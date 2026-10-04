import org.enigmagrid.core.UpdatePolicy;
import static org.enigmagrid.core.UpdatePolicy.State.*;
public class UpdatePolicyChecks {
 public static void main(String[] args){
  java.util.Map<String,Object> config=new java.util.HashMap<>();
  config.put("min_worker_version","0.4.3");
  check(UpdatePolicy.androidMinimum(config).equals("0.4.3"));
  config.put("min_android_worker_version","0.4.10");
  check(UpdatePolicy.androidMinimum(config).equals("0.4.10"));
  config.put("min_android_worker_version","");
  check(UpdatePolicy.androidMinimum(config).equals(""));
  for(Object invalid:new Object[]{null,10,"bad"}){
   config.put("min_android_worker_version",invalid);
   try{UpdatePolicy.androidMinimum(config);throw new AssertionError("Malformed Android minimum accepted");}catch(IllegalArgumentException expected){}
  }
  check(UpdatePolicy.evaluate("0.4.4","0.4.3","0.4.4")==CURRENT);
  check(UpdatePolicy.evaluate("0.4.4","0.4.3","0.4.10")==OPTIONAL);
  check(UpdatePolicy.evaluate("0.4.4","0.4.5","0.4.5")==REQUIRED);
  check(UpdatePolicy.evaluate("0.4.4","0.4.6","0.4.5")==REQUIRED_UNAVAILABLE);
  check(UpdatePolicy.evaluate("0.4.4","0.4.5",null)==REQUIRED_UNAVAILABLE);
  check(UpdatePolicy.evaluate("0.4.4","",null)==CURRENT);
  check(UpdatePolicy.evaluate("0.4.4","0.4.3","0.4.2")==CURRENT);
  check(UpdatePolicy.compare("1.0.0","0.99.99")>0);
  for(String bad:new String[]{"0.4", "0.4.4-dev", "01.4.4", "0.4.-1", "0.4.9999999999", "0.4.4\n"}) {
   try{UpdatePolicy.compare(bad,"0.4.4");throw new AssertionError(bad);}catch(IllegalArgumentException expected){}
  }
  System.out.println("PASS: optional, mandatory, unavailable mandatory release, downgrade and malformed metadata");
 }
 static void check(boolean value){if(!value)throw new AssertionError();}
}
