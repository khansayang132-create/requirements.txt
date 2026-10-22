package com.taikatranslator.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.provider.Translator;
import com.taikatranslator.retry.ProviderException;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * Block-level translation checkpoint (TSK-6.8): a {@link Translator} decorator
 * that only sends texts it hasn't translated before for the same target
 * language and config fingerprint. A resumed run after a crash at block 900
 * pays only for blocks 901+.
 *
 * <p>Stored as JSON lines, appended and flushed after each provider response,
 * so a crash loses at most the batch in flight. A torn last line is skipped
 * on load. Keys are SHA-256 of (fingerprint, target, source, text), so the
 * cache file holds translations but no source text.
 */
public final class TranslationCache implements Translator {

    private final Translator delegate;
    private final Path file;
    private final String fingerprint;
    private final Map<String, String> entries = new HashMap<>();
    private final ObjectMapper json = new ObjectMapper();
    private int hits;
    private int skippedLines;

    public TranslationCache(Translator delegate, Path file, String configFingerprint) throws IOException {
        this.delegate = delegate;
        this.file = file;
        this.fingerprint = configFingerprint;
        if (Files.exists(file)) {
            for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
                if (line.isBlank()) continue;
                try {
                    JsonNode n = json.readTree(line);
                    entries.put(n.get("k").asText(), n.get("v").asText());
                } catch (Exception e) {
                    skippedLines++;
                }
            }
        }
    }

    public int hits() { return hits; }
    public int skippedLines() { return skippedLines; }

    @Override
    public Response translate(Request request) throws ProviderException, InterruptedException {
        List<String> keys = new ArrayList<>();
        List<String> missing = new ArrayList<>();
        for (String t : request.texts()) {
            String k = key(request, t);
            keys.add(k);
            if (!entries.containsKey(k) && !missing.contains(t)) missing.add(t);
        }
        int retries = 0;
        Optional<String> detected = Optional.empty();
        if (!missing.isEmpty()) {
            Response r = delegate.translate(new Request(missing, request.sourceLang(), request.targetLang(), request.xmlTags()));
            if (r.texts().size() != missing.size())
                throw new ProviderException("cache", com.taikatranslator.retry.ErrorCategory.INVALID_RESPONSE,
                        "translator returned " + r.texts().size() + " texts for " + missing.size(), null);
            retries = r.retries();
            detected = r.detectedSourceLang();
            try (BufferedWriter w = Files.newBufferedWriter(file, StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
                for (int i = 0; i < missing.size(); i++) {
                    String k = key(request, missing.get(i));
                    entries.put(k, r.texts().get(i));
                    w.write(json.writeValueAsString(Map.of("k", k, "v", r.texts().get(i))));
                    w.newLine();
                }
            } catch (IOException e) {
                // The translations are still returned; only resumability is lost. Surface it, don't hide it.
                throw new IllegalStateException("translation cache not writable: " + file.getFileName(), e);
            }
        }
        List<String> out = new ArrayList<>(keys.size());
        for (String k : keys) out.add(entries.get(k));
        hits += request.texts().size() - missing.size();
        return new Response(out, detected, retries);
    }

    private String key(Request r, String text) {
        String material = fingerprint + "\u0000" + r.targetLang() + "\u0000" + r.sourceLang().orElse("") + "\u0000"
                + r.xmlTags() + "\u0000" + text;
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(material.getBytes(StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(d);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
