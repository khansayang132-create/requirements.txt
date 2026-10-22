package com.taikatranslator.provider;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.retry.ErrorCategory;
import com.taikatranslator.retry.ProviderException;
import com.taikatranslator.retry.RetryExecutor;
import com.taikatranslator.retry.Sleeper;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * Azure AI Document Intelligence, prebuilt-layout, asynchronous analyze.
 *
 * <p>Three operations, three retry rules:
 * <ol>
 *   <li><b>Submit</b> POST {endpoint}/documentintelligence/documentModels/prebuilt-layout:analyze
 *       ?api-version=... → 202 + Operation-Location. Creates a billable operation, so it
 *       is non-idempotent: retried only on transport failure or 429.</li>
 *   <li><b>Poll</b> GET Operation-Location until status is succeeded/failed. Idempotent:
 *       retried on any retryable error. Waits Retry-After between polls when given.</li>
 *   <li><b>Result</b> comes in the final poll body under analyzeResult.</li>
 * </ol>
 * An overall deadline bounds the whole analysis.
 */
public final class AzureLayoutClient {
    public static final String DEFAULT_API_VERSION = "2024-11-30";
    private static final String PROVIDER = "azure-di";

    private final HttpClient client;
    private final URI endpoint;
    private final String key;
    private final String apiVersion;
    private final RetryExecutor retry;
    private final Sleeper sleeper;
    private final Clock clock;
    private final Duration requestTimeout;
    private final Duration defaultPollInterval;
    private final Duration deadline;
    private final ObjectMapper json = new ObjectMapper();

    public AzureLayoutClient(HttpClient client, URI endpoint, String key, String apiVersion, RetryExecutor retry,
                             Sleeper sleeper, Clock clock, Duration requestTimeout, Duration defaultPollInterval,
                             Duration deadline) {
        this.client = Objects.requireNonNull(client);
        this.endpoint = Objects.requireNonNull(endpoint);
        if (key == null || key.isBlank()) throw new IllegalArgumentException("Azure Document Intelligence key is not configured");
        this.key = key;
        this.apiVersion = Objects.requireNonNull(apiVersion);
        this.retry = Objects.requireNonNull(retry);
        this.sleeper = Objects.requireNonNull(sleeper);
        this.clock = Objects.requireNonNull(clock);
        this.requestTimeout = requestTimeout;
        this.defaultPollInterval = defaultPollInterval;
        this.deadline = deadline;
    }

    public record Analysis(JsonNode analyzeResult, int polls, int retries) { }

    public Analysis analyze(byte[] document, String contentType) throws ProviderException, InterruptedException {
        Instant giveUpAt = clock.instant().plus(deadline);
        URI submit = endpoint.resolve("/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=" + apiVersion);

        RetryExecutor.Outcome<URI> submitted = retry.execute("azure.submit", false, () -> {
            HttpRequest req = HttpRequest.newBuilder(submit).timeout(requestTimeout)
                    .header("Ocp-Apim-Subscription-Key", key)
                    .header("Content-Type", contentType)
                    .POST(HttpRequest.BodyPublishers.ofByteArray(document)).build();
            HttpResponse<String> resp = Http.send(client, req, PROVIDER);
            if (resp.statusCode() != 202)
                throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "expected 202 Accepted, got " + resp.statusCode(), null);
            return URI.create(resp.headers().firstValue("Operation-Location").orElseThrow(() ->
                    new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "202 without Operation-Location", null)));
        });
        int retries = submitted.attempts() - 1;
        int polls = 0;

        while (true) {
            if (clock.instant().isAfter(giveUpAt))
                throw new ProviderException(PROVIDER, ErrorCategory.TIMEOUT, "analysis exceeded deadline of " + deadline, null);
            polls++;
            RetryExecutor.Outcome<HttpResponse<String>> polled = retry.execute("azure.poll", true, () -> {
                HttpRequest req = HttpRequest.newBuilder(submitted.value()).timeout(requestTimeout)
                        .header("Ocp-Apim-Subscription-Key", key).GET().build();
                return Http.send(client, req, PROVIDER);
            });
            retries += polled.attempts() - 1;
            JsonNode body;
            try {
                body = json.readTree(polled.value().body());
            } catch (Exception e) {
                throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "poll response is not JSON", e);
            }
            String status = body.path("status").asText("");
            switch (status) {
                case "succeeded" -> {
                    JsonNode result = body.get("analyzeResult");
                    if (result == null || !result.has("pages"))
                        throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "succeeded without analyzeResult.pages", null);
                    return new Analysis(result, polls, retries);
                }
                case "failed", "canceled" -> throw new ProviderException(PROVIDER, ErrorCategory.CLIENT,
                        "analysis " + status + ": " + body.path("error").path("code").asText("unknown"), null);
                case "notStarted", "running" -> sleeper.sleep(Http.retryAfter(polled.value()).orElse(defaultPollInterval));
                default -> throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "unknown status '" + status + "'", null);
            }
        }
    }

    /** Page metadata from analyzeResult.pages. Azure's "angle" is text skew, not page rotation, so rotation is 0 here. */
    public static List<PageInfo> pages(JsonNode analyzeResult) {
        List<PageInfo> out = new ArrayList<>();
        for (JsonNode p : analyzeResult.path("pages")) {
            out.add(new PageInfo(p.path("pageNumber").asInt(), p.path("width").asDouble(Double.NaN),
                    p.path("height").asDouble(Double.NaN), PageInfo.Unit.fromAzure(p.path("unit").asText(null)), 0));
        }
        return out;
    }

    /** Azure polygons are flat arrays [x1,y1,x2,y2,...] in the page unit. */
    public static double[] polygon(JsonNode boundingRegion) {
        JsonNode poly = boundingRegion.path("polygon");
        double[] out = new double[poly.size()];
        for (int i = 0; i < out.length; i++) out[i] = poly.get(i).asDouble(Double.NaN);
        return out;
    }
}
