package org.enigmagrid.core;
import java.util.*;
/** Bounded GPU transport batch; individual search scopes and receipts stay unchanged. */
public final class RowBatch {
 public static final int MAX_KEYS=512,MAX_ROWS=MAX_KEYS*72,MAX_INPUT=625+MAX_ROWS*9;
 private RowBatch(){}
 public static int[] pack(List<BoundedCrib.Key> keys,int offset,int length){
  if(keys==null||keys.isEmpty()||keys.size()>MAX_KEYS||offset<0||length<1||offset+length>72)throw new IllegalArgumentException("Batch scope");
  int[] packed=new int[625+keys.size()*length*9];int index=0;EnigmaM4.copyRowTables(packed);
  for(BoundedCrib.Key key:keys){
   if(key==null)throw new IllegalArgumentException("Null key");
   EnigmaM4.writeRowInputs(packed,625+index*length*9,key.reflector,key.greek,key.moving,key.positions,key.rings,offset,length);index++;
  }
  packed[0]=keys.size()*length;return packed;
 }
 public static int[][][] unpack(int[] flat,int keys,int length){
  if(keys<1||keys>MAX_KEYS||length<1||length>72||flat==null||flat.length!=keys*length*26)throw new IllegalArgumentException("Batch result size");
  int[][][] result=new int[keys][length][26];
  for(int k=0;k<keys;k++)for(int r=0;r<length;r++){
   int[] row=result[k][r];System.arraycopy(flat,(k*length+r)*26,row,0,26);
   for(int x=0;x<26;x++)if(row[x]<0||row[x]>=26||row[x]==x||row[row[x]]!=x)throw new IllegalArgumentException("Batch permutation");
  }
  return result;
 }
}
