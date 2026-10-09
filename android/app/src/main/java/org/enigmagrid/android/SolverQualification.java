package org.enigmagrid.android;
import java.util.*;
import org.enigmagrid.core.*;

/** Independent numerical/performance qualification and local concurrency selection. */
final class SolverQualification {
    static String key(){return "bounded-solver-hybrid-v4:"+GpuProcess.qualificationKey();}
    static final class Report {
        final String text;final boolean faster;final int jobs;final boolean concurrencyQualified;
        Report(String text,boolean faster,int jobs,boolean concurrencyQualified){this.text=text;this.faster=faster;this.jobs=jobs;this.concurrencyQualified=concurrencyQualified;}
    }
    static Report run(GpuProcess gpu,java.util.function.Supplier<String> restriction)throws Exception {
        int compared=0;long cpuNanos=0,gpuNanos=0,coldNanos=0,parallelNanos=0;
        int workers=Math.max(1,Math.min(8,Runtime.getRuntime().availableProcessors()));
        java.util.concurrent.ExecutorService pool=java.util.concurrent.Executors.newFixedThreadPool(workers);
        StringBuilder detail=new StringBuilder();
        try{
        for(int cores:new int[]{1,8,64})for(int length:new int[]{1,5,22,23,24})for(int budget:new int[]{1,32,5000}){
            if(Thread.currentThread().isInterrupted())throw new java.util.concurrent.CancellationException();
            String blocked=restriction.get();
            if(blocked!=null)throw new QualificationProtection(blocked);
            int[][][] rows=new int[cores][][];int[][] edges=new int[length][3];
            for(int c=0;c<cores;c++)rows[c]=BoundedCrib.cpuRows(BoundedCrib.coreAt(c*100003L),0,length);
            for(int e=0;e<length;e++)edges[e]=new int[]{e,e%26,(e*7+1)%26};
            int[] input=SolverBatch.pack(rows,edges,10,budget,8);
            long start=System.nanoTime();
            if(compared==0){SolverBatch.unpack(gpu.solve(input),input);coldNanos=System.nanoTime()-start;start=System.nanoTime();}
            List<BoardSolver.Result> actual=SolverBatch.unpack(gpu.solve(input),input);long elapsedGpu=System.nanoTime()-start;gpuNanos+=elapsedGpu;
            start=System.nanoTime();
            for(int c=0;c<cores;c++){
                BoardSolver.Result expected=BoardSolver.solve(rows[c],edges,10,budget,8,()->Thread.currentThread().isInterrupted());
                BoardSolver.Result got=actual.get(c);
                if(!expected.status.equals(got.status)||expected.nodes!=got.nodes||expected.partialBoards.size()!=got.partialBoards.size())throw new IllegalStateException("GPU solver status/node/count mismatch at "+cores+"/"+length+"/"+budget+"/"+c);
                for(int n=0;n<expected.partialBoards.size();n++)if(!Arrays.equals(expected.partialBoards.get(n),got.partialBoards.get(n)))throw new IllegalStateException("GPU solver ordered board mismatch");
                compared++;
            }
            long elapsedCpu=System.nanoTime()-start;cpuNanos+=elapsedCpu;
            start=System.nanoTime();
            List<java.util.concurrent.Future<BoardSolver.Result>> futures=new ArrayList<>();
            for(int c=0;c<cores;c++){final int index=c;futures.add(pool.submit(()->BoardSolver.solve(rows[index],edges,10,budget,8,()->Thread.currentThread().isInterrupted())));}
            for(int c=0;c<cores;c++){
                BoardSolver.Result parallel=futures.get(c).get(),got=actual.get(c);
                if(!parallel.status.equals(got.status)||parallel.nodes!=got.nodes||parallel.partialBoards.size()!=got.partialBoards.size())throw new IllegalStateException("Parallel CPU parity mismatch");
                for(int n=0;n<parallel.partialBoards.size();n++)if(!Arrays.equals(parallel.partialBoards.get(n),got.partialBoards.get(n)))throw new IllegalStateException("Parallel CPU ordered board mismatch");
            }
            long elapsedParallel=System.nanoTime()-start;parallelNanos+=elapsedParallel;
            detail.append("\n").append(cores).append(" cores / ").append(length).append(" edges / ").append(budget).append(" nodes: GPU ").append(elapsedGpu/1_000_000).append(" ms, CPU ").append(elapsedCpu/1_000_000).append(" ms, parallel CPU ").append(elapsedParallel/1_000_000).append(" ms");
        }
        // Exercise the actual receipt engine, not just isolated BoardSolver outputs.
        // Includes rows, bounded solving, completions, candidate replay and canonical reduction.
        java.util.function.BooleanSupplier cancelled=()->{
            if(Thread.currentThread().isInterrupted())return true;
            String blocked=restriction.get();
            if(blocked!=null)throw new QualificationProtection(blocked);
            return false;
        };
        long receiptGpu=0,receiptCpu=0;int receipts=0,wins=0;
        long[] indices=new long[128];for(int i=0;i<indices.length;i++)indices[i]=i*7919L;
        String cipher="QWERTZUIOPASDFGHJKLYXCVBNM";
        // Same dimensions and bounded budgets as constrained_program_v1; this
        // fixture is NOT a campaign result and is never submitted for credit.
        String crib="ABCDEFGHIJKLMNOPQRSTUVWXYZ".substring(0,24);
        char[] letters=crib.toCharArray();
        for(int i=0;i<letters.length;i++)if(letters[i]==cipher.charAt(i))letters[i]=(char)('A'+(letters[i]-'A'+1)%26);
        crib=new String(letters);
        for(int length:new int[]{22,23,24})for(int trial=0;trial<6;trial++){
            int candidateCap=trial%3==0?1:trial%3==1?16:32;
            BatchedSolver backend=new BatchedSolver(new BatchedRows(gpu::rows,cancelled),gpu::solve,cancelled).withKeyDispatch(gpu::solveKeys).withCpuShare();
            Map<String,Object> actual=null,expected=null;long gpuElapsed=0,cpuElapsed=0;
            // Alternate execution order to reduce systematic warmup bias.
            for(int pass=0;pass<2;pass++){
                boolean useGpu=(trial+pass)%2==0;long start=System.nanoTime();
                Map<String,Object> result=BoundedCrib.search(cipher,crib.substring(0,length),0,indices,10,5000,64,256,candidateCap,cancelled,useGpu?backend:null,workers);
                long elapsed=System.nanoTime()-start;
                if(useGpu){actual=result;gpuElapsed=elapsed;}else{expected=result;cpuElapsed=elapsed;}
            }
            if(!Canonical.json(expected).equals(Canonical.json(actual)))throw new IllegalStateException("Full GPU receipt mismatch at candidate cap "+candidateCap);
            // First pair is warmup; correctness is still checked.
            if(trial>0){receiptGpu+=gpuElapsed;receiptCpu+=cpuElapsed;if(gpuElapsed<cpuElapsed)wins++;}
            detail.append("\nFull 128-core trial ").append(trial).append(" / ").append(length).append(" letters: GPU ").append(gpuElapsed/1_000_000).append(" ms, CPU ").append(cpuElapsed/1_000_000).append(" ms");
            detail.append("\nGPU stages: ").append(Canonical.json(backend.timings()));
            receipts++;
        }
        boolean faster=wins>=12&&receiptGpu<receiptCpu*0.95;
        ConcurrencyQualification.Report concurrency;
        boolean concurrencyQualified=true;
        try{concurrency=ConcurrencyQualification.run(gpu,faster,restriction);}
        catch(Exception e){
            if(!QualificationProtection.interrupted(e))throw e;
            concurrencyQualified=false;
            concurrency=new ConcurrencyQualification.Report(1,"\nConcurrency check interrupted by device protection; no concurrency result recorded. The completed solver parity/performance result remains valid. "+e.getMessage());
        }
        return new Report("Solver parity: "+compared+" cores; warm GPU+IPC "+gpuNanos/1_000_000+" ms, sequential CPU "+cpuNanos/1_000_000+" ms, "+workers+"-worker CPU "+parallelNanos/1_000_000+" ms; cold start "+coldNanos/1_000_000+" ms. Full receipt parity: "+receipts+"; GPU pipeline "+receiptGpu/1_000_000+" ms, CPU pipeline "+receiptCpu/1_000_000+" ms. "+(faster?"GPU solver qualified for 128-core / 22-24-letter jobs.":"CPU remains faster; GPU solver not enabled.")+detail+concurrency.text,faster,concurrency.jobs,concurrencyQualified);
        }finally{pool.shutdownNow();}
    }
}
