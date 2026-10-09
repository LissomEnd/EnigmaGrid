package org.enigmagrid.core;
import java.util.*;
import java.util.function.BooleanSupplier;
import java.util.concurrent.CancellationException;
/** Lazy, search-local batches. Called through the serialized adaptive backend. */
public final class BatchedRows implements BoundedCrib.RowProvider {
 public interface Dispatch{int[] run(int[] packed);}
 private final Dispatch dispatch;private final BooleanSupplier cancel;private final int batchKeys;
 private List<BoundedCrib.Key> keys=Collections.emptyList();
 private final Map<BoundedCrib.Key,int[][]> cache=new IdentityHashMap<>();
 private int offset,length;
 private long dispatches;
 public long dispatches(){return dispatches;}
 private int[] run(int[] packed){int[] result=dispatch.run(packed);dispatches++;return result;}
 public BatchedRows(Dispatch dispatch,BooleanSupplier cancel){this(dispatch,cancel,64);}
 public BatchedRows(Dispatch dispatch,BooleanSupplier cancel,int batchKeys){
  if(batchKeys!=64&&batchKeys!=128)throw new IllegalArgumentException("Only independently testable GPU row widths are allowed");
  this.dispatch=dispatch;this.cancel=cancel;this.batchKeys=batchKeys;
 }
 public BoundedCrib.RowProvider newSearch(){return new BatchedRows(dispatch,cancel,batchKeys);}
 public void prepare(List<BoundedCrib.Key> keys,int offset,int length){
  if(keys==null||keys.size()>128)throw new IllegalArgumentException("Search batch scope");
  this.keys=new ArrayList<>(keys);this.offset=offset;this.length=length;cache.clear();
 }
 public boolean cached(BoundedCrib.Key key,int offset,int length){return this.offset==offset&&this.length==length&&cache.containsKey(key);}
 private void check(){if(Thread.currentThread().isInterrupted()||cancel.getAsBoolean())throw new CancellationException();}
 public int[][] rows(BoundedCrib.Key key,int offset,int length){
  check();if(offset!=this.offset||length!=this.length||!keys.contains(key))return RowBatch.unpack(run(RowBatch.pack(Collections.singletonList(key),offset,length)),1,length)[0];
  int[][] ready=cache.get(key);if(ready!=null)return ready;
  // Preserve the qualified row-only dispatch size; larger solver batches opt in separately.
  int first=(keys.indexOf(key)/batchKeys)*batchKeys;
  List<BoundedCrib.Key> batch=keys.subList(first,Math.min(keys.size(),first+batchKeys));
  int[][][] result=RowBatch.unpack(run(RowBatch.pack(batch,offset,length)),batch.size(),length);check();
  for(int i=0;i<batch.size();i++)cache.put(batch.get(i),result[i]);
  return cache.get(key);
 }
}
