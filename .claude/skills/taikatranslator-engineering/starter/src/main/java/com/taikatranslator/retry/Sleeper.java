package com.taikatranslator.retry;

import java.time.Duration;

/** Injectable delay so tests never sleep for real. */
@FunctionalInterface
public interface Sleeper {
    void sleep(Duration duration) throws InterruptedException;

    Sleeper SYSTEM = d -> Thread.sleep(d.toMillis());
}
