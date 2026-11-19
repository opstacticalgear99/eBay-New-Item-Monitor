import importlib.util,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('controller',Path(__file__).with_name('schedule-controller.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class ControllerTests(unittest.TestCase):
 def test_pause_only_timer_and_preserve_current_scan(self):
  live={'enabled':True,'active':True,'scanRunning':True};calls=[]
  def systemctl(*args):
   calls.append(args)
   if args[0]=='disable':live.update(enabled=False,active=False)
  with patch.object(m,'state',side_effect=lambda:dict(live)),patch.object(m,'systemctl',side_effect=systemctl):code,data=m.change({'enabled':False,'expectedEnabled':True})
  self.assertEqual(code,200);self.assertTrue(data['scanRunning']);self.assertEqual(calls,[('disable','--now','fieldwatch-monitor.timer')])
 def test_resume_persists_across_reboot(self):
  before={'enabled':False,'active':False};after={'enabled':True,'active':True}
  with patch.object(m,'state',side_effect=[before,after]),patch.object(m,'systemctl') as cmd:
   self.assertEqual(m.change({'enabled':True,'expectedEnabled':False})[0],200)
   cmd.assert_called_once_with('enable','--now','fieldwatch-monitor.timer')
 def test_conflict_never_changes_schedule(self):
  with patch.object(m,'state',return_value={'enabled':False}),patch.object(m,'systemctl') as cmd:
   self.assertEqual(m.change({'enabled':False,'expectedEnabled':True})[0],409);cmd.assert_not_called()
 def test_injection_and_invalid_boolean_rejected(self):
  with patch.object(m,'systemctl') as cmd:
   for value in [{'enabled':'false','expectedEnabled':True},{'enabled':False,'expectedEnabled':True,'unit':'ssh.service'},None]:self.assertEqual(m.change(value)[0],400)
   cmd.assert_not_called()
 def test_unconfirmed_actual_state_returns_failure(self):
  with patch.object(m,'state',return_value={'enabled':True,'active':True}),patch.object(m,'systemctl'):
   self.assertEqual(m.change({'enabled':False,'expectedEnabled':True})[0],503)
if __name__=='__main__':unittest.main()
