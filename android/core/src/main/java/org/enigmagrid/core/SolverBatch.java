package org.enigmagrid.core;
import java.util.*;

/** Bounded wire layout shared with the Vulkan fixed-core solver. */
public final class SolverBatch {
    public static final int MAX_CORES=512,OUTPUT_STRIDE=1667;
    public static int[] pack(int[][][] rows,int[][] edges,int pairs,int nodes,int boards){
        if(rows==null||rows.length<1||rows.length>MAX_CORES||edges==null||edges.length<1||edges.length>72||pairs<0||pairs>13||nodes<1||nodes>5000||boards<1||boards>64)throw new IllegalArgumentException("Solver batch bounds");
        int[] result=new int[5+rows.length*edges.length*26+edges.length*3];
        result[0]=rows.length;result[1]=edges.length;result[2]=pairs;result[3]=nodes;result[4]=boards;int at=5;
        for(int[][] core:rows){
            if(core==null||core.length!=edges.length)throw new IllegalArgumentException("Solver row count");
            for(int[] row:core){
                if(row==null||row.length!=26)throw new IllegalArgumentException("Solver row length");
                for(int x=0;x<26;x++)if(row[x]<0||row[x]>=26||row[row[x]]!=x)throw new IllegalArgumentException("Solver involution");
                for(int x:row)result[at++]=x;
            }
        }
        for(int[] edge:edges){
            if(edge==null||edge.length!=3||edge[0]<0||edge[0]>=edges.length||edge[1]<0||edge[1]>=26||edge[2]<0||edge[2]>=26)throw new IllegalArgumentException("Solver edge");
            for(int x:edge)result[at++]=x;
        }
        return result;
    }
    public static List<BoardSolver.Result> unpack(int[] output,int[] input){
        int count=input[0],length=input[1],pairs=input[2],nodes=input[3],limit=input[4];
        int stride=3+limit*26;
        if(output!=null&&output.length>=2&&output[0]==-1){
            if(output[1]!=count)throw new IllegalStateException("Compact solver core count");
            int[] dense=new int[count*stride];int cursor=2;
            for(int core=0;core<count;core++){
                if(cursor>output.length-3)throw new IllegalStateException("Truncated solver header");
                int answers=output[cursor+2];
                if(answers<0||answers>limit)throw new IllegalStateException("Compact solver answer count");
                int size=3+answers*26;
                if(cursor>output.length-size)throw new IllegalStateException("Truncated solver boards");
                System.arraycopy(output,cursor,dense,core*stride,size);cursor+=size;
            }
            if(cursor!=output.length)throw new IllegalStateException("Trailing solver data");
            output=dense;
        }
        if(output==null||output.length!=count*stride)throw new IllegalStateException("Solver output size");
        List<BoardSolver.Result> results=new ArrayList<>();
        for(int core=0;core<count;core++){
            int base=core*stride,status=output[base],visited=output[base+1],answers=output[base+2];
            if(status<0||status>2||visited<1||visited>nodes||answers<0||answers>limit||(status==0&&answers!=0)||(status==1&&answers==0))throw new IllegalStateException("Solver output bounds");
            List<int[]> boards=new ArrayList<>();Set<String> unique=new HashSet<>();
            for(int n=0;n<answers;n++){
                int[] board=Arrays.copyOfRange(output,base+3+n*26,base+3+(n+1)*26);int used=0;
                for(int x=0;x<26;x++){
                    int y=board[x];if(y< -1||y>=26||(y>=0&&board[y]!=x))throw new IllegalStateException("Invalid solver board");
                    if(y>x)used++;
                }
                if(used>pairs||!unique.add(Arrays.toString(board)))throw new IllegalStateException("Invalid or duplicate solver answer");
                int edgeBase=5+count*length*26;
                for(int e=0;e<length;e++){
                    int position=input[edgeBase+e*3],a=input[edgeBase+e*3+1],b=input[edgeBase+e*3+2];
                    if(board[a]<0||board[b]<0||input[5+core*length*26+position*26+board[a]]!=board[b])throw new IllegalStateException("Solver constraint mismatch");
                }
                boards.add(board);
            }
            results.add(new BoardSolver.Result(status==0?"unsatisfiable":status==1?"satisfiable":"unknown_budget",visited,boards));
        }
        return results;
    }
}
