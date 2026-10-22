package com.taikatranslator.retry;

import java.time.Duration;
import java.util.Objects;

/**
 * Bounded exponential backoff with full jitter.
 *
 * <p>delay(n) = random(0, min(maxDelay, baseDelay * 2^(n-1))) for retry n (1-based).
 * A server-supplied Retry-After wins over the computed delay but is still
 * capped at maxDelay, so a hostile or buggy header can't park the job.
 *
 * @param maxAttempts total attempts including the first; 1 disables retries
 * @param baseDelay   delay scale for the first retry
 * @param maxDelay    cap for any single wait
 * @param deadline    cap for the sum of all waits for one operation
 */
public record RetryPolicy(int maxAttempts, Duration baseDelay, Duration maxDelay, Duration deadline) {

    public RetryPolicy {
        if (maxAttempts < 1) throw new IllegalArgumentException("maxAttempts must be >= 1");
        Objects.requireNonNull(baseDelay, "baseDelay");
        Objects.requireNonNull(maxDelay, "maxDelay");
        Objects.requireNonNull(deadline, "deadline");
        if (baseDelay.isNegative() || maxDelay.isNegative() || deadline.isNegative())
            throw new IllegalArgumentException("durations must not be negative");
        if (maxDelay.compareTo(baseDelay) < 0)
            throw new IllegalArgumentException("maxDelay must be >= baseDelay");
    }

    /** Sensible defaults for translation and extraction calls. */
    public static RetryPolicy defaults() {
        return new RetryPolicy(4, Duration.ofMillis(500), Duration.ofSeconds(20), Duration.ofMinutes(2));
    }

    public static RetryPolicy noRetries() {
        return new RetryPolicy(1, Duration.ZERO, Duration.ZERO, Duration.ZERO);
    }

    /** Upper bound of the jitter window for retry number {@code retry} (1-based). */
    public Duration backoffCeiling(int retry) {
        if (retry < 1) throw new IllegalArgumentException("retry is 1-based");
        long base = baseDelay.toMillis();
        int shift = Math.min(retry - 1, 30); // 2^30 * base already exceeds any sane cap
        long ceiling = base << shift;
        if (ceiling < 0 || ceiling > maxDelay.toMillis()) ceiling = maxDelay.toMillis();
        return Duration.ofMillis(ceiling);
    }
}
