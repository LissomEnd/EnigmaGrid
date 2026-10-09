package org.enigmagrid.core;

/** A safety interruption is not evidence of a numerical/backend failure. */
public final class QualificationProtection extends RuntimeException {
    public QualificationProtection(String reason){super("Device protection: "+reason);}
    public static boolean interrupted(Throwable error) {
        // Only unwrap execution wrappers, never classify an arbitrary backend
        // failure by matching its message or an unrelated nested exception.
        while(error instanceof java.util.concurrent.ExecutionException ||
              error instanceof java.util.concurrent.CompletionException)error=error.getCause();
        return error instanceof QualificationProtection;
    }
}
