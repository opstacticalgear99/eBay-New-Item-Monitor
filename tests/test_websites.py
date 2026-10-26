import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import forward_monitor as f
import ronin_monitor as r
import website_monitor as w
import monitor as m


def empty():return {'version':1,'initialized':False,'known_ids':[],'products':{},'sequence':0,'pending':[]}
def source(**kwargs):return {'id':'fog','name':'Forward Observations Group','url':f.ORIGIN+'/','enabled':True,'new_products':True,'restocks':True,**kwargs}
def product(available=False):return {'id':6787596746911,'title':'Roll 1™ Trauma Pouch','handle':'roll-1™-trauma-pouch','variants':[{'id':40036818911391,'title':'Multicam','available':available,'price':'85.00'}]}


class WebsiteTests(unittest.TestCase):
    def test_forward_exact_availability_price_and_unicode_link(self):
        catalog,products=f.parse_products([product(False)]);p=next(iter(products.values()));v=next(iter(p['variants'].values()))
        self.assertFalse(v['available']);self.assertEqual(v['price'],'US $85.00');self.assertIn('%E2%84%A2',p['url']);self.assertEqual(m.item_link({'itemWebUrl':p['url']}),p['url'])
        self.assertEqual(m.item_link({'itemWebUrl':'https://forwardobservations.com.evil.com/products/a'}),'')
        self.assertEqual(m.item_link({'itemWebUrl':'https://forwardobservations.com/cart'}),'')

    def test_forward_baseline_restock_and_repeated_restock_ids(self):
        catalog,products=f.parse_products([product(False)]);state=r.apply_snapshot(empty(),catalog,products,source_id='fog',source_name='FOG')
        self.assertFalse(state['pending'])
        catalog,products=f.parse_products([product(True)]);state=r.apply_snapshot(state,catalog,products,source_id='fog',source_name='FOG')
        self.assertEqual(len(state['pending']),1);self.assertTrue(state['pending'][0]['item']['itemId'].startswith('fog:'));self.assertEqual(state['pending'][0]['item']['_monitor_label'],'FOG')
        state=r.apply_snapshot(state,catalog,products,source_id='fog');self.assertEqual(len(state['pending']),1)

    def test_unknown_is_not_boolean_string(self):
        p=product();p['variants'][0]['available']='false';_,data=f.parse_products([p]);self.assertIsNone(next(iter(next(iter(data.values()))['variants'].values()))['available'])
        with self.assertRaises(ValueError):f.parse_products([{'id':1,'handle':'a','title':'A','variants':[]}])
        with self.assertRaises(ValueError):f.parse_products([product(),product()])

    def test_pagination_and_failures(self):
        session=Mock();session.get.return_value.status_code=200;session.get.return_value.content=b'json';session.get.return_value.json.return_value={'products':[product()]}
        catalog,data,errors=f.fetch_snapshot(session);self.assertEqual(len(catalog),1);self.assertFalse(errors)
        session.get.return_value.json.return_value={'products':'broken'}
        with self.assertRaises(ValueError):f.fetch_snapshot(session)

    def test_alert_flags_advance_state_without_notifications(self):
        catalog,data=f.parse_products([product(False)]);state=r.apply_snapshot(empty(),catalog,data,source_id='fog')
        catalog,data=f.parse_products([product(True)]);state=r.apply_snapshot(state,catalog,data,source_id='fog',restocks=False)
        self.assertFalse(state['pending']);self.assertTrue(next(iter(state['products'][str(product()['id'])]['variants'].values()))['available'])
        fresh=product();fresh['id']=123;fresh['handle']='new-item';catalog,data=f.parse_products([fresh]);state=r.apply_snapshot(state,catalog,data,source_id='fog',new_products=False)
        self.assertFalse(state['pending']);self.assertIn('123',state['known_ids'])

    def test_pause_drops_pending_and_resume_does_not_replay_changes(self):
        catalog,data=f.parse_products([product(False)]);state=r.apply_snapshot(empty(),catalog,data,source_id='fog')
        state['pending']=[{'item':{'_monitor_labels':['FOG','补货']},'email_sent':False,'app_sent':False}]
        self.assertFalse(r.prepare_site(state,source(enabled=False)));self.assertFalse(state['pending']);self.assertTrue(state['initialized'])
        self.assertTrue(r.prepare_site(state,source()));self.assertFalse(state['initialized'])
        catalog,data=f.parse_products([product(True)]);state=r.apply_snapshot(state,catalog,data,source_id='fog');self.assertFalse(state['pending'])

    def test_website_config_cache_and_supported_url_guard(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(w,'CACHE_FILE',Path(tmp)/'cache.json'),patch.dict(os.environ,{'APP_API_URL':'https://example.invalid','APP_API_TOKEN':'dummy'}),patch.object(w.requests,'get') as get:
            get.return_value.json.return_value={'sites':[source(name='Custom FOG')]}
            self.assertEqual(w.load_settings()['sites'][0]['name'],'Custom FOG');self.assertTrue(w.CACHE_FILE.exists())
            get.side_effect=RuntimeError('offline')
            with self.assertLogs(level='WARNING'):self.assertEqual(w.load_settings()['sites'][0]['name'],'Custom FOG')
        with self.assertRaises(ValueError):w.validate({'sites':[source(url='https://127.0.0.1/')]})

    def test_unknown_sites_are_never_fetched_and_source_errors_are_isolated(self):
        data={'sites':[source(),{**source(id='site-unknown',name='Pending',url='https://example.com/')} ]}
        with patch.object(w,'load_settings',return_value=data),patch.object(r,'main') as ronin,patch.object(f,'main') as fog:
            w.main();self.assertEqual(ronin.call_args.args[0]['enabled'],False);fog.assert_called_once()
            fog.side_effect=RuntimeError('offline')
            with self.assertRaises(RuntimeError):w.main()
            self.assertEqual(ronin.call_count,2)

    def test_forward_state_is_separate_and_failed_read_does_not_reset(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(f,'STATE_FILE',Path(tmp)/'forward.json'),patch.object(f,'fetch_snapshot',side_effect=ValueError('offline')),patch.object(r,'deliver') as deliver:
            state=empty();state['initialized']=True;r.save_state(state,f.STATE_FILE)
            with self.assertLogs(level='WARNING'):f.main(source())
            self.assertTrue(r.load_state(f.STATE_FILE)['initialized']);self.assertEqual(deliver.call_args.kwargs['state_file'],f.STATE_FILE)
