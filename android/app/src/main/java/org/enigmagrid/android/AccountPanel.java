package org.enigmagrid.android;

import android.app.*;
import android.content.SharedPreferences;
import android.text.InputType;
import android.widget.*;
import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Explicit volunteer enrollment; credentials are never shown in status text. */
final class AccountPanel {
    private final Activity activity;
    private final CredentialStore store;
    private final TextView status;
    private final Button register;
    AccountPanel(Activity activity,LinearLayout parent){
        this.activity=activity;store=new CredentialStore(activity.getApplicationContext());
        text(parent,"Your account",22);
        text(parent,"Register this Android device to receive credits for verified work. Registration does not start computation. Only compatible constrained-search jobs are requested.",16);
        SharedPreferences settings=activity.getSharedPreferences("worker-settings",0);
        EditText origin=field(parent,"Coordinator HTTPS address",false);origin.setText(settings.getString("server","https://enigma-grid.tail40f219.ts.net"));
        EditText name=field(parent,"Display name (optional)",false);
        EditText join=field(parent,"Existing contributor key (optional)",true);
        text(parent,"Leave the contributor key empty to create a new private contributor profile. Supply your existing key to credit this device to that profile. Public credit is off for new profiles.",15);
        status=text(parent,"Checking saved account...",16);
        register=new Button(activity);register.setText("Register this device");parent.addView(register);register.setEnabled(false);
        Button refresh=new Button(activity);refresh.setText("Refresh account status");parent.addView(refresh);refresh.setOnClickListener(v->refresh());
        register.setOnClickListener(v->{
            final CoordinatorClient client;
            try{client=new CoordinatorClient(origin.getText().toString().trim());}catch(IllegalArgumentException e){status.setText("Enter a valid HTTPS coordinator address.");return;}
            final String display=name.getText().toString(),key=join.getText().toString();
            new AlertDialog.Builder(activity).setTitle("Register this device?").setMessage("Send the display name, device capabilities and resource settings to "+client.origin()+"? Computation remains stopped.")
                .setNegativeButton("Cancel",null).setPositiveButton("Register",(dialog,which)->{
                    register.setEnabled(false);status.setText("Registering. Please wait; do not repeat the request.");
                    Map<String,Object> limits=object("cpu_percent",settings.getInt("cpu_percent",25),"gpu_percent",settings.getInt("gpu_percent",0),"allow_cpu",settings.getInt("cpu_percent",25)>0,"allow_gpu",settings.getInt("gpu_percent",0)>0);
                    new Thread(()->{
                        String message;
                        try{Enrollment.register(client,store,display,key,limits,()->false);settings.edit().putString("server",client.origin()).apply();message="Device registered. Credentials saved securely. Computation has not started.";}
                        catch(Exception e){message="Registration did not finish. Refresh account status before trying again.";}
                        final String result=message;activity.runOnUiThread(()->{if(!activity.isDestroyed()){join.setText("");status.setText(result);refresh();}});
                    },"account-registration").start();
                }).show();
        });
        refresh();
    }
    private void refresh(){
        register.setEnabled(false);
        new Thread(()->{
            String message;boolean canRegister=false;
            try{
                Map<String,Object> account=store.load();
                if(account!=null)message="Registered with "+account.get("server")+". "+(account.containsKey("dashboard_token")?"Personal statistics are available from Dashboard.":"This device is linked to an existing profile; its dashboard token is not stored here.");
                else if(store.registrationAttempt().load()!=null)message="An earlier registration has an unknown outcome. A repeat request is blocked to prevent duplicate accounts. Credentials must be recovered before another registration.";
                else{message="No account saved. Registration is optional until you choose to contribute.";canRegister=true;}
            }catch(Exception e){message="Saved account could not be read. It has not been replaced.";}
            final String result=message;final boolean enabled=canRegister;
            activity.runOnUiThread(()->{if(!activity.isDestroyed()){status.setText(result);register.setEnabled(enabled);}});
        },"account-status").start();
    }
    private EditText field(LinearLayout parent,String hint,boolean secret){EditText field=new EditText(activity);field.setSingleLine(true);field.setHint(hint);field.setContentDescription(hint);field.setInputType(InputType.TYPE_CLASS_TEXT|(secret?InputType.TYPE_TEXT_VARIATION_PASSWORD:InputType.TYPE_TEXT_VARIATION_NORMAL));field.setSaveEnabled(!secret);if(secret)field.setImportantForAutofill(android.view.View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS);parent.addView(field);return field;}
    private TextView text(LinearLayout parent,String value,int size){TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);view.setTextColor(size>=22?0xff43ddd0:0xffe2edf2);view.setPadding(0,16,0,16);parent.addView(view);return view;}
}
