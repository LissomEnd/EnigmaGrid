package org.enigmagrid.core;
/** Back off when idle/offline; acknowledged work can immediately request another job. */
public final class JobPacing {
 private JobPacing(){}
 public static long delayMillis(boolean acknowledged,long elapsedMillis){
  // Successful work immediately continues. Resource duty is enforced by
  // WorkControl, while HTTP rate limits and failures use transport backoff.
  // An empty queue may become eligible as soon as another volunteer finishes
  // an audit. Do not strand newly available work for thirty seconds.
  return acknowledged?0:1000;
 }
}
