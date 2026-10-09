import java.util.*;
import org.enigmagrid.core.*;

public final class SolverBatchChecks {
    static int[] cpuDispatch(int[] input){
        int count=input[0],length=input[1],stride=3+input[4]*26,at=5;
        int[][][] rows=new int[count][length][26];
        for(int c=0;c<count;c++)for(int e=0;e<length;e++)for(int x=0;x<26;x++)rows[c][e][x]=input[at++];
        int[][] edges=new int[length][3];for(int e=0;e<length;e++)for(int j=0;j<3;j++)edges[e][j]=input[at++];
        int[] output=new int[count*stride];
        for(int c=0;c<count;c++){
            BoardSolver.Result r=BoardSolver.solve(rows[c],edges,input[2],input[3],input[4],()->false);
            int base=c*stride;output[base]=r.status.equals("satisfiable")?1:r.status.equals("unsatisfiable")?0:2;
            output[base+1]=r.nodes;output[base+2]=r.partialBoards.size();
            for(int n=0;n<r.partialBoards.size();n++)System.arraycopy(r.partialBoards.get(n),0,output,base+3+n*26,26);
        }
        return output;
    }
    interface Check { void run(); }
    static void rejects(Check check){try{check.run();}catch(IllegalArgumentException|IllegalStateException expected){return;}throw new AssertionError("Accepted invalid solver data");}
    static void concurrentSearches() {
        AdaptiveRows shared=new AdaptiveRows(new BatchedSolver(BoundedCrib::cpuRows,SolverBatchChecks::cpuDispatch,()->false).withCpuShare(),()->100,()->false,new WorkControl.SystemTiming());
        java.util.concurrent.ExecutorService jobs=java.util.concurrent.Executors.newFixedThreadPool(4);
        java.util.concurrent.CountDownLatch start=new java.util.concurrent.CountDownLatch(1);
        List<java.util.concurrent.Future<?>> futures=new ArrayList<>();
        try {
            for(int job=0;job<4;job++){
                final int ordinal=job;
                final BoundedCrib.RowProvider provider=shared.newSearch();
                futures.add(jobs.submit(()->{
                    try{start.await();}catch(InterruptedException e){Thread.currentThread().interrupt();throw new java.util.concurrent.CancellationException();}
                    long[] keys=new long[128];for(int i=0;i<128;i++)keys[i]=(ordinal*128L+i)*7919L;
                    Map<String,Object> expected=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,keys,2,100,8,8,16,()->false);
                    Map<String,Object> actual=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,keys,2,100,8,8,16,()->false,provider,8);
                    if(!Canonical.json(expected).equals(Canonical.json(actual)))throw new AssertionError("Concurrent search cache leaked across jobs");
                }));
            }
            start.countDown();
            for(java.util.concurrent.Future<?> future:futures)future.get(15,java.util.concurrent.TimeUnit.SECONDS);
            if(shared.failed()||shared.dispatches()!=4)throw new AssertionError("Concurrent GPU accounting not shared");
        }catch(Exception e){throw new AssertionError("Concurrent searches failed",e);}
        finally{jobs.shutdownNow();}
    }
    public static void main(String[] args)throws Exception{
        concurrentSearches();
        long[] indices=new long[128];for(int i=0;i<indices.length;i++)indices[i]=i*7919;
        for(int size:new int[]{64,128}){
            BatchedSolver full=new BatchedSolver(BoundedCrib::cpuRows,SolverBatchChecks::cpuDispatch,()->false).withGpuOnly().withBatchSize(size);
            String cipher="QWERTZUIOPASDFGHJKLYXCVBNM",crib="ABCDEFGHIJKLMNOPQRSTUVWX";
            Map<String,Object> expected=BoundedCrib.search(cipher,crib,0,indices,10,5000,64,256,2048,()->false,null,8);
            Map<String,Object> actual=BoundedCrib.search(cipher,crib,0,indices,10,5000,64,256,2048,()->false,full,8);
            if(!Canonical.json(expected).equals(Canonical.json(actual)))throw new AssertionError("Full GPU dispatch parity "+size);
            if(((Number)full.timings().get("dispatches")).intValue()!=128/size)throw new AssertionError("Wrong dispatch width "+size);
        }
        for(int length:new int[]{21,22,23,24,25}){
            String cipher="QWERTZUIOPASDFGHJKLYXCVBNM";
            char[] letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ".substring(0,length).toCharArray();
            for(int i=0;i<length;i++)if(letters[i]==cipher.charAt(i))letters[i]=(char)('A'+(letters[i]-'A'+1)%26);
            String crib=new String(letters);
            BatchedSolver qualified=new BatchedSolver(BoundedCrib::cpuRows,SolverBatchChecks::cpuDispatch,()->false,true).withCpuShare();
            Map<String,Object> reference=BoundedCrib.search(cipher,crib,0,indices,10,5000,64,256,32,()->false,null,8);
            Map<String,Object> actual=BoundedCrib.search(cipher,crib,0,indices,10,5000,64,256,32,()->false,qualified,8);
            if(!Canonical.json(reference).equals(Canonical.json(actual)))throw new AssertionError("Qualified length receipt mismatch: "+length);
            long calls=((Number)qualified.timings().get("dispatches")).longValue();
            if(calls!=(length>=22&&length<=24?1:0))throw new AssertionError("Qualified scope did not dispatch correctly: "+length);
        }
        for(int cap:new int[]{1,16,128}){
            Map<String,Object> reference=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->false);
            BatchedSolver backend=new BatchedSolver(BoundedCrib::cpuRows,SolverBatchChecks::cpuDispatch,()->false);
            Map<String,Object> actual=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->false,backend,8);
            if(!Canonical.json(reference).equals(Canonical.json(actual)))throw new AssertionError("Full solver receipt differs at candidate cap "+cap);
            Map<String,Object> timing=backend.timings();
            long dispatches=((Number)timing.get("dispatches")).longValue();
            if(dispatches<1||dispatches>2)throw new AssertionError("Batch cache dispatched per core");
            if(((Number)timing.get("input_bytes")).longValue()<=0||((Number)timing.get("output_bytes")).longValue()!=dispatches*64*(3+8*26)*4)throw new AssertionError("Incorrect transfer accounting");
            for(String stage:new String[]{"rows_ns","pack_ns","dispatch_ns","unpack_ns"})if(((Number)timing.get(stage)).longValue()<0)throw new AssertionError("Invalid stage duration");
            for(int gpuShare:new int[]{16,32,64}){
            java.util.concurrent.CountDownLatch cpuStarted=new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.atomic.AtomicInteger gpuCalls=new java.util.concurrent.atomic.AtomicInteger();
            BatchedSolver hybrid=new BatchedSolver(BoundedCrib::cpuRows,p->{
                gpuCalls.incrementAndGet();
                try{if(!cpuStarted.await(3,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("GPU wait starved CPU workers");}
                catch(InterruptedException e){Thread.currentThread().interrupt();throw new java.util.concurrent.CancellationException();}
                return cpuDispatch(p);
            },()->false).withCpuShare(gpuShare);
            Map<String,Object> mixed=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->{
                if(Thread.currentThread().getName().startsWith("enigmagrid-cpu-"))cpuStarted.countDown();return false;
            },hybrid,8);
            if(!Canonical.json(reference).equals(Canonical.json(mixed))||gpuCalls.get()!=1)throw new AssertionError("Hybrid receipt/partition parity");
            }
            java.util.concurrent.CountDownLatch gpuEntered=new java.util.concurrent.CountDownLatch(1),gpuRelease=new java.util.concurrent.CountDownLatch(1);
            java.util.concurrent.ExecutorService independent=java.util.concurrent.Executors.newFixedThreadPool(2);
            BatchedSolver gpuLane=new BatchedSolver(BoundedCrib::cpuRows,p->{
                gpuEntered.countDown();
                try{if(!gpuRelease.await(5,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("Independent CPU lane stalled");}
                catch(InterruptedException e){throw new java.util.concurrent.CancellationException();}
                return cpuDispatch(p);
            },()->false).withGpuOnly();
            try{
                java.util.concurrent.Future<Map<String,Object>> gpuJob=independent.submit(()->BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->false,gpuLane.newSearch(),8));
                if(!gpuEntered.await(2,java.util.concurrent.TimeUnit.SECONDS))throw new AssertionError("GPU lane not started");
                java.util.concurrent.Future<Map<String,Object>> cpuJob=independent.submit(()->BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->false,null,8));
                if(!Canonical.json(reference).equals(Canonical.json(cpuJob.get(3,java.util.concurrent.TimeUnit.SECONDS))))throw new AssertionError("Independent CPU receipt mismatch");
                gpuRelease.countDown();
                if(!Canonical.json(reference).equals(Canonical.json(gpuJob.get(3,java.util.concurrent.TimeUnit.SECONDS))))throw new AssertionError("Dedicated GPU receipt mismatch");
            }finally{gpuRelease.countDown();independent.shutdownNow();}
            BatchedSolver broken=new BatchedSolver(BoundedCrib::cpuRows,p->{throw new IllegalStateException("GPU unavailable");},()->false).withCpuShare();
            AdaptiveRows fallback=new AdaptiveRows(broken,()->100,()->false,new WorkControl.SystemTiming());
            Map<String,Object> recovered=BoundedCrib.search("QWERTZUIOPASDFGHJKLYXCVBNM","WETT",0,indices,2,100,8,8,cap,()->false,fallback,8);
            if(!fallback.failed()||!Canonical.json(reference).equals(Canonical.json(recovered)))throw new AssertionError("Hybrid GPU failure lost receipt parity");
        }
        int[][][] rows={BoundedCrib.cpuRows(BoundedCrib.coreAt(0),0,1)};
        int[][] edges={{0,0,rows[0][0][0]}};
        // Full solver dispatch shares the same live duty budget as row generation.
        class Clock implements WorkControl.Timing {
            long now,slept;public long nanos(){return now;}
            public void sleep(long ms){now+=ms*1000000;slept+=ms;}
        }
        Clock clock=new Clock();int[] duty={25};
        BatchedSolver paced=new BatchedSolver(BoundedCrib::cpuRows,p->{clock.now+=10000000;return cpuDispatch(p);},()->false);
        AdaptiveRows adaptive=new AdaptiveRows(paced,()->duty[0],()->false,clock);
        List<BoundedCrib.Key> one=Collections.singletonList(BoundedCrib.coreAt(0));
        adaptive.prepare(one,0,1);adaptive.solve(one.get(0),0,1,edges,13,32,8);
        duty[0]=100;adaptive.prepare(one,0,1);adaptive.solve(one.get(0),0,1,edges,13,32,8);
        if(clock.slept!=0||adaptive.dispatches()!=2)throw new AssertionError("Solver retained rest after 100% selected");
        duty[0]=25;adaptive.prepare(one,0,1);adaptive.solve(one.get(0),0,1,edges,13,32,8);
        if(clock.slept!=30)throw new AssertionError("Solver lower duty no longer enforced");
        int[] request=SolverKeyBatch.pack(Collections.singletonList(BoundedCrib.coreAt(0)),0,1,edges,13,5000,64);
        int[] response=SolverKeyBatch.execute(request,p->rows[0][0].clone(),SolverBatchChecks::cpuDispatch);
        if(SolverKeyBatch.unpack(response,request).get(0).nodes!=BoardSolver.solve(rows[0],edges,13,5000,64,()->false).nodes)throw new AssertionError("Combined solver parity");
        rejects(()->SolverKeyBatch.execute(Arrays.copyOf(request,request.length-1),p->rows[0][0].clone(),SolverBatchChecks::cpuDispatch));
        rejects(()->SolverKeyBatch.unpack(Arrays.copyOf(response,7),request));
        int[] badScope=response.clone();badScope[1]=2;rejects(()->SolverKeyBatch.unpack(badScope,request));
        rejects(()->SolverKeyBatch.unpack(Arrays.copyOf(response,response.length+1),request));
        int[] malformed=response.clone();malformed[8]=65;rejects(()->SolverKeyBatch.unpack(malformed,request));
        int[] negative=SolverKeyBatch.execute(request,p->rows[0][0].clone(),p->{int[] out=new int[3+p[4]*26];out[1]=1;return out;});
        if(negative.length!=9||!SolverKeyBatch.unpack(negative,request).get(0).partialBoards.isEmpty())throw new AssertionError("Negative core transferred unused rows");
        // Every positive answer still needs its rows and must satisfy all edges.
        if(response[8]>0){int[] missingRows=Arrays.copyOf(response,response.length-26);rejects(()->SolverKeyBatch.unpack(missingRows,request));}
        for(int cap:new int[]{1,8,64})for(int budget:new int[]{1,32,5000}){
            int[] input=SolverBatch.pack(rows,edges,13,budget,cap);
            BoardSolver.Result reference=BoardSolver.solve(rows[0],edges,13,budget,cap,()->false);
            int[] output=new int[3+cap*26];
            output[0]=reference.status.equals("satisfiable")?1:reference.status.equals("unsatisfiable")?0:2;
            output[1]=reference.nodes;output[2]=reference.partialBoards.size();
            for(int i=0;i<reference.partialBoards.size();i++)System.arraycopy(reference.partialBoards.get(i),0,output,3+i*26,26);
            BoardSolver.Result decoded=SolverBatch.unpack(output,input).get(0);
            int[] compact=new int[5+reference.partialBoards.size()*26];compact[0]=-1;compact[1]=1;
            System.arraycopy(output,0,compact,2,compact.length-2);
            BoardSolver.Result compactDecoded=SolverBatch.unpack(compact,input).get(0);
            if(!compactDecoded.status.equals(decoded.status)||compactDecoded.nodes!=decoded.nodes||compactDecoded.partialBoards.size()!=decoded.partialBoards.size())throw new AssertionError("Compact header parity");
            for(int i=0;i<decoded.partialBoards.size();i++)if(!Arrays.equals(decoded.partialBoards.get(i),compactDecoded.partialBoards.get(i)))throw new AssertionError("Compact ordered answer parity");
            rejects(()->SolverBatch.unpack(Arrays.copyOf(compact,compact.length-1),input));
            rejects(()->SolverBatch.unpack(Arrays.copyOf(compact,compact.length+1),input));
            int[] wrongCount=compact.clone();wrongCount[1]=2;rejects(()->SolverBatch.unpack(wrongCount,input));
            int[] wrongAnswers=compact.clone();wrongAnswers[4]=cap+1;rejects(()->SolverBatch.unpack(wrongAnswers,input));
            if(!decoded.status.equals(reference.status)||decoded.nodes!=reference.nodes)throw new AssertionError("Wire round trip");
            for(int i=0;i<decoded.partialBoards.size();i++)if(!Arrays.equals(decoded.partialBoards.get(i),reference.partialBoards.get(i)))throw new AssertionError("Ordered answers changed");
            rejects(()->SolverBatch.unpack(Arrays.copyOf(output,output.length-1),input));
            int[] invalid=output.clone();invalid[1]=budget+1;rejects(()->SolverBatch.unpack(invalid,input));
            if(output[2]>0){int[] badBoard=output.clone();badBoard[3]=26;rejects(()->SolverBatch.unpack(badBoard,input));}
        }
        rejects(()->SolverBatch.pack(rows,edges,14,5000,64));
        rejects(()->SolverBatch.pack(rows,new int[][]{{1,0,1}},13,5000,64));
        rows[0][0][0]=26;rejects(()->SolverBatch.pack(rows,edges,13,5000,64));
        System.out.println("PASS solver wire CPU round trip, ordered boards and malformed result rejection; physical GPU parity not tested here");
    }
}
