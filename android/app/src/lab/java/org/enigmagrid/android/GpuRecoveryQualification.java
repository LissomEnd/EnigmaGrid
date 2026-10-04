package org.enigmagrid.android;

import android.app.Activity;
import android.app.ActivityManager;
import android.app.Instrumentation;
import android.content.Context;
import android.os.Bundle;
import android.os.SystemClock;
import java.util.Arrays;
import org.enigmagrid.core.*;

/** Explicit lab-only process-death check; never binds or kills production. */
public final class GpuRecoveryQualification extends Instrumentation {
    public void onCreate(Bundle args) { super.onCreate(args); start(); }
    public void onStart() {
        Bundle result = new Bundle();
        try {
            Context context = getTargetContext();
            String pkg = context.getPackageName();
            if (!pkg.equals("org.enigmagrid.android.lab"))
                throw new IllegalStateException("Lab package required");
            BoundedCrib.Key key = BoundedCrib.coreAt(123456);
            int[][] expected = BoundedCrib.cpuRows(key, 3, 16);
            try (GpuProcess gpu = new GpuProcess(context)) {
                BatchedRows backend = new BatchedRows(gpu::rows, () -> false);
                AdaptiveRows rows = new AdaptiveRows(backend, () -> 100, () -> false,
                    new WorkControl.Timing() {
                        public long nanos() { return System.nanoTime(); }
                        public void sleep(long ms) throws InterruptedException { Thread.sleep(ms); }
                    });
                if (!Arrays.deepEquals(expected, rows.rows(key, 3, 16)) || rows.failed())
                    throw new AssertionError("GPU baseline failed");
                ActivityManager manager = (ActivityManager) context.getSystemService(Context.ACTIVITY_SERVICE);
                int pid = 0;
                for (ActivityManager.RunningAppProcessInfo process : manager.getRunningAppProcesses())
                    if (process.processName.equals(pkg + ":gpu") && process.uid == android.os.Process.myUid()) pid = process.pid;
                if (pid == 0 || pid == android.os.Process.myPid()) throw new AssertionError("Lab GPU process missing");
                android.os.Process.killProcess(pid);
                long start = SystemClock.elapsedRealtime();
                // No prepared batch cache: this call must cross the dead Binder.
                if (!Arrays.deepEquals(expected, rows.rows(key, 3, 16)) || !rows.failed())
                    throw new AssertionError("CPU fallback after process death failed");
                if (SystemClock.elapsedRealtime() - start > 12000) throw new AssertionError("Unbounded recovery");
                if (!Arrays.deepEquals(expected, rows.rows(key, 3, 16)) || rows.available())
                    throw new AssertionError("Failed backend reused");
                result.putString("result", "PASS: lab GPU process death, bounded CPU fallback and failure latch");
            }
            finish(Activity.RESULT_OK, result);
        } catch (Throwable error) {
            result.putString("result", "FAIL: " + error);
            finish(Activity.RESULT_CANCELED, result);
        }
    }
}
