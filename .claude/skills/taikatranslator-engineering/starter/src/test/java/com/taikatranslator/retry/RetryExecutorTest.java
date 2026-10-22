package com.taikatranslator.retry;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-5.2.4. No test sleeps: the sleeper records the waits instead. */
class RetryExecutorTest {

    private final List<Duration> waits = new ArrayList<>();
    private final Sleeper recording = waits::add;
    private final RetryPolicy policy = new RetryPolicy(4, Duration.ofMillis(100), Duration.ofSeconds(5), Duration.ofSeconds(30));

    private RetryExecutor executor(double random) {
        return new RetryExecutor(policy, recording, () -> random, RetryExecutor.RetryListener.NONE);
    }

    private static ProviderException fail(ErrorCategory c) {
        return new ProviderException("test", c, "simulated", null);
    }

    private static ProviderException http(int status, Duration retryAfter) {
        return new ProviderException("test", ErrorCategory.fromHttpStatus(status), status, retryAfter, "simulated", null);
    }

    @AfterEach
    void clearInterrupt() {
        Thread.interrupted();
    }

    @Test
    void firstAttemptSuccessDoesNotWait() throws Exception {
        var out = executor(0.5).execute("op", true, () -> "ok");
        assertEquals("ok", out.value());
        assertEquals(1, out.attempts());
        assertTrue(waits.isEmpty());
    }

    @Test
    void recoversFromServerErrorThenSucceeds() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        var out = executor(0.5).execute("op", true, () -> {
            if (calls.incrementAndGet() < 3) throw http(503, null);
            return "ok";
        });
        assertEquals(3, out.attempts());
        assertEquals(2, waits.size());
    }

    @Test
    void honoursRetryAfterOn429() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        executor(0.5).execute("op", false, () -> {
            if (calls.incrementAndGet() == 1) throw http(429, Duration.ofSeconds(2));
            return "ok";
        });
        assertEquals(List.of(Duration.ofSeconds(2)), waits);
    }

    @Test
    void retryAfterIsCappedAtMaxDelay() throws Exception {
        AtomicInteger calls = new AtomicInteger();
        executor(0.5).execute("op", true, () -> {
            if (calls.incrementAndGet() == 1) throw http(429, Duration.ofHours(1));
            return "ok";
        });
        assertEquals(List.of(Duration.ofSeconds(5)), waits);
    }

    @Test
    void exhaustionRethrowsLastErrorAfterMaxAttempts() {
        AtomicInteger calls = new AtomicInteger();
        ProviderException e = assertThrows(ProviderException.class, () -> executor(0.5).execute("op", true, () -> {
            calls.incrementAndGet();
            throw fail(ErrorCategory.TRANSPORT);
        }));
        assertEquals(ErrorCategory.TRANSPORT, e.category());
        assertEquals(4, calls.get());
        assertEquals(3, waits.size());
    }

    @Test
    void permanentErrorsAreNotRetried() {
        for (int status : new int[]{400, 401, 403, 404, 456}) {
            AtomicInteger calls = new AtomicInteger();
            assertThrows(ProviderException.class, () -> executor(0.5).execute("op", true, () -> {
                calls.incrementAndGet();
                throw http(status, null);
            }));
            assertEquals(1, calls.get(), "HTTP " + status + " must not be retried");
        }
        assertTrue(waits.isEmpty());
    }

    @Test
    void timeoutIsRetriedOnlyWhenIdempotent() {
        AtomicInteger calls = new AtomicInteger();
        assertThrows(ProviderException.class, () -> executor(0.5).execute("submit", false, () -> {
            calls.incrementAndGet();
            throw fail(ErrorCategory.TIMEOUT);
        }));
        assertEquals(1, calls.get(), "a timed-out non-idempotent call may have been processed");

        calls.set(0);
        assertThrows(ProviderException.class, () -> executor(0.5).execute("poll", true, () -> {
            calls.incrementAndGet();
            throw fail(ErrorCategory.TIMEOUT);
        }));
        assertEquals(4, calls.get());
    }

    @Test
    void serverErrorOnNonIdempotentCallIsNotRetried() {
        AtomicInteger calls = new AtomicInteger();
        assertThrows(ProviderException.class, () -> executor(0.5).execute("submit", false, () -> {
            calls.incrementAndGet();
            throw http(500, null);
        }));
        assertEquals(1, calls.get());
    }

    @Test
    void exponentialBackoffWithFullJitter() throws Exception {
        assertEquals(Duration.ofMillis(100), policy.backoffCeiling(1));
        assertEquals(Duration.ofMillis(200), policy.backoffCeiling(2));
        assertEquals(Duration.ofMillis(400), policy.backoffCeiling(3));
        assertEquals(Duration.ofSeconds(5), policy.backoffCeiling(40), "capped, no overflow");

        AtomicInteger calls = new AtomicInteger();
        executor(0.5).execute("op", true, () -> {
            if (calls.incrementAndGet() < 4) throw fail(ErrorCategory.SERVER);
            return "ok";
        });
        assertEquals(List.of(Duration.ofMillis(50), Duration.ofMillis(100), Duration.ofMillis(200)), waits);
    }

    @Test
    void jitterNeverExceedsCeilingAndBadRandomIsContained() throws Exception {
        RetryExecutor almostOne = executor(0.999999);
        assertTrue(almostOne.waitFor(fail(ErrorCategory.SERVER), 1).toMillis() < 100);
        RetryExecutor broken = executor(Double.NaN);
        assertEquals(Duration.ofMillis(50), broken.waitFor(fail(ErrorCategory.SERVER), 1));
    }

    @Test
    void deadlineStopsRetriesEarly() {
        RetryPolicy tight = new RetryPolicy(10, Duration.ofSeconds(1), Duration.ofSeconds(1), Duration.ofMillis(2500));
        RetryExecutor ex = new RetryExecutor(tight, recording, () -> 0.999, RetryExecutor.RetryListener.NONE);
        AtomicInteger calls = new AtomicInteger();
        assertThrows(ProviderException.class, () -> ex.execute("op", true, () -> {
            calls.incrementAndGet();
            throw fail(ErrorCategory.SERVER);
        }));
        long waited = waits.stream().mapToLong(Duration::toMillis).sum();
        assertTrue(waited <= 2500, "waited " + waited);
        assertTrue(calls.get() < 10);
    }

    @Test
    void interruptionDuringSleepPropagatesAndRestoresFlag() {
        RetryExecutor ex = new RetryExecutor(policy, d -> { throw new InterruptedException("stop"); }, () -> 0.5,
                RetryExecutor.RetryListener.NONE);
        AtomicInteger calls = new AtomicInteger();
        assertThrows(InterruptedException.class, () -> ex.execute("op", true, () -> {
            calls.incrementAndGet();
            throw fail(ErrorCategory.SERVER);
        }));
        assertEquals(1, calls.get());
        assertTrue(Thread.currentThread().isInterrupted());
    }

    @Test
    void interruptionInsideCallIsNotRetried() {
        AtomicInteger calls = new AtomicInteger();
        assertThrows(InterruptedException.class, () -> executor(0.5).execute("op", true, () -> {
            calls.incrementAndGet();
            throw new InterruptedException();
        }));
        assertEquals(1, calls.get());
        assertTrue(Thread.currentThread().isInterrupted());
    }

    @Test
    void alreadyInterruptedThreadDoesNotCallProvider() {
        Thread.currentThread().interrupt();
        AtomicInteger calls = new AtomicInteger();
        assertThrows(InterruptedException.class, () -> executor(0.5).execute("op", true, () -> calls.incrementAndGet()));
        assertEquals(0, calls.get());
    }

    @Test
    void listenerSeesEveryRetry() throws Exception {
        List<Integer> seen = new ArrayList<>();
        RetryExecutor ex = new RetryExecutor(policy, recording, () -> 0.5, (op, n, e, w) -> seen.add(n));
        AtomicInteger calls = new AtomicInteger();
        ex.execute("op", true, () -> {
            if (calls.incrementAndGet() < 3) throw fail(ErrorCategory.TRANSPORT);
            return 1;
        });
        assertEquals(List.of(1, 2), seen);
    }

    @Test
    void statusMappingCoversTheContract() {
        assertEquals(ErrorCategory.RATE_LIMITED, ErrorCategory.fromHttpStatus(429));
        assertEquals(ErrorCategory.QUOTA_EXCEEDED, ErrorCategory.fromHttpStatus(456));
        assertEquals(ErrorCategory.AUTHENTICATION, ErrorCategory.fromHttpStatus(403));
        assertEquals(ErrorCategory.TIMEOUT, ErrorCategory.fromHttpStatus(408));
        assertEquals(ErrorCategory.SERVER, ErrorCategory.fromHttpStatus(502));
        assertEquals(ErrorCategory.CLIENT, ErrorCategory.fromHttpStatus(413));
        assertThrows(IllegalArgumentException.class, () -> ErrorCategory.fromHttpStatus(200));
    }

    @Test
    void policyRejectsNonsense() {
        assertThrows(IllegalArgumentException.class, () -> new RetryPolicy(0, Duration.ZERO, Duration.ZERO, Duration.ZERO));
        assertThrows(IllegalArgumentException.class, () -> new RetryPolicy(3, Duration.ofSeconds(2), Duration.ofSeconds(1), Duration.ZERO));
        assertThrows(IllegalArgumentException.class, () -> new RetryPolicy(3, Duration.ofSeconds(-1), Duration.ofSeconds(1), Duration.ZERO));
    }
}
