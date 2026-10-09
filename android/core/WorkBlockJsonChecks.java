import org.enigmagrid.core.*;
import java.util.*;
import static org.enigmagrid.core.Canonical.object;
public class WorkBlockJsonChecks {
    public static void main(String[] args) {
        String body=WorkBlockJson.json(object("receipts",Arrays.asList(object("unit",123L,"compute_seconds",0.0507,"result",object("text","A\nB")))));
        if(!body.contains("\"compute_seconds\":0.0507")||!body.contains("A\\nB"))throw new AssertionError(body);
        for(double invalid:new double[]{Double.NaN,Double.POSITIVE_INFINITY,Double.NEGATIVE_INFINITY}) {
            try{WorkBlockJson.json(object("seconds",invalid));throw new AssertionError("Non-finite accepted");}
            catch(IllegalArgumentException expected){}
        }
        try{Canonical.json(0.0507);throw new AssertionError("Scientific canonical format changed");}
        catch(IllegalArgumentException expected){}
        System.out.println("PASS numeric block timings, escaped payload and unchanged scientific canonical format");
    }
}
