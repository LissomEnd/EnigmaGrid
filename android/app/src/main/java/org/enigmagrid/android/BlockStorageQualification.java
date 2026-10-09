package org.enigmagrid.android;

import android.content.Context;
import java.util.*;
import java.util.function.BooleanSupplier;
import org.enigmagrid.core.*;
import static org.enigmagrid.core.Canonical.object;

/** Dedicated qualification namespace: never opens the live credential/outbox files. */
final class BlockStorageQualification {
    static void run(Context context,BooleanSupplier cancel)throws Exception{
        if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();
        CredentialStore test=new CredentialStore(context,true);
        List<Object> pending=new ArrayList<>();
        pending.add(object("block_id","storage-check","unit",0,"compute_seconds",.125,"result",object("data","x".repeat(98304))));
        Map<String,Object> state=object("version",1,"server","qualification","owner","qualification","blocks",new ArrayList<>(),"pending",pending);
        test.workBlocks().save(state);
        ReceiptQueue.Storage store=test.workBlockStorage();
        if(!JsonCodec.object(WorkBlockJson.json(state)).equals(store.load()))throw new IllegalStateException("Legacy block storage mismatch");
        store.save(state);
        if(cancel.getAsBoolean())throw new java.util.concurrent.CancellationException();
        pending.add(object("block_id","storage-check","unit",1,"compute_seconds",.25,"result",object("data","y".repeat(98304))));
        store.save(state);
        Map<String,Object> reopened=new CredentialStore(context,true).workBlockStorage().load();
        if(!JsonCodec.object(WorkBlockJson.json(state)).equals(reopened))throw new IllegalStateException("Chunked encrypted restart mismatch");
        pending.remove(0);store.save(state);
        if(!JsonCodec.object(WorkBlockJson.json(state)).equals(new CredentialStore(context,true).workBlockStorage().load()))throw new IllegalStateException("Chunked encrypted acknowledgement mismatch");
    }
}
