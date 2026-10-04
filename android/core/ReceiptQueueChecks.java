import java.util.*;
import org.enigmagrid.core.ReceiptQueue;
import static org.enigmagrid.core.Canonical.object;
public class ReceiptQueueChecks {
 static class Disk implements ReceiptQueue.Storage {
  Map<String,Object> value;boolean fail;
  public Map<String,Object> load(){return value;}
  public void save(Map<String,Object> v)throws Exception{if(fail)throw new java.io.IOException();value=v;}
 }
 public static void main(String[] args)throws Exception {
  Disk disk=new Disk();ReceiptQueue q=new ReceiptQueue(disk,"server","owner");
  for(int i=0;i<8;i++)q.append(object("lease_id","id"+i,"result",i));
  q.append(object("lease_id","id0","result",0));
  if(q.pending().size()!=8)throw new AssertionError();
  try{q.append(object("lease_id","overflow"));throw new AssertionError();}catch(IllegalStateException expected){}
  try{q.append(object("lease_id","id0","result",9));throw new AssertionError();}catch(IllegalStateException expected){}
  disk.fail=true;
  try{q.acknowledge("id0");throw new AssertionError();}catch(java.io.IOException expected){}
  q=new ReceiptQueue(disk,"server","owner");
  if(q.pending().size()!=8)throw new AssertionError("failed save lost receipt");
  disk.fail=false;q.acknowledge("id3");q.acknowledge("id3");
  if(q.pending().size()!=7)throw new AssertionError();
  try{new ReceiptQueue(disk,"server","other").pending();throw new AssertionError();}catch(IllegalStateException expected){}
  try{new ReceiptQueue(disk,"other","owner").pending();throw new AssertionError();}catch(IllegalStateException expected){}
  System.out.println("PASS: bounded queue, replay, conflict, failed persistence, restart, selective acknowledgment, account isolation");
 }
}
