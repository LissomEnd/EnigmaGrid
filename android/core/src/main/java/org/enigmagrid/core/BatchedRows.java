package org.enigmagrid.core;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.concurrent.CancellationException;
/** Lazy, search-local batches. Called through the serialized adaptive backend. */
public final class BatchedRows implements BoundedCrib.RowProvider {
 public interface Dispatch{int[] run(int[] packed);}
 private final Dispatch dispatch;private final BooleanSupplier cancel;
 private List<BoundedCrib.Key> keys=Collections.emptyList();
 private final Map<BoundedCrib.Key,int[][]> cache=new IdentityHashMap<>();
 private int offset,length;
 private long dispatches;
 public long dispatches(){return dispatches;}
 private int[] run(int[] packed){int[] result=dispatch.run(packed);dispatches++;return result;}
 public BatchedRows(Dispatch dispatch,BooleanSupplier cancel){this.dispatch=dispatch;this.cancel=cancel;}
 public void prepare(List<BoundedCrib.Key> keys,int offset,int length){
  if(keys==null||keys.size()>128)throw new IllegalArgumentException("Search batch scope");
  this.keys=new ArrayList<>(keys);this.offset=offset;this.length=length;cache.clear();
 }
 public boolean cached(BoundedCrib.Key key,int offset,int length){return this.offset==offset&&this.length==length&&cache.containsKey(key);}
 private void check(){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
 public int[][] rows(BoundedCrib.Key key,int offset,int length){
  check();if(offset!=this.offset||length!=this.length||!keys.contains(key))return RowBatch.unpack(run(RowBatch.pack(Collections.singletonList(key),offset,length)),1,length)[0];
  int[][] ready=cache.get(key);if(ready!=null)return ready;
  int first=(keys.indexOf(key)/RowBatch.MAX_KEYS)*RowBatch.MAX_KEYS;
  List<BoundedCrib.Key> batch=keys.subList(first,Math.min(keys.size(),first+RowBatch.MAX_KEYS));
  int[][][] result=RowBatch.unpack(run(RowBatch.pack(batch,offset,length)),batch.size(),length);check();
  for(int i=0;i<batch.size();i++)cache.put(batch.get(i),result[i]);
  return cache.get(key);
 }
}
