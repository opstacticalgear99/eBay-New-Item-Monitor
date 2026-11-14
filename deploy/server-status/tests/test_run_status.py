import importlib.util,json,logging,tempfile,unittest
import types
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('run_status',Path(__file__).parents[1]/'run_with_status.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class StatusTests(unittest.TestCase):
 def test_quota_uses_search_not_bulk(self):
  data={'rateLimits':[{'apiName':'Browse','resources':[{'name':'buy.browse','rates':[{'limit':5000,'remaining':0,'timeWindow':86400,'reset':'2026-11-14T08:00:00Z'}]},{'name':'buy.browse.item.bulk','rates':[{'limit':5000,'remaining':5000,'timeWindow':86400}]}]}]}
  self.assertEqual(m.quota_from_response(data)[0]['remaining'],0)
  self.assertEqual(len(m.quota_from_response(data)),1)
 def test_unavailable_quota_keeps_explicitly_stale_value(self):
  with patch.object(m.requests,'get',side_effect=RuntimeError('secret must not appear')):
   q=m.collect_quota('private-token',{'state':'available','checkedAt':'before','rates':[{'remaining':10}]})
  self.assertEqual(q['state'],'unavailable');self.assertEqual(q['lastKnownAt'],'before');self.assertNotIn('secret',json.dumps(q));self.assertNotIn('private-token',json.dumps(q))
 def test_success_exit_with_warnings_is_not_success_report(self):
  r=m.run_source(lambda:logging.warning('partial search'))
  self.assertEqual(r['state'],'partial');self.assertEqual(r['warnings'],1)
 def test_exception_text_is_not_published(self):
  def fail():raise RuntimeError('secret-password')
  r=m.run_source(fail)
  self.assertEqual(r['state'],'failed');self.assertNotIn('secret-password',json.dumps(r))
 def test_pending_corrupt_file_is_unknown(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(m.os.environ,{'EBAY_OUTBOX_FILE':str(Path(d)/'outbox.json')}):
   self.assertEqual(m.pending_count(),0)
   Path(d,'outbox.json').write_text('broken')
   self.assertIsNone(m.pending_count())
 def test_429_stops_further_network_calls_and_runs_websites(self):
  sent=[];published=[];ran=[]
  def send(session,request,**kwargs):
   sent.append(request.url);r=m.requests.Response();r.status_code=429;r.url=request.url;return r
  fake=types.SimpleNamespace(get_access_token=lambda:'private-token')
  def ebay():
   fake.get_access_token()
   for _ in range(3):
    try:
     r=m.requests.get('https://api.ebay.com/buy/browse/v1/item_summary/search',timeout=1);r.raise_for_status()
    except Exception:logging.error('search unavailable')
  fake.main=ebay;websites=types.SimpleNamespace(main=lambda:ran.append('websites'))
  with patch.object(m.importlib,'import_module',side_effect=[fake,websites]),patch.object(m,'load',return_value={}),patch.object(m,'publish',side_effect=lambda s:published.append(json.loads(json.dumps(s)))),patch.object(m,'collect_quota',return_value={'state':'unavailable'}),patch.object(m,'pending_count',return_value=2),patch.object(m.requests.Session,'send',send):
   self.assertEqual(m.main(),1)
  self.assertEqual(len(sent),1);self.assertEqual(ran,['websites'])
  self.assertEqual(published[-1]['ebay']['state'],'rate_limited')
  self.assertEqual(published[-1]['ebay']['pendingDeliveries'],2)
  self.assertNotIn('private-token',json.dumps(published))

if __name__=='__main__':unittest.main()
