package org.enigmagrid.android;

import javax.net.ssl.HttpsURLConnection;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.enigmagrid.core.Canonical;

/** HTTPS transport with system certificate validation and no credential redirects. */
final class CoordinatorClient {
    static final class HttpFailure extends IOException implements org.enigmagrid.core.WorkBlockPipeline.RetryHint {
        final int status;final long retryAfterMillis;
        HttpFailure(int status){this(status,0);}
        HttpFailure(int status,long retryAfterMillis){super("Coordinator HTTP "+status);this.status=status;this.retryAfterMillis=retryAfterMillis;}
        public int status(){return status;}
        public long retryAfterMillis(){return retryAfterMillis;}
    }
    private final String origin;
    private final javax.net.ssl.SSLSocketFactory tls;
    private final java.util.concurrent.atomic.AtomicReference<HttpsURLConnection> active=new java.util.concurrent.atomic.AtomicReference<>();
    CoordinatorClient(String origin) {this(origin,null);}
    CoordinatorClient(String origin,javax.net.ssl.SSLSocketFactory tls) {
        this.tls=tls;
        try {
            URI u=new URI(origin);
            if(!"https".equals(u.getScheme())||u.getHost()==null||u.getRawUserInfo()!=null||u.getRawQuery()!=null||u.getRawFragment()!=null||!(u.getPath().isEmpty()||u.getPath().equals("/")))throw new IllegalArgumentException("Use an HTTPS coordinator origin");
            this.origin=origin.endsWith("/")?origin.substring(0,origin.length()-1):origin;
        }catch(URISyntaxException e){throw new IllegalArgumentException("Invalid coordinator address");}
    }
    String origin(){return origin;}
    CoordinatorClient fork(){return new CoordinatorClient(origin,tls); }
    void cancel(){
        HttpsURLConnection connection=active.getAndSet(null);
        if(connection==null)return;
        // Android disconnect can wait for an in-flight socket operation. Never block
        // the service/UI thread handling Stop while that operation finishes.
        Thread closer=new Thread(()->connection.disconnect(),"coordinator-disconnect");
        closer.setDaemon(true);closer.start();
    }
    synchronized Map<String,Object> request(String path,Map<String,Object> payload,String token) throws Exception {
        if(!path.matches("/(health|api/[a-z0-9/-]+)"))throw new IllegalArgumentException("Invalid endpoint");
        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();
        HttpsURLConnection c=(HttpsURLConnection)new URL(origin+path).openConnection();active.set(c);
        try {
            if(tls!=null)c.setSSLSocketFactory(tls);
            c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(30000);
            c.setRequestProperty("User-Agent","EnigmaGridAndroid/"+BuildConfig.VERSION_NAME);c.setRequestProperty("Accept","application/json");
            if(token!=null){if(!token.matches("[A-Za-z0-9_\\-]{16,512}"))throw new IllegalArgumentException("Invalid credential format");c.setRequestProperty("X-Device-Token",token);}
            if(payload!=null) {
                boolean blockProtocol=path.equals("/api/work-blocks")||path.startsWith("/api/work-blocks/");
                byte[] bytes=(path.equals("/api/device/telemetry/v1")?TelemetryJson.json(payload):
                    blockProtocol?org.enigmagrid.core.WorkBlockJson.json(payload):Canonical.json(payload)).getBytes(StandardCharsets.UTF_8);
                int bodyLimit=path.equals("/api/device/telemetry/v1")?8192:path.equals("/api/work-blocks/result-groups")?768*1024:blockProtocol?256*1024:4*1024*1024;
                if(bytes.length>bodyLimit)throw new IOException("Request exceeds size limit");
                c.setRequestMethod("POST");c.setDoOutput(true);c.setFixedLengthStreamingMode(bytes.length);c.setRequestProperty("Content-Type","application/json");
                try(OutputStream output=c.getOutputStream()){output.write(bytes);}
            }
            int code=c.getResponseCode();
            if(code<200||code>=300){
                long retry=0;
                String header=c.getHeaderField("Retry-After");
                if(header!=null)try{
                    long seconds=Long.parseLong(header.trim());
                    retry=seconds>0?Math.min(seconds,Long.MAX_VALUE/1000)*1000:0;
                }catch(NumberFormatException invalid){
                    try{retry=Math.max(0,c.getHeaderFieldDate("Retry-After",0)-System.currentTimeMillis());}
                    catch(IllegalArgumentException ignored){}
                }
                throw new HttpFailure(code,retry);
            }
            try(InputStream input=c.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192];int size=0,n;
                while((n=input.read(buffer))!=-1){if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();size+=n;if(size>4*1024*1024)throw new IOException("Response exceeds size limit");output.write(buffer,0,n);}
                return JsonCodec.object(new String(output.toByteArray(),StandardCharsets.UTF_8));
            }
        }finally{active.compareAndSet(c,null);c.disconnect();}
    }
}
