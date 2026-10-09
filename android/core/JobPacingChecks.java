import org.enigmagrid.core.JobPacing;
public class JobPacingChecks {
 public static void main(String[] args){
  if(JobPacing.delayMillis(true,1500)!=0)throw new AssertionError("completed work stalls");
  if(JobPacing.delayMillis(true,200)!=0)throw new AssertionError("short completed work stalls");
  if(JobPacing.delayMillis(true,0)!=0)throw new AssertionError("fast batch stalls");
  if(JobPacing.delayMillis(false,200)!=1000)throw new AssertionError("missing bounded idle poll");
  if(JobPacing.delayMillis(false,60000)!=1000)throw new AssertionError("slow empty request adds excessive idle");
  System.out.println("PASS continuous completed work, idle and failure backoff");
 }
}
