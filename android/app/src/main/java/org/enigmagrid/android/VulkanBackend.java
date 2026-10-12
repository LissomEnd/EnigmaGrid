package org.enigmagrid.android;

/** Optional native backend: absence never prevents CPU operation. */
final class VulkanBackend {
    private static final boolean loaded;
    static {boolean ok;try{System.loadLibrary("enigmagrid_gpu");ok=true;}catch(UnsatisfiedLinkError|SecurityException e){ok=false;}loaded=ok;}
    static String probe(){if(!loaded)return "Native Vulkan backend unavailable; CPU remains available";try{return probeNative();}catch(UnsatisfiedLinkError e){return "Vulkan entry point unavailable; CPU remains available";}}
    private static native String probeNative();
    static int[] rows(int[] packed,byte[] spirv){if(!loaded)throw new IllegalStateException("Native Vulkan unavailable");return rowsNative(packed,spirv);}
    private static native int[] rowsNative(int[] packed,byte[] spirv);
    static int[] solve(int[] packed,byte[] spirv){if(!loaded)throw new IllegalStateException("Native Vulkan unavailable");return solveNative(packed,spirv);}
    private static native int[] solveNative(int[] packed,byte[] spirv);
    // Experimental resident API. Service must kill its process if poisoned;
    // Binder death must invalidate every caller-side session handle.
    static int portableBegin(int[] reference,int[] state,int[] params,byte[] shader){if(!loaded)throw new IllegalStateException("Native Vulkan unavailable");return portableBeginNative(reference,state,params,shader);}
    static void portableStep(int session,int[] tape,int iterations){portableStepNative(session,tape,iterations);}
    static int[] portableFinish(int session){return portableFinishNative(session);}
    static void portableClose(int session){portableCloseNative(session);}
    static boolean portablePoisoned(){return loaded&&portablePoisonedNative();}
    private static native int portableBeginNative(int[] reference,int[] state,int[] params,byte[] shader);
    private static native void portableStepNative(int session,int[] tape,int iterations);
    private static native int[] portableFinishNative(int session);
    private static native void portableCloseNative(int session);
    private static native boolean portablePoisonedNative();
}
