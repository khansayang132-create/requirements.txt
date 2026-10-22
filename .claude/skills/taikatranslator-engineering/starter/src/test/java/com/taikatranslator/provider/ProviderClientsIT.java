package com.taikatranslator.provider;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.retry.ErrorCategory;
import com.taikatranslator.retry.ProviderException;
import com.taikatranslator.retry.RetryExecutor;
import com.taikatranslator.retry.RetryPolicy;
import com.taikatranslator.retry.Sleeper;
import org.junit.jupiter.api.Test;

import java.net.http.HttpClient;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.3: provider clients against local stubs. No network, no keys, no real sleeping. */
class ProviderClientsIT {

    private static final ObjectMapper JSON = new ObjectMapper();
    private final List<Duration> waits = new ArrayList<>();
    private final HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();

    private RetryExecutor retry() {
        return new RetryExecutor(new RetryPolicy(3, Duration.ofMillis(10), Duration.ofSeconds(5), Duration.ofSeconds(30)),
                waits::add, () -> 0.5, RetryExecutor.RetryListener.NONE);
    }

    /** Echo "translator": prefixes every text with "ES:" so tests can check order. */
    private static StubServer.Reply echo(StubServer.Recorded req) throws java.io.IOException {
        JsonNode body = JSON.readTree(req.body());
        StringBuilder sb = new StringBuilder("{\"translations\":[");
        for (int i = 0; i < body.get("text").size(); i++) {
            if (i > 0) sb.append(',');
            sb.append("{\"detected_source_language\":\"EN\",\"text\":")
              .append(JSON.writeValueAsString("ES:" + body.get("text").get(i).asText())).append('}');
        }
        return StubServer.Reply.json(200, sb.append("]}").toString());
    }

    @Test
    void deeplSendsAuthHeaderAndKeepsOrderAcrossBatches() throws Exception {
        try (StubServer s = new StubServer((req, n) -> echo(req))) {
            DeepLTranslator t = new DeepLTranslator(http, s.baseUri(), "test-key:fx", retry(), Duration.ofSeconds(5));
            List<String> texts = new ArrayList<>();
            for (int i = 0; i < 120; i++) texts.add("block " + i);
            var resp = t.translate(new Translator.Request(texts, Optional.empty(), "ES", true));

            assertEquals(120, resp.texts().size());
            for (int i = 0; i < 120; i++) assertEquals("ES:block " + i, resp.texts().get(i));
            assertEquals(Optional.of("EN"), resp.detectedSourceLang());
            assertEquals(3, s.requests.size(), "50 + 50 + 20");
            var first = s.requests.get(0);
            assertEquals("/v2/translate", first.path());
            assertEquals(List.of("DeepL-Auth-Key test-key:fx"), first.headers().get("Authorization"));
            JsonNode body = JSON.readTree(first.body());
            assertEquals("xml", body.get("tag_handling").asText());
            assertEquals("ph", body.get("ignore_tags").get(0).asText());
            assertEquals("ES", body.get("target_lang").asText());
        }
    }

    @Test
    void deeplRetries429WithRetryAfterThenSucceeds() throws Exception {
        try (StubServer s = new StubServer((req, n) -> n == 1
                ? new StubServer.Reply(429, "", Map.of("Retry-After", "2"))
                : echo(req))) {
            DeepLTranslator t = new DeepLTranslator(http, s.baseUri(), "k", retry(), Duration.ofSeconds(5));
            var resp = t.translate(new Translator.Request(List.of("hi"), Optional.empty(), "ES", false));
            assertEquals(List.of("ES:hi"), resp.texts());
            assertEquals(1, resp.retries());
            assertEquals(List.of(Duration.ofSeconds(2)), waits);
        }
    }

    @Test
    void deeplQuotaExceededIsPermanent() throws Exception {
        try (StubServer s = new StubServer((req, n) -> StubServer.Reply.json(456, "{\"message\":\"Quota exceeded\"}"))) {
            DeepLTranslator t = new DeepLTranslator(http, s.baseUri(), "secret-key-xyz:fx", retry(), Duration.ofSeconds(5));
            ProviderException e = assertThrows(ProviderException.class,
                    () -> t.translate(new Translator.Request(List.of("hi"), Optional.empty(), "ES", false)));
            assertEquals(ErrorCategory.QUOTA_EXCEEDED, e.category());
            assertEquals(1, s.requests.size());
            assertFalse(e.getMessage().contains("secret-key-xyz"), "no key in messages: " + e.getMessage());
        }
    }

    @Test
    void deeplWrongTranslationCountIsInvalidResponse() throws Exception {
        try (StubServer s = new StubServer((req, n) -> StubServer.Reply.json(200, "{\"translations\":[]}"))) {
            DeepLTranslator t = new DeepLTranslator(http, s.baseUri(), "k", retry(), Duration.ofSeconds(5));
            ProviderException e = assertThrows(ProviderException.class,
                    () -> t.translate(new Translator.Request(List.of("a", "b"), Optional.empty(), "ES", false)));
            assertEquals(ErrorCategory.INVALID_RESPONSE, e.category());
        }
    }

    @Test
    void deeplRetries503ThenGivesUp() throws Exception {
        try (StubServer s = new StubServer((req, n) -> StubServer.Reply.json(503, "{}"))) {
            DeepLTranslator t = new DeepLTranslator(http, s.baseUri(), "k", retry(), Duration.ofSeconds(5));
            ProviderException e = assertThrows(ProviderException.class,
                    () -> t.translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", false)));
            assertEquals(ErrorCategory.SERVER, e.category());
            assertEquals(3, s.requests.size());
        }
    }

    @Test
    void connectionRefusedIsTransport() throws Exception {
        java.net.URI dead;
        try (StubServer s = new StubServer((req, n) -> StubServer.Reply.json(200, "{}"))) {
            dead = s.baseUri();
        }
        DeepLTranslator t = new DeepLTranslator(http, dead, "k", retry(), Duration.ofSeconds(2));
        ProviderException e = assertThrows(ProviderException.class,
                () -> t.translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", false)));
        assertEquals(ErrorCategory.TRANSPORT, e.category());
    }

    @Test
    void deeplRejectsOversizedSingleBlockInsteadOfCuttingIt() throws Exception {
        DeepLTranslator t = new DeepLTranslator(http, java.net.URI.create("http://127.0.0.1:9"), "k", retry(), Duration.ofSeconds(1));
        ProviderException e = assertThrows(ProviderException.class, () -> t.batches(List.of("x".repeat(200_000))));
        assertEquals(ErrorCategory.CLIENT, e.category());
        // 120 KiB = 122,880 bytes: two 61,500-byte texts exceed it, so each goes alone.
        assertEquals(3, t.batches(List.of("a".repeat(61_500), "b".repeat(61_500), "c".repeat(61_500))).size(), "split by bytes");
        assertEquals(2, t.batches(List.of("a".repeat(60_000), "b".repeat(60_000), "c".repeat(60_000))).size(), "two fit together");
    }

    @Test
    void missingKeyFailsAtConstruction() {
        assertThrows(IllegalArgumentException.class,
                () -> new DeepLTranslator(http, java.net.URI.create("http://127.0.0.1"), " ", retry(), Duration.ofSeconds(1)));
    }

    /** Clock that advances when the sleeper "sleeps", so deadlines are testable instantly. */
    static final class FakeTime extends Clock implements Sleeper {
        Instant now = Instant.parse("2026-10-23T00:00:00Z");
        final List<Duration> slept = new ArrayList<>();

        @Override public ZoneId getZone() { return ZoneOffset.UTC; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return now; }
        @Override public void sleep(Duration d) { slept.add(d); now = now.plus(d); }
    }

    private static final String ANALYZE_RESULT =
            "{\"status\":\"succeeded\",\"analyzeResult\":{\"pages\":[{\"pageNumber\":1,\"width\":8.5,\"height\":11,\"unit\":\"inch\"}]}}";

    @Test
    void azureSubmitPollResult() throws Exception {
        FakeTime time = new FakeTime();
        int[] port = {0};
        try (StubServer s = new StubServer((req, n) -> {
            if (req.method().equals("POST"))
                return new StubServer.Reply(202, "", Map.of("Operation-Location", "http://127.0.0.1:" + port[0] + "/op/1?api-version=2024-11-30"));
            if (n == 2) return new StubServer.Reply(200, "{\"status\":\"running\"}", Map.of("Retry-After", "3"));
            return StubServer.Reply.json(200, ANALYZE_RESULT);
        })) {
            port[0] = s.baseUri().getPort();
            AzureLayoutClient c = new AzureLayoutClient(http, s.baseUri(), "azure-key", AzureLayoutClient.DEFAULT_API_VERSION,
                    retry(), time, time, Duration.ofSeconds(5), Duration.ofSeconds(1), Duration.ofMinutes(5));
            var a = c.analyze("%PDF-1.7".getBytes(), "application/pdf");
            assertEquals(2, a.polls());
            assertEquals(List.of(Duration.ofSeconds(3)), time.slept, "honours Retry-After between polls");
            var submit = s.requests.get(0);
            assertTrue(submit.path().startsWith("/documentintelligence/documentModels/prebuilt-layout:analyze?api-version=2024-11-30"));
            assertEquals(List.of("azure-key"), submit.headers().get("Ocp-apim-subscription-key"));
            assertEquals(List.of("application/pdf"), submit.headers().get("Content-type"));
            assertEquals(1, AzureLayoutClient.pages(a.analyzeResult()).size());
        }
    }

    @Test
    void azureSubmitIsNotRetriedOn500ButPollIs() throws Exception {
        FakeTime time = new FakeTime();
        try (StubServer s = new StubServer((req, n) -> StubServer.Reply.json(500, "{}"))) {
            AzureLayoutClient c = new AzureLayoutClient(http, s.baseUri(), "k", "2024-11-30", retry(), time, time,
                    Duration.ofSeconds(5), Duration.ofSeconds(1), Duration.ofMinutes(5));
            ProviderException e = assertThrows(ProviderException.class, () -> c.analyze(new byte[]{1}, "application/pdf"));
            assertEquals(ErrorCategory.SERVER, e.category());
            assertEquals(1, s.requests.size(), "submission creates billable work; a 500 may have created it");
        }
    }

    @Test
    void azureNeverFinishingHitsDeadline() throws Exception {
        FakeTime time = new FakeTime();
        int[] port = {0};
        try (StubServer s = new StubServer((req, n) -> req.method().equals("POST")
                ? new StubServer.Reply(202, "", Map.of("Operation-Location", "http://127.0.0.1:" + port[0] + "/op/9"))
                : StubServer.Reply.json(200, "{\"status\":\"running\"}"))) {
            port[0] = s.baseUri().getPort();
            AzureLayoutClient c = new AzureLayoutClient(http, s.baseUri(), "k", "2024-11-30", retry(), time, time,
                    Duration.ofSeconds(5), Duration.ofSeconds(10), Duration.ofSeconds(60));
            ProviderException e = assertThrows(ProviderException.class, () -> c.analyze(new byte[]{1}, "application/pdf"));
            assertEquals(ErrorCategory.TIMEOUT, e.category());
            assertTrue(s.requests.size() <= 9, "bounded polling, got " + s.requests.size());
        }
    }

    @Test
    void azureFailedAnalysisIsPermanent() throws Exception {
        FakeTime time = new FakeTime();
        int[] port = {0};
        try (StubServer s = new StubServer((req, n) -> req.method().equals("POST")
                ? new StubServer.Reply(202, "", Map.of("Operation-Location", "http://127.0.0.1:" + port[0] + "/op/2"))
                : StubServer.Reply.json(200, "{\"status\":\"failed\",\"error\":{\"code\":\"InvalidContent\"}}"))) {
            port[0] = s.baseUri().getPort();
            AzureLayoutClient c = new AzureLayoutClient(http, s.baseUri(), "k", "2024-11-30", retry(), time, time,
                    Duration.ofSeconds(5), Duration.ofSeconds(1), Duration.ofMinutes(5));
            ProviderException e = assertThrows(ProviderException.class, () -> c.analyze(new byte[]{1}, "application/pdf"));
            assertTrue(e.getMessage().contains("InvalidContent"));
            assertEquals(2, s.requests.size());
        }
    }
}
