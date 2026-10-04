package org.enigmagrid.core;

/** Android release versions are three nonnegative numeric components. */
public final class UpdatePolicy {
    private UpdatePolicy() {}
    public enum State { CURRENT, OPTIONAL, REQUIRED, REQUIRED_UNAVAILABLE }
    public static String androidMinimum(java.util.Map<String,Object> config) {
        String key=config.containsKey("min_android_worker_version")?"min_android_worker_version":"min_worker_version";
        Object value=config.get(key);
        if(!(value instanceof String))throw new IllegalArgumentException("Missing or invalid Android minimum version");
        String minimum=(String)value;
        if(!minimum.isEmpty())parse(minimum);
        return minimum;
    }
    public static int compare(String a,String b) {
        int[] left=parse(a),right=parse(b);
        for(int i=0;i<3;i++){int result=Integer.compare(left[i],right[i]);if(result!=0)return result;}
        return 0;
    }
    private static int[] parse(String text) {
        if(text==null||!text.matches("(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})\\.(0|[1-9][0-9]{0,8})"))throw new IllegalArgumentException("Invalid release version");
        String[] parts=text.split("\\.");return new int[]{Integer.parseInt(parts[0]),Integer.parseInt(parts[1]),Integer.parseInt(parts[2])};
    }
    public static State evaluate(String installed,String minimum,String available) {
        parse(installed);
        boolean required=minimum!=null&&!minimum.isEmpty()&&compare(installed,minimum)<0;
        boolean newer=available!=null&&compare(available,installed)>0;
        if(required)return newer&&compare(available,minimum)>=0?State.REQUIRED:State.REQUIRED_UNAVAILABLE;
        return newer?State.OPTIONAL:State.CURRENT;
    }
}
