package org.enigmagrid.android;

import android.content.Context;
import android.graphics.*;
import android.view.View;
import java.util.Arrays;
import java.util.Locale;

/** Dependency-free rolling telemetry chart with a two-minute history. */
final class TelemetryChartView extends View {
    static final int PERCENT=0, TEMPERATURE=1, RATE=2;
    private final float[] first=new float[120],second=new float[120];
    private int count,cursor;
    private final int mode;
    private final String firstName,secondName;
    private final Paint grid=new Paint(Paint.ANTI_ALIAS_FLAG),aPaint=new Paint(Paint.ANTI_ALIAS_FLAG),
        bPaint=new Paint(Paint.ANTI_ALIAS_FLAG),text=new Paint(Paint.ANTI_ALIAS_FLAG),strongText=new Paint(Paint.ANTI_ALIAS_FLAG);

    TelemetryChartView(Context context,boolean temperature){
        this(context,temperature?TEMPERATURE:PERCENT,"CPU","GPU");
    }
    TelemetryChartView(Context context,int mode,String firstName,String secondName){
        super(context);this.mode=mode;this.firstName=firstName;this.secondName=secondName;
        Arrays.fill(first,Float.NaN);Arrays.fill(second,Float.NaN);
        grid.setColor(Color.rgb(43,66,84));grid.setStrokeWidth(dp(1));
        aPaint.setColor(Color.rgb(76,220,208));aPaint.setStrokeWidth(dp(2.4f));aPaint.setStyle(Paint.Style.STROKE);
        aPaint.setStrokeCap(Paint.Cap.ROUND);aPaint.setStrokeJoin(Paint.Join.ROUND);
        bPaint.setColor(Color.rgb(255,184,92));bPaint.setStrokeWidth(dp(2.4f));bPaint.setStyle(Paint.Style.STROKE);
        bPaint.setStrokeCap(Paint.Cap.ROUND);bPaint.setStrokeJoin(Paint.Join.ROUND);
        // A work-block unit is currently one job, so both rate series often
        // coincide exactly. Dashed Jobs leaves the solid Units trace visible.
        if(mode==RATE)bPaint.setPathEffect(new DashPathEffect(new float[]{dp(6),dp(4)},0));
        text.setColor(Color.rgb(150,174,191));text.setTextSize(dp(10));
        strongText.setColor(Color.rgb(218,231,239));strongText.setTextSize(dp(11));strongText.setTypeface(Typeface.DEFAULT_BOLD);
        setMinimumHeight((int)dp(210));
    }
    void add(float a,float b){first[cursor]=a;second[cursor]=b;cursor=(cursor+1)%first.length;count=Math.min(count+1,first.length);invalidate();}
    @Override protected void onMeasure(int width,int height){setMeasuredDimension(MeasureSpec.getSize(width),resolveSize((int)dp(210),height));}
    @Override protected void onDraw(Canvas c){
        super.onDraw(c);
        float w=getWidth(),h=getHeight(),left=dp(44),right=dp(12),top=dp(54),bottom=dp(28);
        c.drawColor(Color.rgb(10,27,39));
        float min=mode==TEMPERATURE?20f:0f,max=mode==TEMPERATURE?100f:(mode==PERCENT?100f:rateMax());
        for(int i=0;i<=4;i++){
            float y=top+(h-top-bottom)*i/4f;c.drawLine(left,y,w-right,y,grid);
            float value=max-(max-min)*i/4f;c.drawText(axis(value),dp(4),y+dp(4),text);
        }
        for(int i=0;i<=4;i++){float x=left+(w-left-right)*i/4f;c.drawLine(x,top,x,h-bottom,grid);}
        drawSeries(c,first,aPaint,min,max,left,right,top,bottom,w,h);
        drawSeries(c,second,bPaint,min,max,left,right,top,bottom,w,h);
        drawLegend(c,firstName+" "+latest(first),aPaint,left,dp(18));
        if(secondName!=null&&!secondName.isEmpty())drawLegend(c,secondName+" "+latest(second),bPaint,left+(w-left-right)/2,dp(18));
        c.drawText(secondName==null||secondName.isEmpty()?"Dotted: sample unavailable":mode==RATE?"Solid: Units · dashed: Jobs":"Dotted: sensor reading unavailable",left,dp(36),text);
        c.drawText("-2 min",left,h-dp(7),text);c.drawText("now",w-right-dp(20),h-dp(7),text);
    }
    private void drawLegend(Canvas c,String label,Paint series,float x,float y){
        Paint marker=new Paint(series);marker.setStyle(Paint.Style.FILL);
        c.drawCircle(x+dp(4),y-dp(4),dp(4),marker);
        c.drawText(label,x+dp(13),y,strongText);
    }
    private float rateMax(){
        float peak=0f;
        for(int i=0;i<count;i++){int idx=(cursor-count+i+first.length)%first.length;peak=maxFinite(peak,first[idx]);peak=maxFinite(peak,second[idx]);}
        if(peak<=0)return 1f;
        float limit=1f;while(limit<peak*1.15f)limit*=2f;return limit;
    }
    private float maxFinite(float current,float value){return Float.isFinite(value)?Math.max(current,value):current;}
    private String axis(float value){
        if(mode==TEMPERATURE)return String.format(Locale.ROOT,"%.0f°",value);
        if(mode==PERCENT)return String.format(Locale.ROOT,"%.0f%%",value);
        return value>=100?String.format(Locale.ROOT,"%.0f",value):value>=10?String.format(Locale.ROOT,"%.1f",value):String.format(Locale.ROOT,"%.2f",value);
    }
    private String latest(float[] data){
        if(count==0)return "—";
        int idx=(cursor-1+data.length)%data.length;float value=data[idx];
        if(!Float.isFinite(value))return "n/a";
        if(mode==TEMPERATURE)return String.format(Locale.ROOT,"%.1f°C",value);
        if(mode==PERCENT)return String.format(Locale.ROOT,"%.1f%%",value);
        return String.format(Locale.ROOT,value>=10?"%.1f/s":"%.3f/s",value);
    }
    private void drawSeries(Canvas c,float[] data,Paint paint,float min,float max,float left,float right,float top,float bottom,float w,float h){
        if(count==0)return;Path path=new Path();boolean started=false,known=false;float lastX=0,lastY=0;
        Paint missing=new Paint(paint);missing.setAlpha(110);missing.setPathEffect(new DashPathEffect(new float[]{dp(3),dp(4)},0));
        for(int i=0;i<count;i++){
            int idx=(cursor-count+i+data.length)%data.length;float v=data[idx];
            if(!Float.isFinite(v)){started=false;continue;}
            float x=left+(w-left-right)*(data.length-count+i)/(data.length-1);
            float y=h-bottom-(h-top-bottom)*(Math.max(min,Math.min(max,v))-min)/Math.max(.0001f,max-min);
            if(!started){
                if(known)c.drawLine(lastX,lastY,x,y,missing);
                path.moveTo(x,y);started=true;
            }else path.lineTo(x,y);
            known=true;lastX=x;lastY=y;
        }
        c.drawPath(path,paint);
        if(known&&!started)c.drawLine(lastX,lastY,w-right,lastY,missing);
        if(started)c.drawCircle(lastX,lastY,dp(3),paint);
    }
    private float dp(float value){return value*getResources().getDisplayMetrics().density;}
}
