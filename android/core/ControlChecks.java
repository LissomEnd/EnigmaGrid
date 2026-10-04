import org.enigmagrid.core.WorkControl;
public class ControlChecks {
    static class Clock implements WorkControl.Timing {
        long now,slept;Runnable onSleep=()->{};
        public long nanos(){return now;}
        public void sleep(long ms){now+=ms*1000000;slept+=ms;onSleep.run();}
    }
    public static void main(String[] args) {
        Clock clock=new Clock();WorkControl control=new WorkControl(clock,()->null);
        if(control.getAsBoolean())throw new AssertionError();clock.now+=20000000;
        control.getAsBoolean();if(clock.slept!=60)throw new AssertionError("25% duty");
        control.pause();clock.onSleep=control::resume;control.getAsBoolean();if(clock.slept!=160)throw new AssertionError("pause");
        control.setPercent(100);clock.now+=20000000;control.getAsBoolean();if(clock.slept!=160)throw new AssertionError("100% duty");
        control.stop();if(!control.getAsBoolean())throw new AssertionError("stop");
        Clock blockedClock=new Clock();WorkControl blocked=new WorkControl(blockedClock,()->"Cooling down");blockedClock.onSleep=blocked::stop;
        if(!blocked.getAsBoolean()||blockedClock.slept!=100)throw new AssertionError("stop during resource wait");
        Clock memoryClock=new Clock();boolean[] lowMemory={true};int[] waits={0};
        WorkControl memoryControl=new WorkControl(memoryClock,()->lowMemory[0]?"Waiting for available memory":null);
        memoryClock.onSleep=()->{
            if(!"Waiting for available memory".equals(memoryControl.status()))throw new AssertionError("memory wait status");
            if(++waits[0]==3)lowMemory[0]=false;
        };
        if(memoryControl.getAsBoolean()||memoryClock.slept!=300||!"computing".equals(memoryControl.status()))throw new AssertionError("memory recovery");
        lowMemory[0]=true;memoryClock.onSleep=memoryControl::stop;
        if(!memoryControl.getAsBoolean()||memoryClock.slept!=400)throw new AssertionError("stop during memory pressure");
        try{control.setPercent(0);throw new AssertionError("Invalid duty accepted");}catch(IllegalArgumentException expected){}
        System.out.println("PASS: duty cycle, pause/resume, stop, restricted wait, memory recovery and stop, invalid duty");
    }
}
