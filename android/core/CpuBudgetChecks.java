import org.enigmagrid.core.CpuBudget;

public final class CpuBudgetChecks {
    public static void main(String[] args){
        for(int workers:new int[]{1,2,4,8,16})for(int quota:new int[]{25,50,75,100}){
            long[] cpu={0};CpuBudget budget=new CpuBudget(()->cpu[0],8);long now=0,startCpu=0;
            while(now<40_000_000_000L){
                long wait=budget.delayMillis(now,quota);
                if(quota==100&&wait!=0)throw new AssertionError("Artificial rest at 100%");
                if(now<10_000_000_000L)startCpu=cpu[0];
                long elapsed=wait>0?wait*1_000_000L:10_000_000L;
                if(wait==0)cpu[0]+=elapsed*Math.min(workers,8);
                now+=elapsed;
            }
            double actual=100.0*(cpu[0]-startCpu)/30_000_000_000L/8;
            double expected=Math.min(quota,100.0*Math.min(workers,8)/8);
            if(Math.abs(actual-expected)>5)throw new AssertionError(workers+" workers at "+quota+": "+actual);
            if(budget.measuredPercent()==null)throw new AssertionError("Missing measured average");
            if(budget.delayMillis(now,100)!=0)throw new AssertionError("Old quota delay retained");
        }
        System.out.println("PASS aggregate CPU quota 25/50/75/100 across 1/2/4/8/16 workers, capacity limit and immediate 100%");
    }
}
