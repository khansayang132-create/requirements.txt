package com.taikatranslator.retry;

import java.time.Duration;
import java.util.Objects;
import java.util.function.DoubleSupplier;

/**
 * Runs a provider call under a {@link RetryPolicy}.
 *
 * <ul>
 *   <li>Only {@link ErrorCategory#retryable()} failures are retried.</li>
 *   <li>A non-idempotent call is retried only for {@link ErrorCategory#TRANSPORT}
 *       before any response, and for 429 (the server rejected it unprocessed).
 *       TIMEOUT and 5xx may mean the work was done, so they are not retried.</li>
 *   <li>Interruption stops at once, restores the interrupt flag and rethrows.</li>
 *   <li>The listener sees every retry so callers can log and count them.</li>
 * </ul>
 */
public final class RetryExecutor {

    @FunctionalInterface
    public interface Call<T> {
        T run() throws ProviderException, InterruptedException;
    }

    @FunctionalInterface
    public interface RetryListener {
        void onRetry(String operation, int retry, ProviderException cause, Duration wait);

        RetryListener NONE = (op, n, e, w) -> { };
    }

    /** What happened, for the processing report. */
    public record Outcome<T>(T value, int attempts) { }

    private final RetryPolicy policy;
    private final Sleeper sleeper;
    private final DoubleSupplier random;
    private final RetryListener listener;

    public RetryExecutor(RetryPolicy policy, Sleeper sleeper, DoubleSupplier random, RetryListener listener) {
        this.policy = Objects.requireNonNull(policy);
        this.sleeper = Objects.requireNonNull(sleeper);
        this.random = Objects.requireNonNull(random);
        this.listener = Objects.requireNonNull(listener);
    }

    public RetryExecutor(RetryPolicy policy) {
        this(policy, Sleeper.SYSTEM, Math::random, RetryListener.NONE);
    }

    public <T> Outcome<T> execute(String operation, boolean idempotent, Call<T> call)
            throws ProviderException, InterruptedException {
        long waitedMillis = 0;
        for (int attempt = 1; ; attempt++) {
            if (Thread.currentThread().isInterrupted()) throw new InterruptedException(operation + " interrupted");
            try {
                return new Outcome<>(call.run(), attempt);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw e;
            } catch (ProviderException e) {
                if (!shouldRetry(e, idempotent) || attempt >= policy.maxAttempts()) throw e;
                Duration wait = waitFor(e, attempt);
                if (waitedMillis + wait.toMillis() > policy.deadline().toMillis()) throw e;
                listener.onRetry(operation, attempt, e, wait);
                try {
                    sleeper.sleep(wait);
                } catch (InterruptedException ie) {
                    Thread.currentThread().interrupt();
                    throw ie;
                }
                waitedMillis += wait.toMillis();
            }
        }
    }

    static boolean shouldRetry(ProviderException e, boolean idempotent) {
        ErrorCategory c = e.category();
        if (!c.retryable()) return false;
        if (idempotent) return true;
        return c == ErrorCategory.TRANSPORT || c == ErrorCategory.RATE_LIMITED;
    }

    Duration waitFor(ProviderException e, int retry) {
        Duration cap = policy.maxDelay();
        if (e.retryAfter().isPresent()) {
            Duration ra = e.retryAfter().get();
            if (ra.isNegative()) ra = Duration.ZERO;
            return ra.compareTo(cap) > 0 ? cap : ra;
        }
        long ceiling = policy.backoffCeiling(retry).toMillis();
        double r = random.getAsDouble();
        if (!(r >= 0.0 && r < 1.0)) r = 0.5; // defend against a bad supplier
        return Duration.ofMillis((long) Math.floor(ceiling * r));
    }
}
