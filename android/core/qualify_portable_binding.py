"""Host extraction test of the actual ComputeService portable binding methods."""
import argparse,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
STUB=r'''
class GpuProcess {
 static int created;boolean closed,fail;int finished,ended;
 GpuProcess(Object context){created++;}boolean isClosed(){return closed;}void close(){closed=true;}
 int portableBegin(int[]r,int[]s,int[]p){if(closed||fail)throw new IllegalStateException("broken");return 5;}
 void portableStep(int id,int[]t,int n){if(fail)throw new IllegalStateException("dispatch");}
 int[] portableFinish(int id){finished++;return new int[0];}void portableClose(int id){ended++;}
}
'''
MAIN=r'''
 public static void main(String[]args)throws Exception{
  BindingCheck owner=new BindingCheck();org.enigmagrid.core.PortableGpuSearch.Backend a=owner.portableBackend();
  int id=a.begin(new int[0],new int[0],new int[0]);a.finish(id);a.close(id);GpuProcess first=owner.portableGpu;
  org.enigmagrid.core.PortableGpuSearch.Backend b=owner.portableBackend();b.begin(new int[0],new int[0],new int[0]);b.close(5);
  if(GpuProcess.created!=1||first.closed)throw new AssertionError("successful units must retainbinding");
  first.fail=true;try{b.step(5,new int[0],16);throw new AssertionError("failure ignored");}catch(IllegalStateException ok){}
  if(!first.closed||owner.portableGpu!=null)throw new AssertionError("failed binding retained");
  owner.portableBackend();if(GpuProcess.created!=2)throw new AssertionError("no replacement");GpuProcess replacement=owner.portableGpu;
  owner.discardPortableBinding(first);if(owner.portableGpu!=replacement||replacement.closed)throw new AssertionError("stale failure discarded replacement");
  owner.closePortableBinding();owner.closePortableBinding();if(!replacement.closed||owner.portableGpu!=null)throw new AssertionError("shutdown leak");
  owner.stopping=true;try{owner.portableBackend();throw new AssertionError("stop rebound");}catch(java.util.concurrent.CancellationException ok){}
  System.out.println("PASS samebinding acrossunits; failedreplacement; staleowner cannotclose newbinding; idempotentstop; no rebindafterstop");
 }
'''
def main():
 p=argparse.ArgumentParser();p.add_argument('--jdk',type=Path,required=True);a=p.parse_args()
 src=(ROOT/'android/app/src/main/java/org/enigmagrid/android/ComputeService.java').read_text()
 methods=src[src.index('    private void discardPortableBinding'):src.index('    /** Two bounded')]
 assert 'closePortableBinding();\n                        network.stopPresence();' in src
 assert 'destroyed=true;closePortableBinding();' in src
 assert 'stopping=true;closePortableBinding();' in src
 with tempfile.TemporaryDirectory(prefix='portable-binding-') as tmp:
  path=Path(tmp)/'BindingCheck.java';path.write_text(STUB+'public class BindingCheck{private final Object portableBindingLock=new Object();private GpuProcess portableGpu;private boolean stopping,destroyed;Object getApplicationContext(){return this;}'+methods+MAIN+'}')
  backend=Path(tmp)/'org/enigmagrid/core/PortableGpuSearch.java';backend.parent.mkdir(parents=True);backend.write_text('package org.enigmagrid.core;public class PortableGpuSearch{public interface Backend{int begin(int[]r,int[]s,int[]p)throws Exception;void step(int id,int[]t,int n)throws Exception;int[]finish(int id)throws Exception;void close(int id)throws Exception;}}')
  subprocess.run([str(a.jdk/'bin/javac.exe'),'-d',tmp,str(path),str(backend)],check=True)
  subprocess.run([str(a.jdk/'bin/java.exe'),'-cp',tmp,'BindingCheck'],check=True)
if __name__=='__main__':main()
