import org.enigmagrid.core.QualificationProtection;
import org.enigmagrid.core.BoundedCrib;
import java.util.concurrent.*;

public class QualificationProtectionChecks {
    static void check(boolean value){if(!value)throw new AssertionError();}
    public static void main(String[] args)throws Exception {
        QualificationProtection safety=new QualificationProtection("Cooling CPU");
        check(QualificationProtection.interrupted(safety));
        check(QualificationProtection.interrupted(new ExecutionException(new CompletionException(safety))));
        check(!QualificationProtection.interrupted(new IllegalStateException("Device protection: Cooling CPU")));
        check(!QualificationProtection.interrupted(new IllegalStateException("GPU mismatch",safety)));
        check(!QualificationProtection.interrupted(new ExecutionException(new IllegalStateException("Receipt mismatch"))));
        ExecutorService pool=Executors.newSingleThreadExecutor();
        try {
            Future<?> task=pool.submit(()->BoundedCrib.search("BDZGO","BD",0,new long[]{0,1,2,3},10,5000,64,256,3,()->{throw safety;},null,2));
            try{task.get();throw new AssertionError("Protection ignored");}
            catch(ExecutionException e){check(QualificationProtection.interrupted(e));}
        }finally{pool.shutdownNow();check(pool.awaitTermination(8,TimeUnit.SECONDS));}
        System.out.println("PASS safety interruption survives compute futures; numerical failures are not misclassified");
    }
}
