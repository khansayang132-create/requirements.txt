package com.taikatranslator.provider;

import com.taikatranslator.retry.ErrorCategory;
import com.taikatranslator.retry.ProviderException;

import java.io.IOException;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.time.Duration;
import java.util.Optional;

/** Shared HTTP plumbing: one place that turns transport failures and statuses into categories. */
final class Http {
    private Http() { }

    static HttpResponse<String> send(HttpClient client, HttpRequest request, String provider)
            throws ProviderException, InterruptedException {
        HttpResponse<String> response;
        try {
            response = client.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (HttpTimeoutException e) {
            throw new ProviderException(provider, ErrorCategory.TIMEOUT, "request timed out", e);
        } catch (IOException e) {
            throw new ProviderException(provider, ErrorCategory.TRANSPORT, e.getClass().getSimpleName(), e);
        }
        int status = response.statusCode();
        if (status >= 200 && status < 300) return response;
        throw new ProviderException(provider, ErrorCategory.fromHttpStatus(status), status,
                retryAfter(response).orElse(null), "request rejected", null);
    }

    /** Retry-After in delta-seconds. HTTP-date values are ignored (backoff applies instead). */
    static Optional<Duration> retryAfter(HttpResponse<?> response) {
        return response.headers().firstValue("Retry-After").flatMap(v -> {
            try {
                long s = Long.parseLong(v.trim());
                return s >= 0 ? Optional.of(Duration.ofSeconds(s)) : Optional.empty();
            } catch (NumberFormatException e) {
                return Optional.empty();
            }
        });
    }
}
