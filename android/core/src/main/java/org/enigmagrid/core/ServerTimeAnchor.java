package org.enigmagrid.core;

/** Monotonic clock anchored to a coordinator timestamp for disposable diagnostics. */
public final class ServerTimeAnchor {
    private final long serverMs,receivedNs;

    public ServerTimeAnchor(long serverMs,long receivedNs){
        this.serverMs=serverMs;this.receivedNs=receivedNs;
    }
    public long nowMs(long currentNs){
        long elapsedNs=currentNs-receivedNs;
        return serverMs+Math.max(0,elapsedNs)/1_000_000L;
    }
}
