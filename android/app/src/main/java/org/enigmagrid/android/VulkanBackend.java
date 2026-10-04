package org.enigmagrid.android;

/** Optional native backend: absence never prevents CPU operation. */
final class VulkanBackend {
    private static final boolean loaded;
    static {boolean ok;try{System.loadLibrary("enigmagrid_gpu");ok=true;}catch(UnsatisfiedLinkError|SecurityException e){ok=false;}loaded=ok;}
    static String probe(){if(!loaded)return "Native Vulkan backend unavailable; CPU remains available";try{return probeNative();}catch(UnsatisfiedLinkError e){return "Vulkan entry point unavailable; CPU remains available";}}
    private static native String probeNative();
    static int[] rows(int[] packed,byte[] spirv){if(!loaded)throw new IllegalStateException("Native Vulkan unavailable");return rowsNative(packed,spirv);}
    private static native int[] rowsNative(int[] packed,byte[] spirv);
}
