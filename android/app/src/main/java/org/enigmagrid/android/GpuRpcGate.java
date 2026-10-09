package org.enigmagrid.android;

import java.util.concurrent.Semaphore;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** One interruptible admission point for every in-process GPU service request. */
final class GpuRpcGate {
    private static final Semaphore PERMIT = new Semaphore(1, true);
    private static final ScheduledExecutorService RELEASES = Executors.newSingleThreadScheduledExecutor(task -> {
        Thread thread = new Thread(task, "gpu-rpc-release");
        thread.setDaemon(true);
        return thread;
    });
    private GpuRpcGate() {}

    static Permit acquire() throws InterruptedException {
        PERMIT.acquire();
        return new Permit();
    }

    static final class Permit implements AutoCloseable {
        private final AtomicBoolean released = new AtomicBoolean();
        private volatile long holdUntilNs;
        /** A timed-out/canceled Binder request may still occupy GpuService.
         * Its native watchdog kills that process at 8 s; one extra second
         * absorbs dispatch and reply scheduling. Never block caller cancellation. */
        void holdUntilServiceDeadline(long sentNs) {
            holdUntilNs = sentNs + TimeUnit.SECONDS.toNanos(9);
        }
        public void close() {
            if (!released.compareAndSet(false, true)) return;
            long delay = holdUntilNs - System.nanoTime();
            if (delay > 0) RELEASES.schedule(() -> { PERMIT.release(); }, delay, TimeUnit.NANOSECONDS);
            else PERMIT.release();
        }
    }
}
