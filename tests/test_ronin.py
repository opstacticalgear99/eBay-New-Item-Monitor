import copy
import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import ronin_monitor as r
import monitor as m

URL=r.ORIGIN+'/store/p339/Carrier.html'
CAT={'339':URL}

def empty():
    return {'version':1,'initialized':False,'known_ids':[],'products':{},'sequence':0,'pending':[]}

def product(stock=False, extra=None):
    variants={'1':{'available':stock,'options':'Size: Medium / Color: Black','price':'US $475.00'}}
    if extra is not None: variants['2']={'available':extra,'options':'Size: Large','price':'US $475.00'}
    return {'title':'Carrier','url':URL,'variants':variants}

def page(inventory=0):
    skus=[{'site_product_sku_id':'1','inventory':inventory,'price':475,'options':{'Size':{'choices':'Medium'}}}]
    return '<h2 id="wsite-com-product-title">Carrier</h2><p>Unavailable Out of Stock</p><input id="wsite-com-product-view-variation-data" value="'+html.escape(json.dumps(skus),quote=True)+'">'


class RoninTests(unittest.TestCase):
    def baseline(self,stock=False):
        return r.apply_snapshot(empty(),CAT,{'339':product(stock)})

    def test_first_scan_never_notifies_and_preserves_original(self):
        original=empty();out=r.apply_snapshot(original,CAT,{'339':product(True)})
        self.assertFalse(out['pending']);self.assertFalse(original['initialized']);self.assertEqual(out['known_ids'],['339'])

    def test_stock_transition_once_then_repeat_cycles_get_unique_ids(self):
        state=r.apply_snapshot(self.baseline(False),CAT,{'339':product(True)})
        self.assertEqual(len(state['pending']),1);event=state['pending'][0]['item'];self.assertIn('补货',event['title']);self.assertIn('Medium',event['condition'])
        again=r.apply_snapshot(state,CAT,{'339':product(True)})
        self.assertEqual(len(again['pending']),1)
        down=r.apply_snapshot(again,CAT,{'339':product(False)})
        up=r.apply_snapshot(down,CAT,{'339':product(True)})
        self.assertEqual(len(up['pending']),2);self.assertNotEqual(up['pending'][0]['item']['itemId'],up['pending'][1]['item']['itemId'])

    def test_unknown_and_missing_do_not_fabricate_stock_changes(self):
        state=self.baseline(False)
        state=r.apply_snapshot(state,CAT,{'339':product(None)})
        self.assertFalse(state['products']['339']['variants']['1']['available']);self.assertFalse(state['pending'])
        state=r.apply_snapshot(state,{},{});self.assertIn('339',state['products'])
        state=r.apply_snapshot(state,CAT,{'339':product(True)})
        self.assertEqual(len(state['pending']),1)

    def test_initial_failed_detail_is_not_misreported_as_new_later(self):
        state=r.apply_snapshot(empty(),CAT,{})
        state=r.apply_snapshot(state,CAT,{'339':product(True)})
        self.assertFalse(state['pending'])

    def test_new_product_once_even_if_out_of_stock(self):
        state=self.baseline();cat={**CAT,'400':r.ORIGIN+'/store/p400/New.html'}
        p={**product(False),'url':cat['400'],'title':'New product'}
        state=r.apply_snapshot(state,cat,{'400':p});self.assertIn('新品',state['pending'][0]['item']['title'])
        state=r.apply_snapshot(state,cat,{'400':p});self.assertEqual(len(state['pending']),1)
        p=copy.deepcopy(p);p['variants']['1']['available']=True
        state=r.apply_snapshot(state,cat,{'400':p});self.assertEqual(len(state['pending']),2)

    def test_new_variant_establishes_baseline_and_removed_variant_is_retained(self):
        state=r.apply_snapshot(self.baseline(True),CAT,{'339':product(True,True)})
        self.assertFalse(state['pending'])
        state=r.apply_snapshot(state,CAT,{'339':product(True)})
        self.assertIn('2',state['products']['339']['variants'])

    def test_embedded_inventory_overrides_generic_html_and_null_is_unknown(self):
        self.assertTrue(r.parse_product(page(3),URL)['variants']['1']['available'])
        self.assertFalse(r.parse_product(page(0),URL)['variants']['1']['available'])
        self.assertIsNone(r.parse_product(page(None),URL)['variants']['1']['available'])
        with self.assertRaises(ValueError):r.parse_product('<html>Challenge</html>',URL)

    def test_catalog_validates_domain_and_no_partial_or_empty_baseline(self):
        xml='<urlset><url><loc>'+URL+'</loc></url><url><loc>https://evil.com/store/p1/x.html</loc></url></urlset>'
        self.assertEqual(r.parse_catalog(xml),CAT)
        with self.assertRaises(ValueError):r.parse_catalog('<urlset/>')
        with self.assertRaises(ValueError):r.parse_catalog('<html>Oops</html>')
        self.assertIsNone(r.product_id('https://www.ronintactics.com.evil.com/store/p1/a.html'))

    def test_scan_rotates_after_last_attempt_when_time_budget_is_reached(self):
        cat={'339':URL,'400':r.ORIGIN+'/store/p400/Next.html'}
        session=Mock();response=session.get.return_value;response.status_code=200;response.content=b'html';response.text=page(1)
        with patch.object(r,'parse_catalog',return_value=cat),patch.object(r.time,'sleep'),patch.object(r.time,'monotonic',side_effect=[0,0,400]):
            catalog,products,errors=r.fetch_snapshot(session,cursor='339')
        self.assertEqual(list(products),['400']);self.assertEqual(session.ronin_cursor,'400');self.assertTrue(errors)
        self.assertEqual(catalog,cat)

    def test_persistence_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(r,'STATE_FILE',Path(tmp)/'state.json'):
            state=self.baseline();r.save_state(state);self.assertEqual(r.load_state(),state)
            r.STATE_FILE.write_text('{oops')
            with self.assertRaises(ValueError):r.load_state()

    def test_smtp_failure_retains_outbox_app_failure_retries_without_second_email(self):
        state=r.apply_snapshot(self.baseline(False),CAT,{'339':product(True)})
        with tempfile.TemporaryDirectory() as tmp,patch.object(r,'STATE_FILE',Path(tmp)/'state.json'),patch.object(r,'send_email') as email,patch.object(r,'sync_app_notifications',return_value=False) as app:
            r.save_state(state);email.side_effect=RuntimeError('offline')
            with self.assertRaises(RuntimeError):r.deliver(state,[])
            self.assertFalse(r.load_state()['pending'][0]['email_sent']);app.assert_not_called()
            email.side_effect=None;r.deliver(state,[])
            self.assertTrue(r.load_state()['pending'][0]['email_sent']);self.assertEqual(email.call_count,2)
            app.return_value=True;r.deliver(state,[])
            self.assertEqual(email.call_count,2);self.assertFalse(r.load_state()['pending'])

    def test_ronin_email_and_sync_url_allowlist(self):
        self.assertEqual(m.item_link({'itemWebUrl':URL}),URL)
        self.assertEqual(m.item_link({'itemWebUrl':'https://www.ronintactics.com.evil.com/store/p1/x.html'}),'')
        self.assertEqual(m.item_link({'itemWebUrl':'https://www.ronintactics.com/checkout'}),'')
        self.assertEqual(m.item_link({'itemWebUrl':'https://www.ebay.com/itm/123'}),'https://www.ebay.com/itm/123')

    def test_failed_catalog_still_retries_pending_delivery_without_reset(self):
        state=self.baseline()
        with patch.object(r,'load_state',return_value=state),patch.object(r,'fetch_snapshot',side_effect=ValueError('offline')),patch.object(r,'deliver') as deliver:
            with self.assertLogs(level='WARNING'):r.main()
            deliver.assert_called_once_with(state,[])
