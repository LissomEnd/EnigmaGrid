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
  System.out.println("PASS: parity, GPU duty, disabled GPU, native failure fallback, failure latch, malformed output, cancellation");
 }
}
