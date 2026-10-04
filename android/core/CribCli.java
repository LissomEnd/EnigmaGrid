import org.enigmagrid.core.*;
import java.util.*;
public class CribCli {
    public static void main(String[] args) {
        Scanner in=new Scanner(System.in);
        while(in.hasNext()) {
            String cipher=in.next(),crib=in.next();int offset=in.nextInt(),pairs=in.nextInt(),nodes=in.nextInt(),boards=in.nextInt(),completions=in.nextInt(),candidates=in.nextInt(),count=in.nextInt();
            long[] indices=new long[count];for(int i=0;i<count;i++)indices[i]=in.nextLong();
            System.out.println(Canonical.json(BoundedCrib.search(cipher,crib,offset,indices,pairs,nodes,boards,completions,candidates,()->false)));
        }
    }
}
