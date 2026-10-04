package org.enigmagrid.core;
/** Back off when idle/offline; acknowledged work can immediately request another job. */
public final class JobPacing {
 private JobPacing(){}
 public static long delayMillis(boolean acknowledged,long elapsedMillis){
  // Cap short transactions at one per second to avoid flooding the coordinator.
  return acknowledged?Math.max(0,1000-Math.max(0,elapsedMillis)):30000;
 }
}
