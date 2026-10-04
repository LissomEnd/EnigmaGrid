import org.enigmagrid.core.*;
import java.util.*;
import java.util.concurrent.CancellationException;
public class BatchRowsChecks {
 static class Clock implements WorkControl.Timing {long now,slept;public long nanos(){return now;}public void sleep(long ms){now+=ms*1000000;slept+=ms;}}
 static void check(boolean value,String reason){if(!value)throw new AssertionError(reason);}
 public static void main(String[] args){
  List<BoundedCrib.Key> keys=new ArrayList<>();Map<String,int[]> reference=new HashMap<>();
  for(int i=0;i<128;i++){
   BoundedCrib.Key key=BoundedCrib.coreAt(i*100003L);keys.add(key);
   int[] packed=RowBatch.pack(Collections.singletonList(key),2,16);int[][] cpu=BoundedCrib.cpuRows(key,2,16);
   for(int r=0;r<16;r++)reference.put(Arrays.toString(Arrays.copyOfRange(packed,625+r*9,634+r*9)),cpu[r]);
  }
  Clock clock=new Clock();int[] calls={0},duty={25};boolean[] stop={false};
  BatchedRows batch=new BatchedRows(packed->{
   calls[0]++;clock.now+=10000000;check(packed[0]<=16*72,"unbounded dispatch");int[] flat=new int[packed[0]*26];
   for(int r=0;r<packed[0];r++){int[] row=reference.get(Arrays.toString(Arrays.copyOfRange(packed,625+r*9,634+r*9)));check(row!=null,"descriptor mismatch");System.arraycopy(row,0,flat,r*26,26);}return flat;
  },()->stop[0]);
  AdaptiveRows adaptive=new AdaptiveRows(batch,()->duty[0],()->stop[0],clock);
  adaptive.prepare(keys,2,16);
  for(int i=127;i>=0;i--)check(Arrays.deepEquals(adaptive.rows(keys.get(i),2,16),BoundedCrib.cpuRows(keys.get(i),2,16)),"parity");
  check(calls[0]==8&&adaptive.dispatches()==8,"cache inflated dispatch count");
  check(clock.slept==210,"cached rows delayed CPU or erased next dispatch duty: "+clock.slept);
  duty[0]=0;adaptive.rows(keys.get(0),2,16);check(calls[0]==8&&!adaptive.available(),"disabled dispatch");
  duty[0]=100;adaptive.prepare(keys,2,16);adaptive.rows(keys.get(0),2,16);check(calls[0]==9,"new scope reused cache");
  stop[0]=true;try{adaptive.rows(keys.get(0),2,16);throw new AssertionError("cached cancellation ignored");}catch(CancellationException expected){}
  AdaptiveRows broken=new AdaptiveRows(new BatchedRows(packed->new int[packed[0]*26],()->false),()->100,()->false,new WorkControl.SystemTiming());
  broken.prepare(keys,2,16);check(Arrays.deepEquals(broken.rows(keys.get(0),2,16),BoundedCrib.cpuRows(keys.get(0),2,16))&&broken.failed(),"batch fallback");
  try{RowBatch.pack(keys,2,16);throw new AssertionError("oversized batch");}catch(IllegalArgumentException expected){}
  System.out.println("PASS: 128 keys in 8 batches, reverse request order, CPU parity, exact telemetry, disabled GPU, scope reset, cached cancellation, invalid batch fallback, size bound");
 }
}
