package org.enigmagrid.android;

/** Bounded A/B/B/A over real, durably saved grid receipts. No fixture work. */
final class CpuOnlyProductionProfile {
    interface Cache {Integer load(String key);void save(String key,int lanes);}
    static final class Sample {
        final long nanos,durable,scopeGeneration,acked;
        final String scope;final int ready,pending,capacity,lanes;final boolean allowed;
        Sample(long nanos,long durable,long scopeGeneration,String scope,long acked,int ready,int pending,int capacity,int lanes,boolean allowed){
            this.nanos=nanos;this.durable=durable;this.scopeGeneration=scopeGeneration;this.scope=scope;
            this.acked=acked;this.ready=ready;this.pending=pending;this.capacity=capacity;this.lanes=lanes;this.allowed=allowed;
        }
    }
    private static final int[] MODES={1,2,2,1};
    private static final long WINDOW_NS=30_000_000_000L,MAX_TRANSITION_NS=15_000_000_000L;
    private final Cache cache;private final String prefix;
    private int window=-1,target=1;private boolean switching,done,aborting,loadedCache,selectedTwo;
    private String scope,key;private long generation,started,transitionStarted,transitionNanos,promoteNanos;
    private long startUnits,startAck;private int startPending;
    private final double[] rates=new double[4];
    CpuOnlyProductionProfile(String prefix,Cache cache){this.prefix=prefix;this.cache=cache;}
    boolean done(){return done;}
    boolean qualifiedTwo(){return done&&!aborting&&(selectedTwo||loadedCache&&target==2);}
    CpuOnlyProductionProfile nextSession(){return new CpuOnlyProductionProfile(prefix,cache);}
    private static boolean eligible(Sample s){
        return s.allowed&&s.scope!=null&&!"unknown".equals(s.scope)&&s.ready>=2
            &&s.capacity>=16&&s.pending<s.capacity-8;
    }
    private void begin(Sample s){
        started=s.nanos;startUnits=s.durable;startAck=s.acked;startPending=s.pending;
    }
    private int abort(Sample s){
        aborting=true;
        // Also cancel a pending 1->2 request that has not yet drained.
        if(s.lanes==1){target=1;switching=false;done=true;return 1;}
        target=1;switching=true;transitionStarted=s.nanos;return 1;
    }
    private static boolean stable(double a,double b){return a>0&&b>0&&Math.abs(a-b)/Math.max(a,b)<=.08;}
    private int select(){
        if(!stable(rates[0],rates[3])||!stable(rates[1],rates[2]))return 0;
        double a=(rates[0]+rates[3])/2,b=(rates[1]+rates[2])/2;
        if(rates[1]>rates[0]*1.05&&rates[2]>rates[3]*1.05&&b>a*1.05){
            // Transition time is real lost opportunity, even though it is
            // excluded from the steady 30-second window rate denominator.
            double gainUnits=(b-a)*60;
            double costUnits=a*(transitionNanos+promoteNanos)/1e9;
            if(gainUnits>costUnits+a*60*.05)return 2;
        }
        if(rates[0]>rates[1]*1.05&&rates[3]>rates[2]*1.05&&a>b*1.05)return 1;
        return 0;
    }
    /** Returns 0 to keep lanes, or 1/2 to request a boundary-safe transition. */
    int observe(Sample s){
        if(done)return 0;
        if(aborting){
            if(s.lanes==1){done=true;return 0;}
            return 1;
        }
        if(switching){
            if(!eligible(s)||!scope.equals(s.scope)||generation!=s.scopeGeneration)return abort(s);
            if(s.nanos-transitionStarted>MAX_TRANSITION_NS)return abort(s);
            if(s.lanes!=target)return target;
            long delay=s.nanos-transitionStarted;
            transitionNanos+=delay;if(target==2)promoteNanos=delay;
            switching=false;
            if(loadedCache||selectedTwo){
                if(selectedTwo)cache.save(key,2);
                done=true;return 0;
            }
            begin(s);
            return 0;
        }
        if(window<0){
            if(s.lanes!=1||!eligible(s))return 0;
            scope=s.scope;generation=s.scopeGeneration;key=prefix+":"+scope;
            Integer saved=cache.load(key);
            if(saved!=null&&(saved==1||saved==2)){
                loadedCache=true;
                if(saved==1){done=true;return 0;}
                target=2;switching=true;transitionStarted=s.nanos;return 2;
            }
            window=0;begin(s);return 0;
        }
        if(!eligible(s)||!scope.equals(s.scope)||generation!=s.scopeGeneration||s.lanes!=MODES[window])return abort(s);
        if(s.nanos-started<WINDOW_NS)return 0;
        long units=s.durable-startUnits,acks=s.acked-startAck,elapsed=s.nanos-started;
        if(units<20||acks<units-8||s.pending-startPending>8)return abort(s);
        rates[window]=units*1e9/elapsed;
        if(window==MODES.length-1){
            int selected=select();
            if(selected==2){
                // The final transition cost was estimated by the measured
                // first promotion, and the selected profile is saved only
                // after this new transition actually drains and applies.
                target=2;switching=true;transitionStarted=s.nanos;selectedTwo=true;return 2;
            }
            if(selected==1)cache.save(key,1);
            done=true;return 0;
        }
        window++;
        if(MODES[window]==s.lanes){begin(s);return 0;}
        target=MODES[window];switching=true;transitionStarted=s.nanos;return target;
    }
}
