package org.enigmagrid.android;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import javax.net.ssl.HttpsURLConnection;
import org.json.*;
import org.enigmagrid.core.UpdatePolicy;

/** Public metadata only. Never sends device credentials to GitHub. */
final class UpdateChecker {
 static final String REPOSITORY="https://api.github.com/repos/LissomEnd/EnigmaGrid/releases?per_page=100";
 static final class Result {
  final UpdatePolicy.State state;final String minimum,version,url,sha256,notes;final long size;
  Result(UpdatePolicy.State state,String minimum,String version,String url,String sha256,String notes,long size){this.state=state;this.minimum=minimum;this.version=version;this.url=url;this.sha256=sha256;this.notes=notes;this.size=size;}
 }
 static Result check(String origin,String installed)throws Exception {
  Map<String,Object> config=new CoordinatorClient(origin).request("/api/public/config",null,null);
  Object rawMinimum=config.get("min_worker_version");
  if(!(rawMinimum instanceof String))throw new IOException("Missing coordinator minimum version");
  String minimum=(String)rawMinimum;
  UpdatePolicy.evaluate(installed,minimum,null);
  JSONArray releases;
  try{releases=new JSONArray(read(REPOSITORY));}catch(Exception unavailable){
   if(UpdatePolicy.evaluate(installed,minimum,null)==UpdatePolicy.State.REQUIRED_UNAVAILABLE)return new Result(UpdatePolicy.State.REQUIRED_UNAVAILABLE,minimum,null,null,null,"Update service unavailable",0);
   throw unavailable;
  }String newest=null,url=null,hash=null,notes=null;long size=0;
  for(int i=0;i<releases.length();i++){
   JSONObject release=releases.getJSONObject(i);if(release.optBoolean("draft",true))continue;
   String tag=release.optString("tag_name","");if(!tag.startsWith("android-v"))continue;
   String version=tag.substring(9);
   try{if(UpdatePolicy.compare(version,installed)<=0||(newest!=null&&UpdatePolicy.compare(version,newest)<=0))continue;}catch(IllegalArgumentException invalid){continue;}
   JSONArray assets=release.optJSONArray("assets");if(assets==null)continue;
   for(int j=0;j<assets.length();j++){
    JSONObject asset=assets.getJSONObject(j);
    if(!asset.optString("name").equals("EnigmaGrid-Android-"+version+".apk"))continue;
    String expected="https://github.com/LissomEnd/EnigmaGrid/releases/download/"+tag+"/EnigmaGrid-Android-"+version+".apk";
    String digest=asset.optString("digest","");long bytes=asset.optLong("size",0);
    if(!expected.equals(asset.optString("browser_download_url"))||!digest.matches("sha256:[0-9a-f]{64}")||bytes<1||bytes>100*1024*1024)continue;
    newest=version;url=expected;hash=digest.substring(7);size=bytes;notes=release.optString("body","");break;
   }
  }
  return new Result(UpdatePolicy.evaluate(installed,minimum,newest),minimum,newest,url,hash,notes,size);
 }
 private static String read(String address)throws Exception {
  HttpsURLConnection c=(HttpsURLConnection)new URL(address).openConnection();
  c.setInstanceFollowRedirects(false);c.setConnectTimeout(15000);c.setReadTimeout(30000);
  c.setRequestProperty("Accept","application/vnd.github+json");c.setRequestProperty("User-Agent","EnigmaGridAndroid");
  try{
   if(c.getResponseCode()!=200)throw new IOException("Update service HTTP "+c.getResponseCode());
   try(InputStream in=c.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()){
    byte[] b=new byte[8192];int n;while((n=in.read(b))!=-1){if(out.size()+n>4*1024*1024)throw new IOException("Update metadata too large");out.write(b,0,n);}
    return new String(out.toByteArray(),StandardCharsets.UTF_8);
   }
  }finally{c.disconnect();}
 }
}
