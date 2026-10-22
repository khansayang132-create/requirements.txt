package com.taikatranslator.config;

import com.taikatranslator.retry.RetryPolicy;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Duration;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;

/**
 * Effective, validated configuration. Built only by {@link ConfigLoader}.
 *
 * <p>{@link #describe()} is safe to log and to put in the processing report.
 * {@link #fingerprint()} hashes every setting that changes the output (not
 * secrets, not timeouts) so checkpoints from a different configuration are
 * never reused.
 */
public record AppConfig(
        URI azureEndpoint,
        Optional<Secret> azureKey,
        String azureApiVersion,
        URI deeplBaseUrl,
        Optional<Secret> deeplKey,
        Optional<String> formality,
        Optional<String> glossaryId,
        Duration connectTimeout,
        Duration requestTimeout,
        Duration analysisDeadline,
        Duration pollInterval,
        RetryPolicy retryPolicy,
        Limits limits,
        boolean keepTemp) {

    /** TSK-6.7 limits, all enforced before any paid call. */
    public record Limits(long maxFileBytes, int maxPages, long maxCharacters, int maxBlocks) {
        public Limits {
            if (maxFileBytes <= 0 || maxPages <= 0 || maxCharacters <= 0 || maxBlocks <= 0)
                throw new IllegalArgumentException("limits must be positive");
        }
    }

    public Map<String, String> describe() {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("azure.endpoint", azureEndpoint.toString());
        m.put("azure.key", azureKey.isPresent() ? "[set]" : "[missing]");
        m.put("azure.apiVersion", azureApiVersion);
        m.put("deepl.baseUrl", deeplBaseUrl.toString());
        m.put("deepl.key", deeplKey.isPresent() ? "[set]" : "[missing]");
        m.put("deepl.formality", formality.orElse("default"));
        m.put("deepl.glossaryId", glossaryId.orElse("none"));
        m.put("http.connectTimeout", connectTimeout.toString());
        m.put("http.requestTimeout", requestTimeout.toString());
        m.put("azure.analysisDeadline", analysisDeadline.toString());
        m.put("azure.pollInterval", pollInterval.toString());
        m.put("retry.maxAttempts", Integer.toString(retryPolicy.maxAttempts()));
        m.put("retry.baseDelay", retryPolicy.baseDelay().toString());
        m.put("retry.maxDelay", retryPolicy.maxDelay().toString());
        m.put("retry.budget", retryPolicy.deadline().toString());
        m.put("limits.maxFileBytes", Long.toString(limits.maxFileBytes()));
        m.put("limits.maxPages", Integer.toString(limits.maxPages()));
        m.put("limits.maxCharacters", Long.toString(limits.maxCharacters()));
        m.put("limits.maxBlocks", Integer.toString(limits.maxBlocks()));
        m.put("keepTemp", Boolean.toString(keepTemp));
        return m;
    }

    /** SHA-256 over output-affecting settings only. */
    public String fingerprint() {
        String material = String.join("\n",
                "azure.apiVersion=" + azureApiVersion,
                "deepl.formality=" + formality.orElse(""),
                "deepl.glossaryId=" + glossaryId.orElse(""));
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
