package org.enigmagrid.core;

import java.util.Map;
import java.util.Objects;

/** Single-owner outbox session. Every write remains synchronous and durable.
 * Reopen a session after restart or before another batch to read persisted state.
 */
public final class ReceiptStorageSession implements ReceiptQueue.Storage {
    private final ReceiptQueue.Storage storage;
    private Map<String,Object> saved;
    private boolean loaded;
    public ReceiptStorageSession(ReceiptQueue.Storage storage){this.storage=Objects.requireNonNull(storage);}
    public synchronized Map<String,Object> load() throws Exception {
        if(!loaded){saved=storage.load();loaded=true;}
        return saved;
    }
    public synchronized void save(Map<String,Object> value) throws Exception {
        storage.save(value);
        // Failed persistence must leave the previous state visible for retry.
        saved=value;loaded=true;
    }
}
