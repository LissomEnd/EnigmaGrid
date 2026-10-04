import java.io.*;
import java.util.*;
import org.enigmagrid.core.*;
public class NativeRowFixtures {
 public static void main(String[] args)throws Exception{
  try(PrintWriter out=new PrintWriter(args[0])){
   out.println(18);
   for(int count:new int[]{1,2,16})for(int length:new int[]{1,2,3,16,71,72}){
    List<BoundedCrib.Key> keys=new ArrayList<>();for(int i=0;i<count;i++)keys.add(BoundedCrib.coreAt((i*271828183L+length*17L)%BoundedCrib.DOMAIN));
    int[] input=RowBatch.pack(keys,72-length,length);out.println(input.length+" "+(count*length*26));for(int value:input)out.print(value+" ");out.println();
    for(BoundedCrib.Key key:keys)for(int[] row:BoundedCrib.cpuRows(key,72-length,length))for(int value:row)out.print(value+" ");out.println();
   }
  }
 }
}
