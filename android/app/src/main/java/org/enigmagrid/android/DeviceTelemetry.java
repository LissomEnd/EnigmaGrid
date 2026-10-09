package org.enigmagrid.android;

import android.content.*;
import android.os.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

/** Lightweight local telemetry. Missing sensors are represented as NaN, never guessed. */
final class DeviceTelemetry {
    static final class Sample {
        final long capturedMs;
        final float cpuUsagePercent, gpuUsagePercent, cpuTempC, gpuTempC, batteryTempC, unitsPerSecond, jobsPerSecond;
        final long pssKb;
        final int thermalStatus;
        Sample(long capturedMs,float cpuUsagePercent,float gpuUsagePercent,float cpuTempC,float gpuTempC,float batteryTempC,long pssKb,int thermalStatus,float unitsPerSecond,float jobsPerSecond){
            this.capturedMs=capturedMs;this.cpuUsagePercent=cpuUsagePercent;this.gpuUsagePercent=gpuUsagePercent;
            this.cpuTempC=cpuTempC;this.gpuTempC=gpuTempC;this.batteryTempC=batteryTempC;this.pssKb=pssKb;this.thermalStatus=thermalStatus;
            this.unitsPerSecond=unitsPerSecond;this.jobsPerSecond=jobsPerSecond;
        }
        String summary(){
            return String.format(Locale.ROOT,
                "App CPU %s · Device GPU %s · RAM %.0f MB\nCPU temp %s · GPU temp %s · Battery %s · Android thermal %d\nThroughput %s units/s · %s jobs/s",
                pct(cpuUsagePercent),pct(gpuUsagePercent),pssKb/1024f,temp(cpuTempC),temp(gpuTempC),temp(batteryTempC),thermalStatus,rate(unitsPerSecond),rate(jobsPerSecond));
        }
        private static String pct(float v){return Float.isFinite(v)?String.format(Locale.ROOT,"%.1f%%",v):"n/a";}
        private static String temp(float v){return Float.isFinite(v)?String.format(Locale.ROOT,"%.1f°C",v):"n/a";}
        private static String rate(float v){return Float.isFinite(v)?String.format(Locale.ROOT,v>=10?"%.1f":"%.3f",v):"n/a";}
    }

    private long lastWallNs=-1,lastCpuMs=-1;
    synchronized Sample sample(Context context){
        long wall=SystemClock.elapsedRealtimeNanos(),cpuMs=android.os.Process.getElapsedCpuTime()+GpuProcess.cpuMillis();
        float cpuUsage=Float.NaN;
        if(lastWallNs>0&&wall>lastWallNs&&cpuMs>=lastCpuMs){
            double cores=Math.max(1,Runtime.getRuntime().availableProcessors());
            cpuUsage=(float)Math.max(0,Math.min(100,100.0*((cpuMs-lastCpuMs)*1_000_000.0)/(wall-lastWallNs)/cores));
        }
        lastWallNs=wall;lastCpuMs=cpuMs;
        float[] temps=readThermalZones();
        float battery=readBatteryTemp(context);
        float gpuUsage=readGpuBusy();
        PowerManager pm=(PowerManager)context.getSystemService(Context.POWER_SERVICE);
        int thermal=(pm!=null&&Build.VERSION.SDK_INT>=29)?pm.getCurrentThermalStatus():0;
        SharedPreferences status=context.getSharedPreferences("worker-status",Context.MODE_PRIVATE);
        float unitsPerSecond=status.getFloat("units_per_second",0f),jobsPerSecond=status.getFloat("jobs_per_second",0f);
        return new Sample(System.currentTimeMillis(),cpuUsage,gpuUsage,temps[0],temps[1],battery,Debug.getPss(),thermal,unitsPerSecond,jobsPerSecond);
    }

    static float[] temperatures(Context context){
        float[] values=readThermalZones();
        return new float[]{values[0],values[1],readBatteryTemp(context)};
    }

    private static float readBatteryTemp(Context context){
        Intent b=context.registerReceiver(null,new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        if(b==null)return Float.NaN;
        int raw=b.getIntExtra(BatteryManager.EXTRA_TEMPERATURE,-1);
        return raw>=0?raw/10f:Float.NaN;
    }

    private static float[] readThermalZones(){
        float cpu=Float.NaN,socFallback=Float.NaN,gpu=Float.NaN;
        File root=new File("/sys/class/thermal"); File[] zones=root.listFiles();
        if(zones==null)return new float[]{cpu,gpu};
        for(File zone:zones){
            if(!zone.getName().startsWith("thermal_zone"))continue;
            try{
                String type=read(new File(zone,"type")).trim().toLowerCase(Locale.ROOT);
                float value=parseTemp(read(new File(zone,"temp")));
                if(!Float.isFinite(value)||value<0||value>150)continue;
                if(isGpu(type))gpu=maxFinite(gpu,value);
                else if(isCpu(type))cpu=maxFinite(cpu,value);
                else if(type.contains("soc"))socFallback=maxFinite(socFallback,value);
            }catch(Exception ignored){}
        }
        // Vendor SoC sensors sometimes use raw, non-millidegree units (e.g.
        // Samsung SM-T500 reports soc=100 while CPU zones are ~35 C).
        // Prefer actual CPU-specific sensors; retain SoC as a fallback where
        // no CPU sensor exists. Android thermal status remains an independent guard.
        return new float[]{Float.isFinite(cpu)?cpu:socFallback,gpu};
    }

    private static boolean isGpu(String type){return type.contains("gpu")||type.contains("kgsl")||type.contains("gfx");}
    private static boolean isCpu(String type){
        return type.contains("cpu")||type.contains("cpuss")||type.contains("tsens");
    }
    private static float maxFinite(float a,float b){return Float.isFinite(a)?Math.max(a,b):b;}
    private static float parseTemp(String text){
        float v=Float.parseFloat(text.trim());
        if(Math.abs(v)>1000f)v/=1000f;
        return v;
    }
    private static String read(File file)throws IOException{
        try(InputStream in=new FileInputStream(file)){
            ByteArrayOutputStream out=new ByteArrayOutputStream();
            byte[] buf=new byte[128];int n;
            while((n=in.read(buf))>0&&out.size()<512)out.write(buf,0,n);
            return out.toString(StandardCharsets.UTF_8.name());
        }
    }
    private static final org.enigmagrid.core.GpuUtilizationWindow gpuWindow=new org.enigmagrid.core.GpuUtilizationWindow();
    private static volatile String gpuProvider="unavailable";
    static String gpuProvider(){return gpuProvider;}
    private static float readGpuBusy(){
        long now=SystemClock.elapsedRealtime();
        for(String path:new String[]{"/sys/class/kgsl/kgsl-3d0/gpubusy","/sys/class/drm/card0/device/gpu_busy_percent"}){
            try{
                String[] p=read(new File(path)).trim().split("\\s+");
                if(p.length==1){gpuProvider=path.contains("kgsl")?"KGSL gpubusy":"DRM gpu_busy_percent";return gpuWindow.add(now,Double.parseDouble(p[0]),100);}
                if(p.length>=2){
                    double busy=Double.parseDouble(p[0]),total=Double.parseDouble(p[1]);
                    if(total>0){gpuProvider=path.contains("kgsl")?"KGSL gpubusy":"DRM gpu_busy_percent";return gpuWindow.add(now,busy,total);}
                }
            }catch(Exception ignored){}
        }
        gpuProvider="unavailable";
        return gpuWindow.add(now,0,0);
    }
}
