import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import monitor as m


def settings(brands=None,sellers=None):
    return {'brands': brands or [{'label':l,'query':q} for l,q in m.BRANDS], 'sellers': sellers or list(m.SELLERS)}


class SettingsTests(unittest.TestCase):
    def test_defaults_match_server_defaults_exactly(self):
        self.assertEqual(json.loads(Path('monitor-defaults.json').read_text()),settings())

    def test_load_config_and_fallback_to_cached_on_outage(self):
        cached=settings([{'label':'Custom','query':'Custom query'}],['new-seller'])
        with patch.dict(os.environ,{'APP_API_URL':'https://example.invalid','APP_API_TOKEN':'dummy'}), patch.object(m.requests,'get') as get:
            get.return_value.json.return_value=cached
            self.assertEqual(m.load_monitor_settings({}),cached)
            get.assert_called_once_with('https://example.invalid/api/monitor/settings',headers={'Authorization':'Bearer dummy'},timeout=m.REQUEST_TIMEOUT)
            get.side_effect=RuntimeError('offline')
            with self.assertLogs(level='WARNING'):
                self.assertEqual(m.load_monitor_settings({'monitor_settings':cached}),cached)

    def test_new_query_baseline_and_overlap_with_established_query(self):
        item={'itemId':'historical'}
        with patch.object(m,'api_search_brand',side_effect=[[copy.deepcopy(item)],[copy.deepcopy(item)]]) as search:
            items,errors=m.fetch_brand_items(Mock(),'token',[('New','new query'),('Old','old query')],{'old query'})
            self.assertTrue(items['historical']['_monitor_notify'])
            self.assertEqual(search.call_args_list[0].args[-1],'new query')
            self.assertFalse(errors)
        with patch.object(m,'api_search_brand',return_value=[copy.deepcopy(item)]):
            items,_=m.fetch_brand_items(Mock(),'token',[('New','new query')],{'old query'})
            self.assertFalse(items['historical']['_monitor_notify'])

    def test_new_seller_baseline_does_not_suppress_existing_seller(self):
        session=Mock();session.get.return_value.status_code=200
        session.get.return_value.json.return_value={'itemSummaries':[
            {'itemId':'old','seller':{'username':'OLD-SELLER'}},
            {'itemId':'new','seller':{'username':'new-seller'}}]}
        items,errors=m.fetch_all_sellers(session,'token',['old-seller','new-seller'],{'old-seller'})
        self.assertTrue(items['old']['_monitor_notify'])
        self.assertFalse(items['new']['_monitor_notify'])
        self.assertFalse(errors)
        self.assertIn('old-seller|new-seller',session.get.call_args.kwargs['params']['filter'])

    def test_new_source_first_run_seeds_ids_then_notifies_only_new_arrival(self):
        config=settings([{'label':'New','query':'new-query'}],['new-seller'])
        with TemporaryDirectory() as tmp, patch.object(m,'STATE_FILE',Path(tmp)/'state.json'),patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'), patch.object(m,'load_monitor_settings',return_value=config), patch.object(m,'get_access_token',return_value='dummy'), patch.object(m,'send_email') as email, patch.object(m,'sync_app_notifications'), patch.object(m,'api_search_brand') as brand, patch.object(m.requests,'Session') as session:
            m.save_state({'brand_initialized':True,'seller_initialized':True,'brand_seen_ids':['old-brand'],'seller_seen_ids':['old-seller']})
            brand.return_value=[{'itemId':'historical-brand'}]
            response=session.return_value.get.return_value;response.status_code=200
            response.json.return_value={'itemSummaries':[{'itemId':'historical-seller','seller':{'username':'new-seller'}}]}
            m.main();email.assert_not_called()
            first=m.load_state();self.assertIn('historical-brand',first['brand_seen_ids']);self.assertIn('old-brand',first['brand_seen_ids']);self.assertIn('historical-seller',first['seller_seen_ids'])
            brand.return_value=[{'itemId':'historical-brand'},{'itemId':'fresh'}]
            m.main()
            email.assert_called_once();self.assertEqual([x['itemId'] for x in email.call_args.args[0]],['fresh'])
            m.main();email.assert_called_once()

    def test_failed_baseline_is_retried_without_notifications(self):
        config=settings([{'label':'New','query':'new-query'}])
        with TemporaryDirectory() as tmp, patch.object(m,'STATE_FILE',Path(tmp)/'state.json'),patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'), patch.object(m,'load_monitor_settings',return_value=config), patch.object(m,'get_access_token',return_value='dummy'), patch.object(m,'send_email') as email, patch.object(m,'fetch_all_sellers',return_value=({},[])), patch.object(m,'api_search_brand',side_effect=RuntimeError('offline')):
            m.save_state({'brand_initialized':True,'seller_initialized':True,'brand_seen_ids':['old'],'seller_seen_ids':[]})
            with self.assertLogs(level='WARNING'): m.main()
            state=m.load_state();self.assertNotIn('new-query',state.get('configured_brand_queries',[]));self.assertEqual(state['brand_seen_ids'],['old']);email.assert_not_called()

    def test_load_state_preserves_new_configuration_fields(self):
        state={'brand_initialized':True,'seller_initialized':True,'brand_seen_ids':['a'],'seller_seen_ids':['b'],'configured_brand_queries':['q'],'configured_sellers':['s'],'monitor_settings':settings()}
        with TemporaryDirectory() as tmp,patch.object(m,'STATE_FILE',Path(tmp)/'state.json'),patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'):
            m.save_state(state);self.assertEqual(m.load_state(),state)
