package com.taikatranslator.retry;

/**
 * Why an external call failed. Retry decisions are made on the category, never
 * on exception class names or message text.
 */
public enum ErrorCategory {
    /** Connection refused/reset, DNS, TLS handshake: the request may not have arrived. */
    TRANSPORT(true),
    /** Read or request timeout: the request may have been processed. */
    TIMEOUT(true),
    /** HTTP 429. Honour Retry-After. */
    RATE_LIMITED(true),
    /** HTTP 5xx (500, 502, 503, 504...). */
    SERVER(true),
    /** DeepL 456: character quota used up. Waiting won't help. */
    QUOTA_EXCEEDED(false),
    /** HTTP 401/403: bad or missing key. */
    AUTHENTICATION(false),
    /** Other 4xx: the request itself is wrong. */
    CLIENT(false),
    /** Response arrived but couldn't be parsed or broke the contract. */
    INVALID_RESPONSE(false);

    private final boolean retryable;

    ErrorCategory(boolean retryable) {
        this.retryable = retryable;
    }

    public boolean retryable() {
        return retryable;
    }

    /** Maps an HTTP status to a category. Only call this for non-2xx statuses. */
    public static ErrorCategory fromHttpStatus(int status) {
        if (status == 429) return RATE_LIMITED;
        if (status == 456) return QUOTA_EXCEEDED;
        if (status == 401 || status == 403) return AUTHENTICATION;
        if (status == 408) return TIMEOUT;
        if (status >= 500 && status <= 599) return SERVER;
        if (status >= 400 && status <= 499) return CLIENT;
        throw new IllegalArgumentException("Not an error status: " + status);
    }
}
