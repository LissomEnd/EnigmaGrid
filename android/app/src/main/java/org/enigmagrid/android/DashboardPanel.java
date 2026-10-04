package org.enigmagrid.android;

import android.app.Activity;
import android.widget.*;
import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Native public/personal dashboard. Uses only volunteer API routes. */
final class DashboardPanel {
    private final Activity activity;
    private final LinearLayout results;
    DashboardPanel(Activity activity,LinearLayout parent) {
        this.activity=activity;
        text(parent,"Grid dashboard",22);
        EditText origin=new EditText(activity);origin.setSingleLine(true);origin.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);
        origin.setContentDescription("Coordinator HTTPS address");
        origin.setText(activity.getSharedPreferences("worker-settings",0).getString("server","https://enigma-grid.tail40f219.ts.net"));parent.addView(origin);
        Button refresh=new Button(activity);refresh.setText("Refresh dashboard");parent.addView(refresh);
        results=new LinearLayout(activity);results.setOrientation(LinearLayout.VERTICAL);parent.addView(results);
        text(results,"Refresh to load current public statistics. Personal statistics require a saved account.",16);
        refresh.setOnClickListener(v->{
            final CoordinatorClient client;
            try{client=new CoordinatorClient(origin.getText().toString().trim());}catch(IllegalArgumentException e){text(results,"Enter a valid HTTPS coordinator address.",16);return;}
            refresh.setEnabled(false);results.removeAllViews();text(results,"Loading…",16);
            new Thread(()->{
                Map<String,Object> global=null,personal=null;String error=null,personalError=null;
                try {
                    global=client.request("/api/public/status",null,null);
                    Map<String,Object> state=new CredentialStore(activity.getApplicationContext()).load();
                    if(state!=null&&client.origin().equals(state.get("server"))&&state.get("dashboard_token") instanceof String) {
                        try{personal=client.request("/api/me",object("dashboard_token",state.get("dashboard_token")),null);}catch(Exception e){personalError="Personal statistics unavailable; saved account retained.";}
                    }
                }catch(Exception e){error="Dashboard unavailable. Check the address and connection, then refresh.";}
                final Map<String,Object> g=global,p=personal;final String failure=error,pFailure=personalError;
                activity.runOnUiThread(()->{if(activity.isDestroyed())return;refresh.setEnabled(true);results.removeAllViews();
                    if(g!=null){renderPublic(g);activity.getSharedPreferences("worker-settings",0).edit().putString("server",client.origin()).apply();}
                    if(failure!=null)text(results,failure,16);
                    if(p!=null){text(results,"Your contribution",21);renderFields(results,p);}
                    else text(results,pFailure==null?"No personal account loaded for this coordinator.":pFailure,16);
                });
            },"dashboard-refresh").start();
        });
    }
    private void renderPublic(Map<String,Object> data) {
        text(results,"Updated "+java.text.DateFormat.getTimeInstance().format(new Date()),14);
        text(results,"Verified units: "+value(data,"completed_units")+" / "+value(data,"total_units"),19);
        text(results,"Progress: "+value(data,"progress_pct")+"%",18);
        text(results,"Awaiting verification: "+value(data,"pending_validations"),17);
        text(results,"Online devices: "+value(data,"online_devices")+" · CPU: "+value(data,"online_cpu_devices")+" · GPU: "+value(data,"online_gpu_devices"),17);
        text(results,"Registration: "+(Boolean.TRUE.equals(data.get("registration_open"))?"open":"closed"),16);
        text(results,"Campaigns",21);renderList(data.get("campaigns"));
        text(results,"Public contributions",21);renderList(data.get("leaderboard"));
        text(results,"Devices are not people. Credits are awarded after independent verification.",14);
    }
    private String value(Map<String,Object> data,String key){Object v=data.get(key);return v==null?"Unavailable":String.valueOf(v);}
    private void renderList(Object value){if(value instanceof List){List<?> rows=(List<?>)value;if(rows.isEmpty())text(results,"No entries",16);for(Object row:rows)if(row instanceof Map)renderFields(results,(Map<?,?>)row);}else text(results,"Unavailable",16);}
    private void renderFields(LinearLayout parent,Map<?,?> data) {
        for(Map.Entry<?,?> entry:data.entrySet()) {
            String key=String.valueOf(entry.getKey());Object value=entry.getValue();
            if(key.contains("token")||key.contains("secret")||key.equals("contributor_key"))continue;
            if(value instanceof Map){text(parent,title(key),18);renderFields(parent,(Map<?,?>)value);}
            else if(value instanceof List){text(parent,title(key),18);for(Object item:(List<?>)value){if(item instanceof Map)renderFields(parent,(Map<?,?>)item);else text(parent,String.valueOf(item),16);}}
            else text(parent,title(key)+": "+(value==null?"Unavailable":value),16);
        }
    }
    private static String title(String key){String s=key.replace('_',' ');return s.isEmpty()?s:Character.toUpperCase(s.charAt(0))+s.substring(1);}
    private TextView text(LinearLayout parent,String value,int size){TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);view.setTextColor(size>=21?0xff43ddd0:0xffe2edf2);if(size>=21)view.setTypeface(android.graphics.Typeface.DEFAULT,1);view.setPadding(0,16,0,16);parent.addView(view);return view;}
}
