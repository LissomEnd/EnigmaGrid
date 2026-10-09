import org.enigmagrid.core.CpuLaneBudget;

/** Production lane-budget formulas, including small and large processor counts. */
public final class CpuLaneBudgetChecks {
    private static void eq(int actual,int expected,String reason){if(actual!=expected)throw new AssertionError(reason+": "+actual+" != "+expected);}
    private static void bad(int processors,int lanes,boolean independent,boolean gpu){
        try{CpuLaneBudget.forLane(processors,lanes,independent,gpu);throw new AssertionError("Accepted bad topology");}
        catch(IllegalArgumentException expected){}
    }
    public static void main(String[] args){
        eq(CpuLaneBudget.forLane(8,1,false,false),8,"CPU-only one lane");
        eq(CpuLaneBudget.forLane(8,2,false,false),4,"CPU-only two lanes");
        eq(CpuLaneBudget.forLane(8,4,false,false),2,"CPU-only four lanes");
        eq(CpuLaneBudget.forLane(8,2,true,false),7,"mixed2 CPU budget");
        eq(CpuLaneBudget.forLane(8,2,true,true),4,"mixed2 GPU CPU fallback");
        eq(CpuLaneBudget.forLane(8,4,true,false),2,"mixed4 CPU budget");
        eq(CpuLaneBudget.forLane(8,4,true,true),2,"mixed4 GPU CPU fallback");
        eq(CpuLaneBudget.forLane(12,2,true,false),11,"large mixed2");
        eq(CpuLaneBudget.forLane(32,4,true,false),10,"large mixed4");
        eq(CpuLaneBudget.forLane(64,2,true,false),31,"32 thread cap");
        eq(CpuLaneBudget.forLane(2,2,true,false),1,"small CPU lane");
        eq(CpuLaneBudget.forLane(1,2,true,false),1,"single processor CPU lane");
        for(int p=1;p<=64;p++)for(int lanes:new int[]{1,2,4}){
            int cap=Math.min(32,p);
            int cpuOnly=CpuLaneBudget.forLane(p,lanes,false,false);
            if(cpuOnly<1||cpuOnly>cap)throw new AssertionError("Unbounded CPU-only budget");
            if(lanes>1){
                int cpu=CpuLaneBudget.forLane(p,lanes,true,false);
                int gpuFallback=CpuLaneBudget.forLane(p,lanes,true,true);
                if(cpu<1||cpu>cap||gpuFallback<1||gpuFallback>cap)throw new AssertionError("Unbounded mixed budget");
                if(cap>=lanes&&(lanes-1)*cpu+(cap>1?1:0)>cap)
                    throw new AssertionError("CPU lane budgets exceed aggregate cap");
            }
        }
        bad(0,2,true,false);bad(8,3,false,false);bad(8,1,true,false);bad(8,2,false,true);
        System.out.println("PASS mixed2/mixed4 and CPU-only lane budgets, P=1..64, GPU fallback, max32");
    }
}
