import org.enigmagrid.core.JobPacing;
public class JobPacingChecks {
 public static void main(String[] args){
  if(JobPacing.delayMillis(true,1500)!=0)throw new AssertionError("completed work stalls");
  if(JobPacing.delayMillis(true,200)!=800)throw new AssertionError("request flood");
  if(JobPacing.delayMillis(false,200)!=30000)throw new AssertionError("missing idle backoff");
  if(JobPacing.delayMillis(false,60000)!=30000)throw new AssertionError("missing failure backoff");
  System.out.println("PASS completed work pacing, request cap, idle and failure backoff");
 }
}
