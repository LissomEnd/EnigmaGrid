import org.enigmagrid.core.BoardSolver;
import java.util.*;
public class BoardCli {
    public static void main(String[] args) {
        Scanner input=new Scanner(System.in);
        while(input.hasNextInt()) {
            int nr=input.nextInt(),ne=input.nextInt(),pairs=input.nextInt(),nodes=input.nextInt(),solutions=input.nextInt();
            int[][] rows=new int[nr][26],edges=new int[ne][3];
            for(int[] row:rows)for(int j=0;j<26;j++)row[j]=input.nextInt();
            for(int[] edge:edges)for(int j=0;j<3;j++)edge[j]=input.nextInt();
            BoardSolver.Result result=BoardSolver.solve(rows,edges,pairs,nodes,solutions,()->false);
            StringJoiner out=new StringJoiner(" ");out.add(result.status);out.add(""+result.nodes);
            for(int[] board:result.partialBoards)for(int x:board)out.add(""+x);
            System.out.println(out);
        }
    }
}
