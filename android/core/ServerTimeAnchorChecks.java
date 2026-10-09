package org.enigmagrid.core;

public final class ServerTimeAnchorChecks {
    public static void main(String[] args){
        // A wildly incorrect device wall clock must not shift diagnostic buckets.
        long serverMs=1_800_000_000_000L,receivedNs=5_000_000_000L;
        ServerTimeAnchor anchor=new ServerTimeAnchor(serverMs,receivedNs);
        if(anchor.nowMs(receivedNs)!=serverMs||anchor.nowMs(receivedNs+5_500_000_000L)!=serverMs+5500)
            throw new AssertionError("Server clock did not advance monotonically");
        if(anchor.nowMs(receivedNs-1_000_000L)!=serverMs)
            throw new AssertionError("Negative elapsed time shifted diagnostic clock");
        System.out.println("PASS server-anchored monotonic diagnostic timestamps");
    }
}
