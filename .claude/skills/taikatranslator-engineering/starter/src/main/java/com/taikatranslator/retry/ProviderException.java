package com.taikatranslator.retry;

import java.time.Duration;
import java.util.Optional;

/**
 * A classified failure from an external provider (Azure, DeepL, vision).
 * The message must never contain keys, auth headers or document text.
 */
public class ProviderException extends Exception {
    private final String provider;
    private final ErrorCategory category;
    private final int httpStatus;
    private final Duration retryAfter;

    public ProviderException(String provider, ErrorCategory category, int httpStatus,
                             Duration retryAfter, String message, Throwable cause) {
        super(provider + " " + category + (httpStatus > 0 ? " (HTTP " + httpStatus + ")" : "") + ": " + message, cause);
        this.provider = provider;
        this.category = category;
        this.httpStatus = httpStatus;
        this.retryAfter = retryAfter;
    }

    public ProviderException(String provider, ErrorCategory category, String message, Throwable cause) {
        this(provider, category, 0, null, message, cause);
    }

    public String provider() { return provider; }
    public ErrorCategory category() { return category; }
    /** 0 when the failure wasn't an HTTP response. */
    public int httpStatus() { return httpStatus; }
    public Optional<Duration> retryAfter() { return Optional.ofNullable(retryAfter); }
}
