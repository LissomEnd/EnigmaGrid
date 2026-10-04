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
final class CredentialStore {
    private final String alias;
    private final AtomicFile file;
    private final File directory;
    private final int limit;
    CredentialStore(Context context){this(context,false);}
    CredentialStore(Context context,boolean qualification){
        this(context.getNoBackupFilesDir(),"org.enigmagrid.android.credentials.v1"+(qualification?".qualification":""),qualification?"qualification.enc":"credentials.enc",65536);
    }
    private CredentialStore(File directory,String alias,String name,int limit){this.directory=directory;this.alias=alias;this.file=new AtomicFile(new File(directory,name));this.limit=limit;}
    CredentialStore pendingResults(){return new CredentialStore(directory,alias+".results",alias.endsWith(".qualification")?"qualification-results.enc":"pending-result.enc",8*1024*1024);}
    CredentialStore registrationAttempt(){return new CredentialStore(directory,alias+".registration",alias.endsWith(".qualification")?"qualification-registration.enc":"registration-attempt.enc",65536);}
    synchronized void clear(){file.delete();}
    private javax.crypto.SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(alias)) {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());generator.generateKey();
        }
        return (javax.crypto.SecretKey)store.getKey(alias,null);
    }
    synchronized void save(Map<String,Object> state) throws Exception {
        byte[] plain=Canonical.json(state).getBytes(StandardCharsets.UTF_8);
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
    synchronized Map<String,Object> load() throws Exception {
        byte[] raw;
        try(InputStream input=file.openRead();ByteArrayOutputStream out=new ByteArrayOutputStream()) {
            byte[] buffer=new byte[4096];int n;while((n=input.read(buffer))!=-1){if(out.size()+n>limit+64)throw new IOException("Encrypted record too large");out.write(buffer,0,n);}raw=out.toByteArray();
        }catch(FileNotFoundException e){return null;}
        if(raw.length<30||raw[0]!=1||raw[1]!=12)throw new IOException("Invalid credential record");
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,raw,2,12));cipher.updateAAD(alias.getBytes(StandardCharsets.UTF_8));
        return JsonCodec.object(new String(finishChunks(cipher,raw,14,raw.length-14),StandardCharsets.UTF_8));
    }
}
