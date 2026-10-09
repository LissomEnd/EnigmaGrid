package org.enigmagrid.android;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Host-only gate regression: different sessions serialize, cancellation exits. */
public final class GpuRpcGateChecks {
    private static void check(boolean condition) { if (!condition) throw new AssertionError(); }

    public static void main(String[] args) throws Exception {
        AtomicInteger active = new AtomicInteger(), peak = new AtomicInteger();
        CountDownLatch firstEntered = new CountDownLatch(1), finishFirst = new CountDownLatch(1);
        Thread first = new Thread(() -> {
            try (GpuRpcGate.Permit ignored = GpuRpcGate.acquire()) {
                peak.accumulateAndGet(active.incrementAndGet(), Math::max);
                firstEntered.countDown();
                if (!finishFirst.await(2, TimeUnit.SECONDS)) throw new AssertionError("first gate wait");
                active.decrementAndGet();
            } catch (InterruptedException e) { throw new AssertionError(e); }
        });
        first.start();check(firstEntered.await(1, TimeUnit.SECONDS));
        AtomicInteger canceled = new AtomicInteger();
        Thread waiter = new Thread(() -> {
            try (GpuRpcGate.Permit ignored = GpuRpcGate.acquire()) {
                throw new AssertionError("canceled waiter entered RPC");
            } catch (InterruptedException expected) { canceled.incrementAndGet(); }
        });
        waiter.start();Thread.sleep(30);waiter.interrupt();waiter.join(1000);
        check(!waiter.isAlive() && canceled.get() == 1);
        Thread second = new Thread(() -> {
            try (GpuRpcGate.Permit ignored = GpuRpcGate.acquire()) {
                peak.accumulateAndGet(active.incrementAndGet(), Math::max);
                active.decrementAndGet();
            } catch (InterruptedException e) { throw new AssertionError(e); }
        });
        second.start();Thread.sleep(30);check(active.get() == 1);
        finishFirst.countDown();first.join(1000);second.join(1000);
        check(!first.isAlive() && !second.isAlive() && peak.get() == 1 && active.get() == 0);
        long heldAt=System.nanoTime();
        try(GpuRpcGate.Permit timedOut=GpuRpcGate.acquire()) {
            timedOut.holdUntilServiceDeadline(heldAt-TimeUnit.MILLISECONDS.toNanos(8500));
        }
        try(GpuRpcGate.Permit ignored=GpuRpcGate.acquire()) {
            long delayMs=TimeUnit.NANOSECONDS.toMillis(System.nanoTime()-heldAt);
            check(delayMs>=350 && delayMs<2000);
        }
        System.out.println("PASS: process-wide GPU RPC serialization, canceled waiter and deferred release");
    }
}
