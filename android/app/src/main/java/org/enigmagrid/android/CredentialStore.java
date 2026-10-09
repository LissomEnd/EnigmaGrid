package org.enigmagrid.android;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import java.io.*;
import java.security.KeyStore;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import javax.crypto.*;
import javax.crypto.spec.GCMParameterSpec;
import org.enigmagrid.core.Canonical;

/** App-private atomic AES-GCM storage. Android Keystore key material is non-exportable. */
final class CredentialStore implements org.enigmagrid.core.ReceiptQueue.Storage {
    private final String alias;
    private final AtomicFile file;
    private final File directory;
    private final int limit;
    // The non-exportable Keystore handle is stable for this store's lifetime.
    // A fresh Cipher/IV is still required for every independently durable save.
    private javax.crypto.SecretKey cachedKey;
    CredentialStore(Context context){this(context,false);}
    CredentialStore(Context context,boolean qualification){
        this(context.getNoBackupFilesDir(),"org.enigmagrid.android.credentials.v1"+(qualification?".qualification":""),qualification?"qualification.enc":"credentials.enc",65536);
    }
    private CredentialStore(File directory,String alias,String name,int limit){this.directory=directory;this.alias=alias;this.file=new AtomicFile(new File(directory,name));this.limit=limit;}
    CredentialStore pendingResults(){return new CredentialStore(directory,alias+".results",alias.endsWith(".qualification")?"qualification-results.enc":"pending-result.enc",8*1024*1024);}
    CredentialStore workBlocks(){return new CredentialStore(directory,alias+".blocks",alias.endsWith(".qualification")?"qualification-blocks.enc":"work-blocks.enc",8*1024*1024);}
    org.enigmagrid.core.ReceiptQueue.Storage workBlockStorage(){
        CredentialStore blocks=workBlocks();
        File recordDirectory=new File(directory,blocks.file.getBaseFile().getName()+".receipts");
        org.enigmagrid.core.ReceiptQueue.Storage manifest=new org.enigmagrid.core.ReceiptQueue.Storage(){
            private boolean migrationChecked;
            public Map<String,Object> load()throws Exception{return blocks.load();}
            public void save(Map<String,Object> value)throws Exception{
                if(!migrationChecked){
                    Map<String,Object> old=blocks.load();
                    if(old!=null&&!old.containsKey("storage_format")){
                        CredentialStore backup=new CredentialStore(directory,blocks.alias,blocks.file.getBaseFile().getName()+".legacy",blocks.limit);
                        backup.cachedKey=blocks.key();
                        if(backup.load()==null)backup.save(old);
                    }
                    migrationChecked=true;
                }
                blocks.save(value);
            }
        };
        return new org.enigmagrid.core.ChunkedBlockStorage(manifest,new org.enigmagrid.core.ChunkedBlockStorage.Records(){
            private CredentialStore record(String hash)throws Exception{
                if(hash==null||!hash.matches("[0-9a-f]{64}"))throw new IOException("Invalid receipt filename");
                CredentialStore item=new CredentialStore(recordDirectory,blocks.alias,hash+".enc",blocks.limit);
                item.cachedKey=blocks.key();return item;
            }
            public Map<String,Object> load(String hash)throws Exception{return record(hash).load();}
            public void save(String hash,Map<String,Object> value)throws Exception{record(hash).save(value);}
            public void retain(java.util.Set<String> hashes)throws Exception{
                File[] files=recordDirectory.listFiles();if(files==null)return;
                for(File path:files){
                    String name=path.getName();
                    if(name.matches("[0-9a-f]{64}\\.enc(?:\\.new|\\.bak)?")){
                        String hash=name.substring(0,64);
                        if(!hashes.contains(hash))record(hash).clear();
                    }
                }
            }
        },128*1024);
    }
    CredentialStore expiredResults(){return new CredentialStore(directory,alias+".blocks.archive",alias.endsWith(".qualification")?"qualification-expired.enc":"expired-results.enc",8*1024*1024);}
    CredentialStore registrationAttempt(){return new CredentialStore(directory,alias+".registration",alias.endsWith(".qualification")?"qualification-registration.enc":"registration-attempt.enc",65536);}
    synchronized void clear(){file.delete();}
    private javax.crypto.SecretKey key() throws Exception {
        if(cachedKey!=null)return cachedKey;
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(alias)) {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());generator.generateKey();
        }
        javax.crypto.SecretKey found=(javax.crypto.SecretKey)store.getKey(alias,null);
        if(found==null)throw new java.security.KeyStoreException("Missing storage key");
        cachedKey=found;
        return found;
    }
    public synchronized void save(Map<String,Object> state) throws Exception {
        byte[] plain=((alias.endsWith(".blocks")||alias.endsWith(".blocks.archive"))?org.enigmagrid.core.WorkBlockJson.json(state):Canonical.json(state)).getBytes(StandardCharsets.UTF_8);
        if(plain.length>limit)throw new IOException("Encrypted record too large");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());
        cipher.updateAAD(alias.getBytes(StandardCharsets.UTF_8));byte[] encrypted=finishChunks(cipher,plain,0,plain.length),iv=cipher.getIV();
        FileOutputStream output=null;
        try {output=file.startWrite();output.write(1);output.write(iv.length);output.write(iv);output.write(encrypted);file.finishWrite(output);}
        catch(Exception e){if(output!=null)file.failWrite(output);throw e;}
    }
    // Bound calls into older KeyStore providers; never expose plaintext before tag verification.
    private static byte[] finishChunks(Cipher cipher,byte[] input,int offset,int length) throws Exception {
        ByteArrayOutputStream output=new ByteArrayOutputStream();
        int end=offset+length;
        while(offset<end){
            int count=Math.min(16384,end-offset);
            byte[] part=cipher.update(input,offset,count);
            if(part!=null)output.write(part);
            offset+=count;
        }
        byte[] last=cipher.doFinal();
        if(last!=null)output.write(last);
        return output.toByteArray();
    }
    public synchronized Map<String,Object> load() throws Exception {
        byte[] raw;
        try(InputStream input=file.openRead();ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];int n;while((n=input.read(buffer))!=-1){if(out.size()+n>limit+64)throw new IOException("Encrypted record too large");out.write(buffer,0,n);}raw=out.toByteArray();
        }catch(FileNotFoundException e){return null;}
        if(raw.length<30||raw[0]!=1||raw[1]!=12)throw new IOException("Invalid credential record");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,raw,2,12));cipher.updateAAD(alias.getBytes(StandardCharsets.UTF_8));
        return JsonCodec.object(new String(finishChunks(cipher,raw,14,raw.length-14),StandardCharsets.UTF_8));
    }
}
