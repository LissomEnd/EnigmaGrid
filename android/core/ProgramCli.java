import org.enigmagrid.core.*;
import java.util.*;
public class ProgramCli {
    public static void main(String[] args) {
        Scanner in=new Scanner(System.in);
        while(in.hasNext()) {
            String cipher=in.next();long ordinal=in.nextLong();int chunk=in.nextInt(),limit=in.nextInt(),count=in.nextInt();
            List<ResearchProgram.Hypothesis> rows=new ArrayList<>();
            for(int i=0;i<count;i++)rows.add(new ResearchProgram.Hypothesis(in.next(),in.nextInt()));
            System.out.println(Canonical.json(ResearchProgram.jobAt(cipher,rows,ordinal,chunk,limit)));
        }
    }
}
