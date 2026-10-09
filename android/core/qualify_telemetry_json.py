"""Check Android telemetry decimals against the coordinator's wire validator."""
import argparse
import json
import pathlib
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument("--jdk", required=True)
args = parser.parse_args()
root = pathlib.Path(__file__).resolve().parents[2]
src = root / "android"
jdk = pathlib.Path(args.jdk) / "bin"
with tempfile.TemporaryDirectory() as directory:
    output = pathlib.Path(directory)
    stubs = output / "stubs"
    (stubs / "org/enigmagrid/android").mkdir(parents=True)
    (stubs / "org/enigmagrid/core").mkdir(parents=True)
    (stubs / "org/enigmagrid/android/BuildConfig.java").write_text(
        'package org.enigmagrid.android;final class BuildConfig{static final String VERSION_NAME="0.5.0";}',
        encoding="utf-8",
    )
    (stubs / "org/enigmagrid/android/JsonCodec.java").write_text(
        'package org.enigmagrid.android;import java.util.*;final class JsonCodec{static Map<String,Object> object(String s){return Collections.emptyMap();}}',
        encoding="utf-8",
    )
    (stubs / "org/enigmagrid/core/WorkBlockPipeline.java").write_text(
        'package org.enigmagrid.core;public final class WorkBlockPipeline{public interface RetryHint{int status();long retryAfterMillis();}}',
        encoding="utf-8",
    )
    subprocess.run([
        str(jdk / "javac"), "-d", str(output),
        str(src / "core/src/main/java/org/enigmagrid/core/Canonical.java"),
        str(src / "core/src/main/java/org/enigmagrid/core/WorkBlockJson.java"),
        str(src / "app/src/main/java/org/enigmagrid/android/TelemetryJson.java"),
        str(src / "app/src/main/java/org/enigmagrid/android/CoordinatorClient.java"),
        str(src / "core/TelemetryJsonChecks.java"),
        str(stubs / "org/enigmagrid/android/BuildConfig.java"),
        str(stubs / "org/enigmagrid/android/JsonCodec.java"),
        str(stubs / "org/enigmagrid/core/WorkBlockPipeline.java"),
    ], check=True)
    result = subprocess.run([
        str(jdk / "java"), "-cp", str(output),
        "org.enigmagrid.android.TelemetryJsonChecks",
    ], check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout.strip())

    reporter_output = output / "reporter"
    reporter_stubs = output / "reporter-stubs"
    (reporter_stubs / "android/content").mkdir(parents=True)
    (reporter_stubs / "org/enigmagrid/android").mkdir(parents=True)
    (reporter_stubs / "org/enigmagrid/core").mkdir(parents=True)
    sources = {
        "android/content/Context.java": """package android.content;
public class Context {public Context getApplicationContext(){return this;}}""",
        "org/enigmagrid/core/ServerTimeAnchor.java": """package org.enigmagrid.core;
public final class ServerTimeAnchor {public static long currentMs;
public ServerTimeAnchor(long serverMs,long receivedNs){}public long nowMs(long nowNs){return currentMs;}}""",
        "org/enigmagrid/android/BuildConfig.java": """package org.enigmagrid.android;
final class BuildConfig {static final String VERSION_NAME="0.5.0";}""",
        "org/enigmagrid/android/DeviceTelemetry.java": """package org.enigmagrid.android;
import android.content.Context;
final class DeviceTelemetry {static String provider="unavailable";static float gpu=Float.NaN;static final class Sample {
float cpuUsagePercent=17.25f,gpuUsagePercent=gpu,cpuTempC=58f,
gpuTempC=Float.NaN,batteryTempC=39f;long pssKb=100000;
} Sample sample(Context context){return new Sample();}
static String gpuProvider(){return provider;}}""",
        "org/enigmagrid/android/NetworkWorker.java": """package org.enigmagrid.android;
final class NetworkWorker {interface TelemetrySession {void start();void close();}
String backend="cpu";String backendName(){return backend;}int readyJobs(){return 3;}int pendingResults(){return 2;}
String phase(){return "Computing assigned work";}long completedJobs(){return 0;}
long completedUnits(){return 0;}long acknowledgedReceipts(){return 0;}
double computeSeconds(){return 0;}double persistenceSeconds(){return 0;}
double uploadWaitSeconds(){return 0;}double leaseWaitSeconds(){return 0;}}""",
        "org/enigmagrid/android/CoordinatorClient.java": """package org.enigmagrid.android;
import java.io.*;import java.util.*;import org.enigmagrid.core.Canonical;
final class CoordinatorClient {static final class HttpFailure extends IOException {
int status;long retryAfterMillis;}
int calls;Map<String,Object> payload;boolean failOnce,blockNext;
java.util.List<Map<String,Object>> payloads=new java.util.ArrayList<>();
java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1),release=new java.util.concurrent.CountDownLatch(1);
Map<String,Object> request(String path,Map<String,Object> body,String token)throws IOException{
if(!path.equals("/api/device/telemetry/v1"))throw new AssertionError(path);
calls++;payload=body;payloads.add(body);
if(failOnce){failOnce=false;throw new IOException("simulated outage");}
if(blockNext){blockNext=false;entered.countDown();try{if(!release.await(2,java.util.concurrent.TimeUnit.SECONDS))throw new IOException("slow upload timeout");}catch(InterruptedException error){Thread.currentThread().interrupt();throw new IOException(error);}}
return Canonical.object("ok",true,"accepted",((List<?>)body.get("buckets")).size());}
void cancel(){}}""",
    }
    for name, text in sources.items():
        path = reporter_stubs / name
        path.write_text(text, encoding="utf-8")
    subprocess.run([
        str(jdk / "javac"), "-d", str(reporter_output),
        str(src / "core/src/main/java/org/enigmagrid/core/Canonical.java"),
        str(src / "app/src/main/java/org/enigmagrid/android/TelemetryJson.java"),
        str(src / "app/src/main/java/org/enigmagrid/android/DeviceTelemetryReporter.java"),
        str(src / "core/DeviceTelemetryReporterChecks.java"),
        *(str(reporter_stubs / name) for name in sources),
    ], check=True)
    reporter_result = subprocess.run([
        str(jdk / "java"), "-cp", str(reporter_output),
        "org.enigmagrid.android.DeviceTelemetryReporterChecks",
    ], check=True, capture_output=True, text=True)
    reporter_payloads = json.loads(reporter_result.stdout.strip())

sys.path.insert(0, str(root / "server"))
import device_telemetry  # noqa: E402

device_telemetry.validate(payload)
for packets in reporter_payloads.values():
    for packet in packets:
        # The slow-network fixture advances its fake clock several minutes;
        # use the packet's own time to validate wire shape, not freshness.
        device_telemetry.validate(packet, now_ms=packet["buckets"][-1]["start_ms"] + 5000)
with tempfile.TemporaryDirectory(prefix="enigma-telemetry-flap-") as directory:
    now_ms = max(bucket["start_ms"] for packet in reporter_payloads["flap"]
                 for bucket in packet["buckets"]) + 5000
    for packet in reporter_payloads["flap"]:
        response = device_telemetry.ingest(pathlib.Path(directory) / "telemetry.sqlite3",
                                           "dev_host_fixture", packet, now_ms=now_ms)
        assert response["ok"] and response["accepted"] == len(packet["buckets"])
print("PASS finite Android telemetry, bounded catch-up/profile coalescing, identical retry and server-validated packets")
