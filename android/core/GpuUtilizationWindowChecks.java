import org.enigmagrid.core.GpuUtilizationWindow;
public final class GpuUtilizationWindowChecks {
 public static void main(String[] args){
  GpuUtilizationWindow w=new GpuUtilizationWindow();
  if(!Float.isNaN(w.add(0,0,0)))throw new AssertionError("Missing read became idle");
  if(w.add(1000,20,100)!=20||w.add(1100,0,0)!=20)throw new AssertionError("Destructive counter read lost valid interval");
  if(Math.abs(w.add(2000,80,400)-20)>0.001)throw new AssertionError("Incorrect weighting");
  if(w.add(2100,Double.NaN,100)!=20||w.add(2200,200,100)!=20)throw new AssertionError("Invalid hardware read accepted");
  if(!Float.isNaN(w.add(12000,0,0)))throw new AssertionError("Stale sample survived window");
  if(w.add(13000,0,100)!=0)throw new AssertionError("Actual idle discarded");
  System.out.println("PASS GPU interval weighting, reset counter, invalid readings, expiry and real idle");
 }
}
