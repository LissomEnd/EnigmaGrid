import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import coordinator

class EngineEligibility(unittest.TestCase):
 def device(self,platform="Android 15",engines=("bounded_crib_v1",)):
  meta={"platform":platform}
  if engines is not None:meta["supported_engines"]=list(engines)
  return dict(enabled=1,quarantined=0,settings_json=json.dumps({"cpu_percent":60,"allow_cpu":True}),capabilities_json='["cpu","bounded_crib_v1"]',meta_json=json.dumps(meta))
 def segment(self,engine):return dict(engine=engine,config_json='{"requires":["cpu"]}')
 def test_android_rejects_legacy_accepts_supported(self):
  self.assertFalse(coordinator.device_eligible(self.device(),self.segment("portable_event_v1"))[0])
  self.assertTrue(coordinator.device_eligible(self.device(),self.segment("bounded_crib_v1"))[0])
 def test_legacy_windows_still_works(self):
  self.assertTrue(coordinator.device_eligible(self.device("Windows",None),self.segment("portable_event_v1"))[0])
 def test_old_android_and_empty_list_fail_closed(self):
  for d in [self.device(engines=None),self.device(engines=())]:
   self.assertFalse(coordinator.device_eligible(d,self.segment("portable_event_v1"))[0])
 def test_negotiation_survives_metadata_sanitization(self):
  self.assertEqual(coordinator.sanitize_meta({"supported_engines":["bounded_crib_v1","unknown"]})["supported_engines"],["bounded_crib_v1"])
if __name__=="__main__":unittest.main()
