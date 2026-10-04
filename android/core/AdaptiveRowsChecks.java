import org.enigmagrid.core.*;
import java.util.*;
import java.util.concurrent.CancellationException;
public class AdaptiveRowsChecks {
 static class Clock implements WorkControl.Timing {long now,slept;public long nanos(){return now;}public void sleep(long ms){now+=ms*1000000;slept+=ms;}}
 public static void main(String[] args){
  BoundedCrib.Key key=BoundedCrib.coreAt(123456);int[][] expected=BoundedCrib.cpuRows(key,3,16);Clock clock=new Clock();int[] calls={0},duty={25};
  AdaptiveRows rows=new AdaptiveRows((k,o,n)->{calls[0]++;clock.now+=10000000;return BoundedCrib.cpuRows(k,o,n);},()->duty[0],()->false,clock);
  if(!Arrays.deepEquals(expected,rows.rows(key,3,16)))throw new AssertionError("parity");rows.rows(key,3,16);
  if(rows.dispatches()!=2||!rows.available())throw new AssertionError("successful GPU telemetry");
  if(clock.slept!=30||calls[0]!=2)throw new AssertionError("GPU duty");duty[0]=0;rows.rows(key,3,16);if(calls[0]!=2)throw new AssertionError("GPU disabled");
  if(rows.available()||rows.dispatches()!=2)throw new AssertionError("disabled telemetry");
  int[] failures={0};AdaptiveRows broken=new AdaptiveRows((k,o,n)->{failures[0]++;throw new UnsatisfiedLinkError();},()->100,()->false,clock);
  if(!Arrays.deepEquals(expected,broken.rows(key,3,16)))throw new AssertionError("fallback");broken.rows(key,3,16);if(failures[0]!=1||!broken.failed())throw new AssertionError("failure latch");
  if(broken.available()||broken.dispatches()!=0)throw new AssertionError("failed telemetry");
  AdaptiveRows invalid=new AdaptiveRows((k,o,n)->new int[n][26],()->100,()->false,clock);if(!Arrays.deepEquals(expected,invalid.rows(key,3,16))||!invalid.failed())throw new AssertionError("malformed fallback");
  AdaptiveRows stopped=new AdaptiveRows((k,o,n)->{throw new AssertionError("dispatch after stop");},()->100,()->true,clock);
  try{stopped.rows(key,3,16);throw new AssertionError("stop ignored");}catch(CancellationException good){}
  int[] preparations={0};
  AdaptiveRows preparationFailure=new AdaptiveRows(new BoundedCrib.RowProvider(){
   public void prepare(List<BoundedCrib.Key> keys,int o,int n){preparations[0]++;throw new UnsatisfiedLinkError("driver initialization");}
   public int[][] rows(BoundedCrib.Key k,int o,int n){throw new AssertionError("failed backend reused");}
  },()->100,()->false,clock);
  preparationFailure.prepare(Collections.singletonList(key),3,16);
  preparationFailure.prepare(Collections.singletonList(key),3,16);
  if(preparations[0]!=1||!preparationFailure.failed()||!Arrays.deepEquals(expected,preparationFailure.rows(key,3,16)))throw new AssertionError("preparation fallback");
  AdaptiveRows preparationCancelled=new AdaptiveRows(new BoundedCrib.RowProvider(){
   public void prepare(List<BoundedCrib.Key> keys,int o,int n){throw new CancellationException();}
   public int[][] rows(BoundedCrib.Key k,int o,int n){throw new AssertionError();}
  },()->100,()->false,clock);
  try{preparationCancelled.prepare(Collections.singletonList(key),3,16);throw new AssertionError("preparation cancellation swallowed");}catch(CancellationException good){}
  if(preparationCancelled.failed())throw new AssertionError("cancellation disabled GPU");
  int[] timeoutCalls={0};
  AdaptiveRows timedOut=new AdaptiveRows((k,o,n)->{timeoutCalls[0]++;throw new IllegalStateException("GPU process timeout",new java.util.concurrent.TimeoutException());},()->100,()->false,clock);
  if(!Arrays.deepEquals(expected,timedOut.rows(key,3,16)))throw new AssertionError("timeout CPU parity");
  timedOut.rows(key,3,16);
  if(timeoutCalls[0]!=1||!timedOut.failed()||timedOut.available())throw new AssertionError("timeout backend reused");
  boolean[] cancelledDuringDispatch={false};
  AdaptiveRows interruptedDriver=new AdaptiveRows((k,o,n)->{cancelledDuringDispatch[0]=true;throw new IllegalStateException("driver disconnected");},()->100,()->cancelledDuringDispatch[0],clock);
  try{interruptedDriver.rows(key,3,16);throw new AssertionError("stop during driver failure ignored");}catch(CancellationException good){}
  AdaptiveRows cancelledDriver=new AdaptiveRows((k,o,n)->{throw new CancellationException("GPU operation cancelled");},()->100,()->false,clock);
  try{cancelledDriver.rows(key,3,16);throw new AssertionError("driver cancellation swallowed");}catch(CancellationException good){}
  if(cancelledDriver.failed())throw new AssertionError("driver cancellation disabled GPU");
  System.out.println("PASS: parity, GPU duty, disabled GPU, native failure fallback, failure latch, malformed output, cancellation");
 }
}
