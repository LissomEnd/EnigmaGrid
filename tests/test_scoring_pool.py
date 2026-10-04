import sys,unittest,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
from scoring_pool import OrderedScorers
class ScoringTests(unittest.TestCase):
 def test_order_and_all_devices(self):
  barrier=threading.Barrier(3);seen=[]
  def device(i):
   def score(keys):
    seen.append(i);barrier.wait(timeout=2);return [v*7 for v in keys]
   return score
  pool=OrderedScorers([device(i) for i in range(3)])
  try:self.assertEqual(sum(pool.score(list(range(11))),[]),[v*7 for v in range(11)]);self.assertEqual(set(seen),{0,1,2})
  finally:pool.close()
 def test_small_and_empty(self):
  pool=OrderedScorers([lambda k:list(k)]*3)
  try:self.assertEqual(pool.score([]),[]);self.assertEqual(pool.score([4]),[[4]])
  finally:pool.close()
 def test_failure_waits_for_other_device(self):
  finished=threading.Event()
  def bad(k):raise ValueError('device failure')
  def slow(k):time.sleep(.03);finished.set();return k
  pool=OrderedScorers([bad,slow])
  try:
   with self.assertRaises(ValueError):pool.score([1,2])
   self.assertTrue(finished.is_set())
  finally:pool.close()
if __name__=='__main__':unittest.main()
