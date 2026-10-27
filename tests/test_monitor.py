import copy
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
import monitor as m


class MonitorTests(unittest.TestCase):
    def test_sync_batches_all_items_even_after_a_failed_batch(self):
        items = [{'itemId': str(i)} for i in range(205)]
        response = Mock(status_code=200)
        with patch.dict(os.environ, {'APP_API_URL': 'https://example.invalid', 'APP_API_TOKEN': 'test'}), patch.object(m.requests, 'post', side_effect=[RuntimeError('offline'), response, response]) as post, self.assertLogs(level='ERROR'):
            m.sync_app_notifications(items)
        batches = [c.kwargs['json']['items'] for c in post.call_args_list]
        self.assertEqual([len(b) for b in batches], [100, 100, 5])
        self.assertEqual([i['itemId'] for b in batches for i in b], [str(i) for i in range(205)])

    def run_monitor(self, email_failure=False, app_failure=False, baseline=True, errors=False):
        state = {'brand_initialized': baseline, 'seller_initialized': baseline,
                 'brand_seen_ids': ['old-brand'], 'seller_seen_ids': ['old-seller']}
        brands = {'old-brand': {'itemId': 'old-brand'}, 'new': {'itemId': 'new'}}
        sellers = {'old-seller': {'itemId': 'old-seller'}, 'new': {'itemId': 'new'}}
        events = []
        def email(items, errors):
            events.append(('email', [i['itemId'] for i in items]))
            if email_failure:
                raise RuntimeError('SMTP unavailable')
        with TemporaryDirectory() as tmp, patch.object(m, 'STATE_FILE', Path(tmp)/'state.json'), patch.object(m, 'OUTBOX_FILE', Path(tmp)/'outbox.json'), patch.object(m, 'load_monitor_settings', return_value={'brands': [{'label':l,'query':q} for l,q in m.BRANDS], 'sellers':m.SELLERS}), patch.object(m, 'get_access_token', return_value='test'), patch.object(m, 'fetch_brand_items', return_value=(brands, ['partial'] if errors else [])), patch.object(m, 'fetch_all_sellers', return_value=(sellers, [])), patch.object(m, 'send_email', side_effect=email), patch.object(m.requests, 'post', side_effect=RuntimeError('app offline')) as post, patch.dict(os.environ, {'APP_API_URL': 'https://example.invalid' if app_failure else '', 'APP_API_TOKEN': 'test'}):
            m.save_state(state)
            if email_failure:
                with self.assertRaises(RuntimeError):
                    m.main()
                self.assertIn('new', m.load_state()['brand_seen_ids'])
                self.assertEqual(len(m.load_outbox()), 1)
                self.assertFalse(m.load_outbox()[0]['email_sent'])
                self.assertTrue(m.load_outbox()[0]['app_sent'])
            else:
                m.main()
                saved = m.load_state()
                self.assertTrue(set(state['brand_seen_ids']) <= set(saved['brand_seen_ids']))
                self.assertTrue(set(state['seller_seen_ids']) <= set(saved['seller_seen_ids']))
                if errors:
                    self.assertTrue(set(state['brand_seen_ids']) <= set(saved['brand_seen_ids']))
                    self.assertIn('new', saved['brand_seen_ids'])
                else:
                    self.assertIn('new', saved['brand_seen_ids'])
                m.main()
                if not errors:
                    self.assertEqual(len(events), 1 if baseline else 0)
            return events

    def test_existing_ids_and_cross_source_duplicates(self):
        self.assertEqual(self.run_monitor(), [('email', ['new'])])

    def test_gmail_failure_keeps_outbox_and_does_not_block_app(self):
        self.run_monitor(email_failure=True)

    def test_app_failure_does_not_repeat_gmail_or_reset_state(self):
        with self.assertLogs(level='ERROR'):
            self.run_monitor(app_failure=True)

    def test_first_run_builds_baseline_without_notifications(self):
        self.assertEqual(self.run_monitor(baseline=False), [])

    def test_partial_snapshot_keeps_old_brand_state(self):
        self.run_monitor(errors=True)

    def test_new_condition_uses_id_not_english_label(self):
        for title in ('New', 'New with tags', 'Brand New', 'New with box'):
            self.assertTrue(m.is_new_condition({'conditionId':'1000','condition':title}))
        self.assertFalse(m.is_new_condition({'conditionId':'3000','condition':'New'}))
        self.assertFalse(m.is_new_condition({'condition':'Used'}))

    def test_outbox_retries_app_without_repeating_email_after_restart(self):
        with TemporaryDirectory() as tmp, patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'), patch.object(m,'send_email') as email, patch.object(m,'sync_app_notifications',side_effect=[False,True]) as app:
            pending=[{'item':{'itemId':'123'},'email_sent':False,'app_sent':False}]
            m.save_outbox(pending);m.deliver_outbox(pending,[])
            pending=m.load_outbox();self.assertTrue(pending[0]['email_sent'])
            m.deliver_outbox(pending,[])
            self.assertEqual(email.call_count,1);self.assertEqual(app.call_count,2)
            self.assertEqual(m.load_outbox(),[])

    def test_gmail_failure_still_delivers_app_and_retries_only_gmail(self):
        with TemporaryDirectory() as tmp, patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'), patch.object(m,'send_email',side_effect=[RuntimeError('offline'),None]) as email, patch.object(m,'sync_app_notifications',return_value=True) as app:
            pending=[{'item':{'itemId':'123'},'email_sent':False,'app_sent':False}]
            with self.assertRaises(RuntimeError):m.deliver_outbox(pending,[])
            pending=m.load_outbox();self.assertTrue(pending[0]['app_sent'])
            m.deliver_outbox(pending,[])
            self.assertEqual(app.call_count,1);self.assertEqual(email.call_count,2)
            self.assertEqual(m.load_outbox(),[])

    def test_corrupt_outbox_fails_closed(self):
        with TemporaryDirectory() as tmp, patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'):
            m.OUTBOX_FILE.write_text('{broken')
            with self.assertRaises(ValueError):m.load_outbox()

    def test_new_condition_scope_seeds_old_items_without_flooding_then_notifies(self):
        config={'brands':[{'label':'S&S','query':'s&s'}],'sellers':['seller']}
        old={'itemId':'old-tags','conditionId':'1000','condition':'New with tags','_monitor_condition_expansion':True}
        new={**old,'itemId':'fresh-tags'}
        state={'brand_initialized':True,'seller_initialized':True,'brand_seen_ids':['original'],'seller_seen_ids':[],'configured_brand_queries':['s&s'],'configured_sellers':['seller']}
        with TemporaryDirectory() as tmp, patch.object(m,'STATE_FILE',Path(tmp)/'state.json'),patch.object(m,'OUTBOX_FILE',Path(tmp)/'outbox.json'),patch.object(m,'get_access_token',return_value='dummy'),patch.object(m,'load_monitor_settings',return_value=config),patch.object(m,'fetch_all_sellers',return_value=({},[])),patch.object(m,'fetch_brand_items',side_effect=[({'old-tags':old},[]),({'old-tags':old,'fresh-tags':new},[])]),patch.object(m,'send_email') as email,patch.object(m,'sync_app_notifications',return_value=True):
            m.save_state(state);m.main();email.assert_not_called()
            self.assertEqual(m.load_state()['condition_policy_version'],2)
            m.main();self.assertEqual([i['itemId'] for i in email.call_args.args[0]],['fresh-tags'])
            self.assertIn('original',m.load_state()['brand_seen_ids'])

    def test_actual_gmail_smtp_path(self):
        with patch.dict(os.environ, {'GMAIL_ADDRESS': 'test@example.invalid', 'GMAIL_APP_PASSWORD': 'dummy', 'ALERT_TO': 'to@example.invalid'}), patch.object(m.smtplib, 'SMTP_SSL') as smtp:
            m.send_email([{'itemId': 'new', 'title': 'Synthetic', 'itemWebUrl': 'https://www.ebay.com/itm/123456789012'}], [])
        smtp.assert_called_once_with('smtp.gmail.com', 465, timeout=30)
        smtp.return_value.__enter__.return_value.login.assert_called_once_with('test@example.invalid', 'dummy')
        smtp.return_value.__enter__.return_value.sendmail.assert_called_once()


if __name__ == '__main__':
    unittest.main()

