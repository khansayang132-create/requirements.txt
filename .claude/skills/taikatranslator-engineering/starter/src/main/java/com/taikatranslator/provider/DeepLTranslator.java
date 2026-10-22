package com.taikatranslator.provider;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.taikatranslator.retry.ErrorCategory;
import com.taikatranslator.retry.ProviderException;
import com.taikatranslator.retry.RetryExecutor;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/**
 * DeepL /v2/translate with JSON bodies.
 *
 * <ul>
 *   <li>Base URL: {@code https://api.deepl.com} (Pro) or {@code https://api-free.deepl.com}
 *       (Free keys end in {@code :fx}). Tests point it at a local stub.</li>
 *   <li>Auth header {@code Authorization: DeepL-Auth-Key <key>}. Never logged.</li>
 *   <li>Batches at most {@link #MAX_TEXTS} texts and {@link #MAX_BODY_BYTES} bytes
 *       (DeepL caps a request body at 128 KiB); order is preserved.</li>
 *   <li>456 (quota exceeded) is permanent: no retry.</li>
 *   <li>Translation has no side effects besides billing, so it is treated as
 *       idempotent; a retry after a timeout can bill the characters twice.</li>
 * </ul>
 */
public final class DeepLTranslator implements Translator {
    public static final int MAX_TEXTS = 50;
    public static final int MAX_BODY_BYTES = 120 * 1024; // headroom under the 128 KiB limit
    private static final String PROVIDER = "deepl";

    private final HttpClient client;
    private final URI endpoint;
    private final String authKey;
    private final RetryExecutor retry;
    private final Duration requestTimeout;
    private final ObjectMapper json = new ObjectMapper();

    public DeepLTranslator(HttpClient client, URI baseUrl, String authKey, RetryExecutor retry, Duration requestTimeout) {
        this.client = Objects.requireNonNull(client);
        this.endpoint = baseUrl.resolve("/v2/translate");
        if (authKey == null || authKey.isBlank()) throw new IllegalArgumentException("DeepL auth key is not configured");
        this.authKey = authKey;
        this.retry = Objects.requireNonNull(retry);
        this.requestTimeout = Objects.requireNonNull(requestTimeout);
    }

    @Override
    public Response translate(Request request) throws ProviderException, InterruptedException {
        List<String> out = new ArrayList<>(request.texts().size());
        Optional<String> detected = Optional.empty();
        int retries = 0;
        for (List<String> batch : batches(request.texts())) {
            byte[] body = body(batch, request);
            RetryExecutor.Outcome<JsonNode> o = retry.execute("deepl.translate", true, () -> call(body));
            retries += o.attempts() - 1;
            JsonNode translations = o.value().path("translations");
            if (!translations.isArray() || translations.size() != batch.size())
                throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE,
                        "expected " + batch.size() + " translations, got " + translations.size(), null);
            for (JsonNode t : translations) {
                JsonNode text = t.get("text");
                if (text == null || !text.isTextual())
                    throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "translation without text", null);
                out.add(text.asText());
                if (detected.isEmpty() && t.hasNonNull("detected_source_language"))
                    detected = Optional.of(t.get("detected_source_language").asText());
            }
        }
        return new Response(out, detected, retries);
    }

    private JsonNode call(byte[] body) throws ProviderException, InterruptedException {
        HttpRequest req = HttpRequest.newBuilder(endpoint)
                .timeout(requestTimeout)
                .header("Authorization", "DeepL-Auth-Key " + authKey)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();
        HttpResponse<String> resp = Http.send(client, req, PROVIDER);
        try {
            return json.readTree(resp.body());
        } catch (Exception e) {
            throw new ProviderException(PROVIDER, ErrorCategory.INVALID_RESPONSE, "response is not JSON", e);
        }
    }

    private byte[] body(List<String> texts, Request r) {
        ObjectNode n = json.createObjectNode();
        ArrayNode arr = n.putArray("text");
        texts.forEach(arr::add);
        n.put("target_lang", r.targetLang());
        r.sourceLang().ifPresent(s -> n.put("source_lang", s));
        n.put("preserve_formatting", true);
        if (r.xmlTags()) {
            n.put("tag_handling", "xml");
            n.putArray("ignore_tags").add("ph");
        }
        return n.toString().getBytes(StandardCharsets.UTF_8);
    }

    /** Splits by count and by encoded size. A single oversized text is an error, not a silent cut. */
    List<List<String>> batches(List<String> texts) throws ProviderException {
        List<List<String>> out = new ArrayList<>();
        List<String> cur = new ArrayList<>();
        int bytes = 256; // JSON envelope allowance
        for (String t : texts) {
            int size = json.valueToTree(t).toString().getBytes(StandardCharsets.UTF_8).length + 1;
            if (size + 256 > MAX_BODY_BYTES)
                throw new ProviderException(PROVIDER, ErrorCategory.CLIENT, "a single block exceeds the request size limit; split it upstream", null);
            if (!cur.isEmpty() && (cur.size() == MAX_TEXTS || bytes + size > MAX_BODY_BYTES)) {
                out.add(cur);
                cur = new ArrayList<>();
                bytes = 256;
            }
            cur.add(t);
            bytes += size;
        }
        if (!cur.isEmpty()) out.add(cur);
        return out;
    }
}
