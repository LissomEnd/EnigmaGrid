package org.enigmagrid.core;
import java.util.*;

/** One IPC request for rows and solving. Intermediate rows never return before solving. */
public final class SolverKeyBatch {
    public static final int MAX_INPUT=6+72*3+RowBatch.MAX_INPUT;
    public static int[] pack(List<BoundedCrib.Key> keys,int offset,int length,int[][] edges,int pairs,int nodes,int boards){
        if(edges==null||edges.length!=length||pairs<0||pairs>13||nodes<1||nodes>5000||boards<1||boards>64)throw new IllegalArgumentException("Solver key bounds");
        int[] rows=RowBatch.pack(keys,offset,length),request=new int[6+length*3+rows.length];
        request[0]=keys.size();request[1]=length;request[2]=pairs;request[3]=nodes;request[4]=boards;request[5]=rows.length;
        int at=6;for(int[] edge:edges){
            if(edge==null||edge.length!=3||edge[0]<0||edge[0]>=length||edge[1]<0||edge[1]>25||edge[2]<0||edge[2]>25)throw new IllegalArgumentException("Solver key edge");
            for(int v:edge)request[at++]=v;
        }
        System.arraycopy(rows,0,request,at,rows.length);return request;
    }
    public static int[] execute(int[] request,BatchedSolver.Dispatch rowDispatch,BatchedSolver.Dispatch solverDispatch){
        if(request==null||request.length<6||request.length>MAX_INPUT)throw new IllegalArgumentException("Solver key request");
        int count=request[0],length=request[1],rowSize=request[5];
        if(count<1||count>SolverBatch.MAX_CORES||length<1||length>72||rowSize!=625+count*length*9||request.length!=6+length*3+rowSize)throw new IllegalArgumentException("Solver key layout");
        int[][] edges=new int[length][3];int at=6;for(int e=0;e<length;e++)for(int j=0;j<3;j++)edges[e][j]=request[at++];
        int[] rowInput=Arrays.copyOfRange(request,at,request.length);
        if(rowInput[0]!=count*length)throw new IllegalArgumentException("Solver row count");
        int[][][] rows=RowBatch.unpack(rowDispatch.run(rowInput),count,length);
        int[] input=SolverBatch.pack(rows,edges,request[2],request[3],request[4]);
        int[] output=solverDispatch.run(input);
        List<BoardSolver.Result> results=SolverBatch.unpack(output,input);
        int size=6;for(BoardSolver.Result r:results)size+=3+r.partialBoards.size()*26+(r.partialBoards.isEmpty()?0:length*26);
        int[] response=new int[size];response[0]=-2;System.arraycopy(request,0,response,1,5);at=6;
        for(int c=0;c<count;c++){
            BoardSolver.Result r=results.get(c);
            response[at++]=r.status.equals("unsatisfiable")?0:r.status.equals("satisfiable")?1:2;
            response[at++]=r.nodes;response[at++]=r.partialBoards.size();
            for(int[] board:r.partialBoards){System.arraycopy(board,0,response,at,26);at+=26;}
            // No constraint rows are needed for a core with no returned boards.
            if(!r.partialBoards.isEmpty())for(int[] row:rows[c]){System.arraycopy(row,0,response,at,26);at+=26;}
        }
        return response;
    }
    public static List<BoardSolver.Result> unpack(int[] response,int[] request){
        if(response==null||response.length<6||response[0]!=-2)throw new IllegalStateException("Combined solver response");
        for(int i=0;i<5;i++)if(response[1+i]!=request[i])throw new IllegalStateException("Combined solver scope");
        int count=request[0],length=request[1],limit=request[4],stride=3+limit*26,base=5+count*length*26;
        int[] input=new int[base+length*3],output=new int[count*stride];
        System.arraycopy(request,0,input,0,5);System.arraycopy(request,6,input,base,length*3);
        int at=6;
        for(int c=0;c<count;c++){
            if(at>response.length-3)throw new IllegalStateException("Truncated combined header");
            int answers=response[at+2];
            if(answers<0||answers>limit)throw new IllegalStateException("Combined answer count");
            int size=3+answers*26,rowSize=answers==0?0:length*26;
            if(at>response.length-size-rowSize)throw new IllegalStateException("Truncated combined result");
            System.arraycopy(response,at,output,c*stride,size);at+=size;
            if(rowSize>0){
                int[] flat=Arrays.copyOfRange(response,at,at+rowSize);RowBatch.unpack(flat,1,length);
                System.arraycopy(flat,0,input,5+c*length*26,rowSize);at+=rowSize;
            }
        }
        if(at!=response.length)throw new IllegalStateException("Trailing combined data");
        return SolverBatch.unpack(output,input);
    }
}
