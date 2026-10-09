package org.enigmagrid.android;

import android.app.Activity;
import android.widget.*;
import java.text.DateFormat;
import java.util.*;
import static org.enigmagrid.core.Canonical.object;

/** Compact public/personal dashboard. Uses only volunteer API routes. */
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
        text(results,"Refresh to load public statistics.",16);
        refresh.setOnClickListener(v->{
            final CoordinatorClient client;
            try{client=new CoordinatorClient(origin.getText().toString().trim());}catch(IllegalArgumentException e){results.removeAllViews();text(results,"Enter a valid HTTPS coordinator address.",16);return;}
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
                    if(g!=null)renderPublic(g);
                    if(failure!=null)text(results,failure,16);
                    if(p!=null)renderPersonal(p);
                    else if(pFailure!=null)text(results,pFailure,16);
                });
            },"dashboard-refresh").start();
        });
    }
    private void renderPublic(Map<String,Object> data) {
        text(results,"Grid · as of "+time(data.get("time")),14);
        text(results,"Completed "+value(data,"completed_units")+" / "+value(data,"total_units")+" units",19);
        text(results,"Verified "+value(data,"verified_units")+" · Trusted "+value(data,"accepted_trusted_units"),16);
        text(results,"Pending validations "+value(data,"pending_validations")+" · Online devices "+value(data,"online_devices"),16);
        text(results,"Campaigns · overall progress "+percent(data.get("progress_pct")),21);
        renderCampaigns(data.get("campaigns"));
        text(results,"Leaderboard · credited work",21);
        renderLeaders(data.get("leaderboard"));
        text(results,"Devices are not people. Trusted credit can precede independent verification.",14);
    }
    private void renderPersonal(Map<String,Object> data) {
        text(results,"Your contribution · as of "+time(data.get("stats_as_of")),21);
        Object raw=data.get("stats");Map<?,?> stats=raw instanceof Map?(Map<?,?>)raw:null;
        if(stats==null){text(results,"Personal statistics unavailable",16);return;}
        text(results,"Verified "+value(stats,"verified_units")+" · Trusted "+value(stats,"accepted_trusted_units")+" · Pending "+value(data,"pending_units")+" units",16);
    }
    private void renderCampaigns(Object raw) {
        if(!(raw instanceof List)){text(results,"Campaigns unavailable",16);return;}
        List<?> rows=(List<?>)raw;if(rows.isEmpty()){text(results,"No campaigns",16);return;}
        int shown=0;
        for(Object rawRow:rows){
            if(!(rawRow instanceof Map))continue;
            Map<?,?> row=(Map<?,?>)rawRow;
            text(results,value(row,"name")+" · "+value(row,"status"),16);
            if(++shown==5)break;
        }
        if(rows.size()>shown)text(results,"+"+(rows.size()-shown)+" more campaigns",14);
        // /api/public/status has only overall progress, not per-campaign progress.
    }
    private void renderLeaders(Object raw) {
        if(!(raw instanceof List)){text(results,"Leaderboard unavailable",16);return;}
        List<?> rows=(List<?>)raw;if(rows.isEmpty()){text(results,"No public contributions yet",16);return;}
        int rank=0;
        for(Object rawRow:rows){
            if(!(rawRow instanceof Map))continue;
            Map<?,?> row=(Map<?,?>)rawRow;
            text(results,""+(++rank)+". "+value(row,"display_name")+" · "+value(row,"units")+" units · "+value(row,"jobs")+" jobs",16);
            if(rank==10)break;
        }
        if(rows.size()>rank)text(results,"+"+(rows.size()-rank)+" more contributors",14);
    }
    private static String value(Map<?,?> data,String key){Object v=data.get(key);return v==null?"Unavailable":String.valueOf(v);}
    private static String percent(Object value){
        if(!(value instanceof Number))return "Unavailable";
        double n=((Number)value).doubleValue();return Double.isFinite(n)?String.format(Locale.getDefault(),"%.1f%%",n):"Unavailable";
    }
    private static String time(Object value){
        if(!(value instanceof Number))return "Unavailable";
        double seconds=((Number)value).doubleValue();
        if(!Double.isFinite(seconds)||seconds<=0||seconds>253402300799.0)return "Unavailable";
        return DateFormat.getDateTimeInstance(DateFormat.SHORT,DateFormat.SHORT).format(new Date((long)(seconds*1000)));
    }
    private TextView text(LinearLayout parent,String value,int size){TextView view=new TextView(activity);view.setText(value);view.setTextSize(size);view.setTextColor(size>=21?0xff43ddd0:0xffe2edf2);if(size>=21)view.setTypeface(android.graphics.Typeface.DEFAULT,android.graphics.Typeface.BOLD);view.setPadding(0,12,0,12);parent.addView(view);return view;}
}
