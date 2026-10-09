package org.enigmagrid.core;

import java.util.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import static org.enigmagrid.core.Canonical.*;

/** Clean bounded_crib_v1 receipt engine; no network or implicit search domain. */
public final class BoundedCrib {
    // One process-wide CPU executor enforces the hardware-sized aggregate cap.
    // Each search submits at most its requested number of stripe tasks.
    private static final int CPU_CAPACITY=Math.max(1,Math.min(32,Runtime.getRuntime().availableProcessors()));
    private static final ThreadPoolExecutor CPU_POOL=new ThreadPoolExecutor(
        CPU_CAPACITY,CPU_CAPACITY,0L,TimeUnit.MILLISECONDS,new ArrayBlockingQueue<>(128),r->{
            Thread t=new Thread(r,"enigmagrid-cpu-"+CPU_CAPACITY);t.setDaemon(true);return t;
        },new ThreadPoolExecutor.AbortPolicy());
    private static final ExecutorService GPU_POOL=Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"enigmagrid-gpu-dispatch");t.setDaemon(true);return t;});
    public interface RowProvider {
        /** Stateful backends override this to give each concurrent search its own cache. */
        default RowProvider newSearch(){return this;}
        int[][] rows(Key key,int offset,int length);
        default void prepare(List<Key> keys,int offset,int length){}
        /** Optional full bounded solver; null retains the reference CPU path. */
        default BoardSolver.Result solve(Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards){return null;}
        default boolean hybrid(){return false;}
        default boolean accelerates(Key key){return true;}
    }
    public static final long DOMAIN=1344L*308915776L;
    private static final String[] ROTORS={"I","II","III","IV","V","VI","VII","VIII"};
    private static final List<String[]> ORDERS=new ArrayList<>();
    static {for(String a:ROTORS)for(String b:ROTORS)for(String c:ROTORS)if(!a.equals(b)&&!a.equals(c)&&!b.equals(c))ORDERS.add(new String[]{a,b,c});}
    public static final class Key {
        public final String reflector,greek,rings,positions;
        public final String[] moving;
        private Key(String reflector,String greek,String[] moving,String rings,String positions){this.reflector=reflector;this.greek=greek;this.moving=moving.clone();this.rings=rings;this.positions=positions;}
        Map<String,Object> value(List<String> plugs){return object("reflector",reflector,"greek",greek,"moving_rotors",Arrays.asList(moving),"rings",rings,"positions",positions,"plugboard",plugs);}
        String crypt(String text,List<String> plugs){return EnigmaM4.crypt(text,reflector,greek,moving,positions,rings,plugs.toArray(new String[0]));}
    }
    public static int[][] cpuRows(Key key,int offset,int length) {
        return EnigmaM4.rows(key.reflector,key.greek,key.moving,key.positions,key.rings,offset,length);
    }
    public static Key coreAt(long index) {
        if(index<0 || index>=DOMAIN)throw new IllegalArgumentException("Core index");
        char[] v=new char[6];for(int j=0;j<6;j++){v[j]=(char)('A'+index%26);index/=26;}
        String[] order=ORDERS.get((int)(index%336));index/=336;
        return new Key(index/2==0?"Bthin":"Cthin",index%2==0?"Beta":"Gamma",order,"AA"+v[4]+v[5],new String(v,0,4));
    }
    /** Canonical ordering shared with transport cohorts; each search stays <=128 cores. */
    static List<Key> canonicalKeys(long[] indices){
        if(indices==null||indices.length<1||indices.length>128)throw new IllegalArgumentException("Invalid scope");
        TreeMap<String,Key> cores=new TreeMap<>();Set<Long> seen=new HashSet<>();
        for(long index:indices){if(!seen.add(index))throw new IllegalArgumentException("Duplicate core");Key k=coreAt(index);cores.put(digest(k.value(Collections.emptyList())),k);}
        return new ArrayList<>(cores.values());
    }
    private static void check(BooleanSupplier cancel){if(Thread.currentThread().isInterrupted()||(cancel!=null&&cancel.getAsBoolean()))throw new CancellationException();}
    private static Future<?> submitCpuStripe(Runnable work,BooleanSupplier cancel){
        if(Thread.currentThread().getName().startsWith("enigmagrid-cpu-"))
            throw new RejectedExecutionException("Nested CPU search");
        FutureTask<Void> task=new FutureTask<>(work,null);
        for(;;){
            check(cancel);
            try{CPU_POOL.execute(task);return task;}
            catch(RejectedExecutionException full){
                if(CPU_POOL.isShutdown())throw full;
                // At most 128 tasks may wait; thermal/user stop must not be
                // stuck in a queue insertion that never checks cancellation.
                try{Thread.sleep(20);}catch(InterruptedException stopped){
                    Thread.currentThread().interrupt();throw new CancellationException();
                }
            }
        }
    }
    private static final class Completions {
        final List<int[]> boards=new ArrayList<>();boolean truncated;
        final int pairs,limit;final BooleanSupplier cancel;
        Completions(int pairs,int limit,BooleanSupplier cancel){this.pairs=pairs;this.limit=limit;this.cancel=cancel;}
        void visit(int[] p) {
            check(cancel);if(truncated)return;
            int used=0;List<Integer> free=new ArrayList<>();
            for(int i=0;i<26;i++){if(i<p[i])used++;if(p[i]==-1)free.add(i);}
            if(used>pairs || used+free.size()/2<pairs)return;
            if(free.isEmpty()){if(used==pairs){if(boards.size()>=limit)truncated=true;else boards.add(p.clone());}return;}
            int a=free.get(0);int[] q=p.clone();q[a]=a;visit(q);
            if(used<pairs)for(int j=1;j<free.size();j++){int b=free.get(j);q=p.clone();q[a]=b;q[b]=a;visit(q);if(truncated)break;}
        }
    }
    private static List<String> plugs(int[] board) {
        List<String> result=new ArrayList<>();for(int i=0;i<26;i++)if(i<board[i])result.add(""+(char)('A'+i)+(char)('A'+board[i]));return result;
    }
    private static void text(String s){if(s==null||s.length()<1||s.length()>72||!s.matches("[A-Z]+"))throw new IllegalArgumentException("Invalid text");}
    public static Map<String,Object> search(String cipher,String crib,int offset,long[] indices,int pairs,int nodeLimit,int boardLimit,int completionLimit,int candidateLimit,BooleanSupplier cancel) {
        return search(cipher,crib,offset,indices,pairs,nodeLimit,boardLimit,completionLimit,candidateLimit,cancel,null);
    }
    public static Map<String,Object> search(String cipher,String crib,int offset,long[] indices,int pairs,int nodeLimit,int boardLimit,int completionLimit,int candidateLimit,BooleanSupplier cancel,RowProvider provider) {
        return search(cipher,crib,offset,indices,pairs,nodeLimit,boardLimit,completionLimit,candidateLimit,cancel,provider,1);
    }
    /** Parallel preparation with canonical-order reduction. Providers are serialized. */
    public static Map<String,Object> search(String cipher,String crib,int offset,long[] indices,int pairs,int nodeLimit,int boardLimit,int completionLimit,int candidateLimit,BooleanSupplier cancel,RowProvider provider,int workers) {
        if(workers<1||workers>32)throw new IllegalArgumentException("Worker count");
        text(cipher);text(crib);
        if(offset<0||offset+crib.length()>cipher.length()||pairs<0||pairs>13||indices==null||indices.length<1||indices.length>128)throw new IllegalArgumentException("Invalid scope");
        if(nodeLimit<1||nodeLimit>5000||boardLimit<1||boardLimit>64||completionLimit<1||completionLimit>256||candidateLimit<1||candidateLimit>2048)throw new IllegalArgumentException("Invalid budget");
        TreeMap<String,Key> cores=new TreeMap<>();
        for(Key k:canonicalKeys(indices))cores.put(digest(k.value(Collections.emptyList())),k);
        List<Object> coreValues=new ArrayList<>();for(Key k:cores.values())coreValues.add(k.value(Collections.emptyList()));
        Map<String,Object> scope=object("engine","bounded_crib_v1","ciphertext",cipher,"crib",crib,"offset",offset,"model","clean","index",null,"pairs",pairs,"cores",coreValues);
        int[][] edges=new int[crib.length()][3];boolean conflict=false;
        for(int j=0;j<crib.length();j++){edges[j]=new int[]{j,crib.charAt(j)-65,cipher.charAt(offset+j)-65};conflict|=edges[j][1]==edges[j][2];}
        List<Object> candidates=new ArrayList<>();int unknown=0,nodes=0,visited=0;
        check(cancel);
        if(!conflict&&provider!=null){synchronized(provider){provider.prepare(new ArrayList<>(cores.values()),offset,crib.length());}}
        boolean parallel=!conflict&&workers>1&&cores.size()>1;
        List<Future<BoardSolver.Result>> prepared=new ArrayList<>();
        List<Future<?>> cpuStripes=new ArrayList<>();
        try {
        if(parallel){
            // GPU calls remain serialized. CPU work for each search occupies no
            // more than `workers` stripes, while independent jobs may fill the
            // same hardware-sized pool instead of sharing an undersized pool.
            List<Key> keys=new ArrayList<>(cores.values());
            List<RowProvider> selectedProviders=new ArrayList<>(keys.size());
            List<Integer> cpuIndices=new ArrayList<>();
            boolean hybrid=provider!=null&&provider.hybrid();
            for(int i=0;i<keys.size();i++){
                Key key=keys.get(i);
                RowProvider selected=hybrid&&!provider.accelerates(key)?null:provider;
                selectedProviders.add(selected);
                if(hybrid&&selected!=null){
                    prepared.add(GPU_POOL.submit(()->solveCore(key,offset,crib.length(),edges,pairs,nodeLimit,boardLimit,cancel,selected)));
                }else{
                    prepared.add(new CompletableFuture<BoardSolver.Result>());
                    cpuIndices.add(i);
                }
            }
            int stripes=Math.min(workers,cpuIndices.size());
            for(int slot=0;slot<stripes;slot++){
                final int stripe=slot;
                cpuStripes.add(submitCpuStripe(()->{
                    Throwable failure=null;
                    for(int at=stripe;at<cpuIndices.size();at+=stripes){
                        int index=cpuIndices.get(at);
                        @SuppressWarnings("unchecked") CompletableFuture<BoardSolver.Result> result=(CompletableFuture<BoardSolver.Result>)prepared.get(index);
                        if(failure!=null){result.completeExceptionally(failure);continue;}
                        try{result.complete(solveCore(keys.get(index),offset,crib.length(),edges,pairs,nodeLimit,boardLimit,cancel,selectedProviders.get(index)));}
                        catch(Throwable error){failure=error;result.completeExceptionally(error);}
                    }
                },cancel));
            }
        }
        if(!conflict)for(Key k:cores.values()) {
            check(cancel);visited++;
            BoardSolver.Result solved;
            if(!parallel)solved=solveCore(k,offset,crib.length(),edges,pairs,nodeLimit,boardLimit,cancel,provider!=null&&provider.hybrid()&&!provider.accelerates(k)?null:provider);
            else try{solved=prepared.get(visited-1).get();}
            catch(InterruptedException e){Thread.currentThread().interrupt();throw new CancellationException();}
            catch(ExecutionException e){Throwable cause=e.getCause();if(cause instanceof RuntimeException)throw (RuntimeException)cause;if(cause instanceof Error)throw (Error)cause;throw new IllegalStateException(cause);}
            nodes+=solved.nodes;boolean uncertain=solved.status.equals("unknown_budget");
            for(int[] partial:solved.partialBoards) {
                Completions complete=new Completions(pairs,completionLimit,cancel);complete.visit(partial);uncertain|=complete.truncated;
                for(int[] board:complete.boards) {
                    List<String> plugs=plugs(board);String plain=k.crypt(cipher,plugs);
                    if(!plain.substring(offset,offset+crib.length()).equals(crib))throw new IllegalStateException("Constraint/replay disagreement");
                    if(candidates.size()>=candidateLimit){uncertain=true;break;}
                    candidates.add(object("key",k.value(plugs),"plaintext",plain,"unknown_slots",Collections.emptyList()));
                }
                if(candidates.size()>=candidateLimit){uncertain=true;break;}
            }
            if(uncertain)unknown++;
            if(candidates.size()>=candidateLimit)break;
        }
        } finally {
            for(Future<?> task:cpuStripes)if(!task.isDone())task.cancel(true);
            for(Future<?> task:cpuStripes)if(task.isCancelled())CPU_POOL.remove((Runnable)task);
            for(Future<?> task:prepared)if(!task.isDone())task.cancel(true);
        }
        check(cancel);
        boolean complete=unknown==0&&(conflict||visited==cores.size());
        return object("engine","bounded_crib_v1","scope_hash",digest(scope),"cipher_sha256",sha256(cipher),"status",complete?(candidates.isEmpty()?"complete_negative":"complete_candidates"):"unknown_budget","complete",complete,"historical_solution",false,"core_count",cores.size(),"visited_cores",visited,"nodes",nodes,"candidates",candidates,"budgets",object("nodes_per_core",nodeLimit,"boards_per_core",boardLimit,"completions_per_board",completionLimit,"candidates",candidateLimit),"model","clean","index",null,"crib",crib,"offset",offset,"pairs",pairs);
    }
    private static BoardSolver.Result solveCore(Key key,int offset,int length,int[][] edges,int pairs,int nodes,int boards,BooleanSupplier cancel,RowProvider provider){
        check(cancel);int[][] rows;
        if(provider!=null)synchronized(provider){
            check(cancel);
            BoardSolver.Result accelerated=provider.solve(key,offset,length,edges,pairs,nodes,boards);
            check(cancel);
            if(accelerated!=null){
                if(accelerated.status.equals("cancelled"))throw new CancellationException();
                return accelerated;
            }
        }
        if(provider==null)rows=cpuRows(key,offset,length);
        else synchronized(provider){check(cancel);rows=provider.rows(key,offset,length);}
        if(rows==null||rows.length!=length)throw new IllegalStateException("Invalid row backend output");
        BoardSolver.Result result=BoardSolver.solve(rows,edges,pairs,nodes,boards,cancel);
        if(result.status.equals("cancelled"))throw new CancellationException();
        return result;
    }

}
