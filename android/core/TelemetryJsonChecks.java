package org.enigmagrid.android;

import java.util.Arrays;
import java.util.Map;
import org.enigmagrid.core.Canonical;

/** Host check for decimal diagnostics without widening the scientific JSON protocol. */
public final class TelemetryJsonChecks {
    public static void main(String[] args) {
        long start=System.currentTimeMillis()/5000*5000;
        Map<String,Object> bucket=Canonical.object("start_ms",start,"duration_ms",5000,"samples",3,
            "jobs_done",12L,"cpu_percent",17.25,"gpu_percent",43.5f,"cpu_temp_c",58.0);
        Map<String,Object> payload=Canonical.object("format","device_telemetry_v1",
            "session_id","testsession0123456789","seq",0L,"worker_version","0.5.0",
            "backend","vulkan-mixed2","cpu_scope","process","gpu_scope","device",
            "cpu_provider","Android process CPU time","gpu_provider","KGSL gpubusy",
            "buckets",Arrays.asList(bucket));
        String json=TelemetryJson.json(payload);
        if(!json.contains("\"cpu_percent\":17.25")||!json.contains("\"gpu_percent\":43.5"))
            throw new AssertionError("Decimal readings lost");
        try {Canonical.json(payload);throw new AssertionError("Scientific JSON accepted decimals");}
        catch(IllegalArgumentException expected) {}
        bucket.put("cpu_percent",Double.NaN);
        try {TelemetryJson.json(payload);throw new AssertionError("Non-finite reading accepted");}
        catch(IllegalArgumentException expected) {}
        bucket.put("cpu_percent",17.25);
        System.out.println(json);
    }
}
