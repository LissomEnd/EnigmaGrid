package org.enigmagrid.android;

import javax.net.ssl.HttpsURLConnection;
import java.net.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import org.enigmagrid.core.Canonical;

/** HTTPS transport with system certificate validation and no credential redirects. */
final class CoordinatorClient {
    static final class HttpFailure extends IOException {final int status;HttpFailure(int status){super("Coordinator HTTP "+status);this.status=status;}}
    private final String origin;
    private final javax.net.ssl.SSLSocketFactory tls;
    private volatile HttpsURLConnection active;
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
    void cancel(){HttpsURLConnection connection=active;if(connection!=null)connection.disconnect();}
    synchronized Map<String,Object> request(String path,Map<String,Object> payload,String token) throws Exception {
        if(!path.matches("/(health|api/[a-z/-]+)"))throw new IllegalArgumentException("Invalid endpoint");
        if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();
        HttpsURLConnection c=(HttpsURLConnection)new URL(origin+path).openConnection();active=c;
        try {
            if(tls!=null)c.setSSLSocketFactory(tls);
            c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(30000);
            c.setRequestProperty("User-Agent","EnigmaGridAndroid/0.4.4");c.setRequestProperty("Accept","application/json");
            if(token!=null){if(!token.matches("[A-Za-z0-9_\\-]{16,512}"))throw new IllegalArgumentException("Invalid credential format");c.setRequestProperty("X-Device-Token",token);}
            if(payload!=null) {
                byte[] bytes=Canonical.json(payload).getBytes(StandardCharsets.UTF_8);
                if(bytes.length>4*1024*1024)throw new IOException("Request exceeds size limit");
                c.setRequestMethod("POST");c.setDoOutput(true);c.setFixedLengthStreamingMode(bytes.length);c.setRequestProperty("Content-Type","application/json");
                try(OutputStream output=c.getOutputStream()){output.write(bytes);}
            }
            int code=c.getResponseCode();
            if(code<200||code>=300)throw new HttpFailure(code);
            try(InputStream input=c.getInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[8192];int size=0,n;
                while((n=input.read(buffer))!=-1){if(Thread.currentThread().isInterrupted())throw new InterruptedIOException();size+=n;if(size>4*1024*1024)throw new IOException("Response exceeds size limit");output.write(buffer,0,n);}
                return JsonCodec.object(new String(output.toByteArray(),StandardCharsets.UTF_8));
            }
        }finally{active=null;c.disconnect();}
    }
}
