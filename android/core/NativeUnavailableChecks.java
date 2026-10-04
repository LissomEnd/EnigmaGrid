package org.enigmagrid.android;

import java.util.Arrays;
import java.util.Collections;
import org.enigmagrid.core.*;

/** Executes the real JNI loader with an empty native-library path. */
public final class NativeUnavailableChecks {
    public static void main(String[] args) {
        if (!VulkanBackend.probe().contains("CPU remains available"))
            throw new AssertionError("Missing backend was not reported");
        BoundedCrib.Key key = BoundedCrib.coreAt(123456);
        int[] attempts = {0};
        AdaptiveRows rows = new AdaptiveRows((k, offset, length) -> {
            attempts[0]++;
            int[] flat = VulkanBackend.rows(RowBatch.pack(Collections.singletonList(k), offset, length), new byte[0]);
            return RowBatch.unpack(flat, 1, length)[0];
        }, () -> 100, () -> false, new WorkControl.Timing() {
            public long nanos() { return System.nanoTime(); }
            public void sleep(long ms) throws InterruptedException { Thread.sleep(ms); }
        });
        for (int length : new int[]{1, 2, 3, 16, 71, 72}) {
            int offset = 72 - length;
            if (!Arrays.deepEquals(rows.rows(key, offset, length), BoundedCrib.cpuRows(key, offset, length)))
                throw new AssertionError("CPU fallback parity: " + length);
        }
        if (attempts[0] != 1 || !rows.failed() || rows.available() || rows.dispatches() != 0)
            throw new AssertionError("Unavailable native backend was retried or reported active");
        System.out.println("PASS: actual missing JNI library, CPU parity at six boundaries, one attempt, truthful GPU telemetry");
    }
}
