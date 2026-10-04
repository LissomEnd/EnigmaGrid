import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'solver/runtime/src'))
from search.portable_search import opencl_devices
class DiscoveryTests(unittest.TestCase):
 def test_broken_platform_and_device_do_not_hide_healthy_gpu(self):
  good=SimpleNamespace(available=True,compiler_available=True,global_mem_size=128*1024*1024)
  class BrokenPlatform:
   def get_devices(self,**kwargs):raise RuntimeError('unavailable ICD')
  class BrokenDevice:
   @property
   def available(self):raise RuntimeError('disconnected device')
  platform=SimpleNamespace(get_devices=lambda **kwargs:[BrokenDevice(),good])
  cl=SimpleNamespace(get_platforms=lambda:[BrokenPlatform(),platform],device_type=SimpleNamespace(GPU=4))
  with patch.dict(sys.modules,pyopencl=cl):self.assertEqual(opencl_devices(),[good])
 def test_missing_runtime_keeps_cpu_fallback(self):
  cl=SimpleNamespace(get_platforms=lambda:(_ for _ in ()).throw(RuntimeError('no runtime')))
  with patch.dict(sys.modules,pyopencl=cl):self.assertEqual(opencl_devices(),[])
if __name__=='__main__':unittest.main()
