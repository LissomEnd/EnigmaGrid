package org.enigmagrid.android;

import java.util.*;

public final class CpuOnlyProductionProfileChecks {
    static final long SECOND=1_000_000_000L;
    static final class Cache implements CpuOnlyProductionProfile.Cache {
        final Map<String,Integer> values=new HashMap<>();
        public Integer load(String key){return values.get(key);}
        public void save(String key,int lanes){values.put(key,lanes);}
    }
    static CpuOnlyProductionProfile.Sample at(long sec,long units,long ack,int pending,int lanes,boolean allowed,long generation){
        return new CpuOnlyProductionProfile.Sample(sec*SECOND,units,generation,"scope",ack,100,pending,64,lanes,allowed);
    }
    static void check(boolean value,String why){if(!value)throw new AssertionError(why);}
    static void fasterTwo(){
        Cache cache=new Cache();CpuOnlyProductionProfile p=new CpuOnlyProductionProfile("hardware",cache);
        check(p.observe(at(1,1,1,0,1,true,1))==0,"A1 start");
        check(p.observe(at(31,101,101,0,1,true,1))==2,"A1 to B1");
        check(p.observe(at(32,101,101,0,2,true,1))==0,"B1 start after drain");
        check(p.observe(at(62,231,231,0,2,true,1))==0,"B1 to B2");
        check(p.observe(at(92,361,361,0,2,true,1))==1,"B2 to A2");
        check(p.observe(at(93,361,361,0,1,true,1))==0,"A2 start after drain");
        check(p.observe(at(123,461,461,0,1,true,1))==2,"net gain including drain");
        check(cache.values.isEmpty(),"do not save two before final boundary");
        check(p.observe(at(124,461,461,0,2,true,1))==0&&p.done(),"final boundary");
        check(cache.values.equals(Collections.singletonMap("hardware:scope",2)),"save meaningful two-lane result");
    }
    static void aborts(){
        Cache cache=new Cache();CpuOnlyProductionProfile p=new CpuOnlyProductionProfile("hardware",cache);
        p.observe(at(1,1,1,0,1,true,1));
        check(p.observe(at(31,101,101,0,1,true,1))==2,"request B");
        p.observe(at(32,101,101,0,2,true,1));
        check(p.observe(at(40,120,120,0,2,false,1))==1,"thermal/pause abort demotes");
        check(p.observe(at(41,120,120,0,1,false,1))==0&&p.done(),"abort after drain");
        check(cache.values.isEmpty(),"no cache after protection");
        CpuOnlyProductionProfile scope=new CpuOnlyProductionProfile("hardware",cache);
        scope.observe(at(1,1,1,0,1,true,1));
        check(scope.observe(at(2,2,2,0,1,true,2))==1&&scope.done(),"scope generation change aborts and clears pending promotion");
        CpuOnlyProductionProfile backlog=new CpuOnlyProductionProfile("hardware",cache);
        backlog.observe(at(1,1,1,0,1,true,1));
        check(backlog.observe(at(31,101,90,11,1,true,1))==1&&backlog.done(),"ACK/outbox growth aborts");
        CpuOnlyProductionProfile pending=new CpuOnlyProductionProfile("hardware",cache);
        pending.observe(at(1,1,1,0,1,true,1));
        check(pending.observe(at(31,101,101,0,1,true,1))==2,"promotion requested");
        check(pending.observe(at(32,101,101,0,1,false,1))==1&&pending.done(),"unsafe promotion is cancelled before drain");
        CpuOnlyProductionProfile cached=new CpuOnlyProductionProfile("hardware",cache);
        cache.values.put("hardware:scope",2);
        check(cached.observe(at(1,1,1,0,1,true,1))==2,"cached profile requests transition");
        check(cached.observe(at(2,1,1,0,1,false,1))==1&&cached.done()&&!cached.qualifiedTwo(),"cached transition cancels on thermal guard");
    }
    static void decision(int a1,int b1,int b2,int a2,Integer expected,String why){
        Cache cache=new Cache();CpuOnlyProductionProfile p=new CpuOnlyProductionProfile("hardware",cache);
        check(p.observe(at(1,0,0,0,1,true,1))==0,why+" start");
        check(p.observe(at(31,a1,a1,0,1,true,1))==2,why+" B request");
        check(p.observe(at(32,a1,a1,0,2,true,1))==0,why+" B start");
        check(p.observe(at(62,a1+b1,a1+b1,0,2,true,1))==0,why+" B2 start");
        int throughB=a1+b1+b2;
        check(p.observe(at(92,throughB,throughB,0,2,true,1))==1,why+" A2 request");
        check(p.observe(at(93,throughB,throughB,0,1,true,1))==0,why+" A2 start");
        int total=throughB+a2;
        check(p.observe(at(123,total,total,0,1,true,1))==0&&p.done(),why+" final decision");
        check(Objects.equals(cache.values.get("hardware:scope"),expected),why+" cached choice");
    }
    static void conservativeDecisions(){
        decision(100,100,100,100,null,"tie cannot promote");
        decision(100,104,104,100,null,"under five percent cannot promote");
        decision(100,130,90,100,null,"unstable GPU-free CPU rate cannot promote");
        decision(100,90,90,100,1,"consistent slower two lanes keep one");
    }
    public static void main(String[] args){fasterTwo();aborts();conservativeDecisions();System.out.println("PASS real-work CPU A/B/B/A selection, transition cost and safety aborts");}
}
