package com.taikatranslator.config;

import com.taikatranslator.retry.RetryPolicy;

import java.io.IOException;
import java.io.Reader;
import java.net.URI;
import java.net.URISyntaxException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Properties;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * TSK-6.5. Precedence: CLI overrides > environment > properties file > defaults.
 *
 * <ul>
 *   <li>Secrets come only from the environment ({@code AZURE_DI_KEY}, {@code DEEPL_AUTH_KEY}).
 *       A secret-looking key in the properties file is a configuration error.</li>
 *   <li>Endpoints must be https; plain http is accepted only for 127.0.0.1/localhost (stubs).</li>
 *   <li>Every problem is collected and reported together, by setting name, never by value.</li>
 *   <li>Unknown keys in the file are errors: a typo must not silently fall back to a default.</li>
 * </ul>
 */
public final class ConfigLoader {

    public static final class ConfigException extends Exception {
        public final List<String> problems;

        ConfigException(List<String> problems) {
            super("invalid configuration:\n  - " + String.join("\n  - ", problems));
            this.problems = List.copyOf(problems);
        }
    }

    /** Settings name → environment variable name. */
    private static final Map<String, String> ENV = Map.ofEntries(
            Map.entry("azure.endpoint", "AZURE_DI_ENDPOINT"),
            Map.entry("azure.apiVersion", "AZURE_DI_API_VERSION"),
            Map.entry("deepl.baseUrl", "DEEPL_BASE_URL"),
            Map.entry("deepl.formality", "DEEPL_FORMALITY"),
            Map.entry("deepl.glossaryId", "DEEPL_GLOSSARY_ID"),
            Map.entry("http.connectTimeout", "TAIKA_CONNECT_TIMEOUT"),
            Map.entry("http.requestTimeout", "TAIKA_REQUEST_TIMEOUT"),
            Map.entry("azure.analysisDeadline", "TAIKA_ANALYSIS_DEADLINE"),
            Map.entry("azure.pollInterval", "TAIKA_POLL_INTERVAL"),
            Map.entry("retry.maxAttempts", "TAIKA_RETRY_MAX_ATTEMPTS"),
            Map.entry("retry.baseDelay", "TAIKA_RETRY_BASE_DELAY"),
            Map.entry("retry.maxDelay", "TAIKA_RETRY_MAX_DELAY"),
            Map.entry("retry.budget", "TAIKA_RETRY_BUDGET"),
            Map.entry("limits.maxFileBytes", "TAIKA_MAX_FILE_BYTES"),
            Map.entry("limits.maxPages", "TAIKA_MAX_PAGES"),
            Map.entry("limits.maxCharacters", "TAIKA_MAX_CHARACTERS"),
            Map.entry("limits.maxBlocks", "TAIKA_MAX_BLOCKS"),
            Map.entry("keepTemp", "TAIKA_KEEP_TEMP"));

    private static final Map<String, String> DEFAULTS = Map.ofEntries(
            Map.entry("azure.endpoint", "https://example.cognitiveservices.azure.com"),
            Map.entry("azure.apiVersion", "2024-11-30"),
            Map.entry("deepl.baseUrl", "https://api.deepl.com"),
            Map.entry("http.connectTimeout", "PT10S"),
            Map.entry("http.requestTimeout", "PT60S"),
            Map.entry("azure.analysisDeadline", "PT10M"),
            Map.entry("azure.pollInterval", "PT1S"),
            Map.entry("retry.maxAttempts", "4"),
            Map.entry("retry.baseDelay", "PT0.5S"),
            Map.entry("retry.maxDelay", "PT20S"),
            Map.entry("retry.budget", "PT2M"),
            Map.entry("limits.maxFileBytes", Long.toString(50L * 1024 * 1024)),
            Map.entry("limits.maxPages", "200"),
            Map.entry("limits.maxCharacters", "500000"),
            Map.entry("limits.maxBlocks", "20000"),
            Map.entry("keepTemp", "false"));

    private static final Set<String> FORMALITY = Set.of("default", "more", "less", "prefer_more", "prefer_less");
    private static final Pattern SECRETISH = Pattern.compile("(?i).*(key|secret|password|token|credential).*");

    private ConfigLoader() { }

    public static AppConfig load(Map<String, String> env, Optional<Path> file, Map<String, String> overrides)
            throws ConfigException {
        List<String> problems = new ArrayList<>();
        Map<String, String> v = new HashMap<>(DEFAULTS);

        if (file.isPresent()) {
            Properties p = new Properties();
            try (Reader r = Files.newBufferedReader(file.get(), StandardCharsets.UTF_8)) {
                p.load(r);
            } catch (IOException e) {
                problems.add("cannot read config file " + file.get().getFileName());
            }
            for (String k : p.stringPropertyNames()) {
                if (SECRETISH.matcher(k).matches()) {
                    problems.add("config file contains '" + k + "'; secrets belong in environment variables, not files");
                } else if (!ENV.containsKey(k)) {
                    problems.add("unknown setting '" + k + "' in config file");
                } else {
                    v.put(k, p.getProperty(k).trim());
                }
            }
        }
        ENV.forEach((setting, var) -> {
            String val = env.get(var);
            if (val != null && !val.isBlank()) v.put(setting, val.trim());
        });
        overrides.forEach((k, val) -> {
            if (!ENV.containsKey(k)) problems.add("unknown override '" + k + "'");
            else v.put(k, val);
        });

        URI azure = uri("azure.endpoint", v, problems);
        URI deepl = uri("deepl.baseUrl", v, problems);
        Duration connect = duration("http.connectTimeout", v, problems);
        Duration request = duration("http.requestTimeout", v, problems);
        Duration deadline = duration("azure.analysisDeadline", v, problems);
        Duration poll = duration("azure.pollInterval", v, problems);
        Duration base = duration("retry.baseDelay", v, problems);
        Duration maxDelay = duration("retry.maxDelay", v, problems);
        Duration budget = duration("retry.budget", v, problems);
        int attempts = (int) number("retry.maxAttempts", v, 1, 20, problems);
        long maxFile = number("limits.maxFileBytes", v, 1, Long.MAX_VALUE, problems);
        long maxPages = number("limits.maxPages", v, 1, 100_000, problems);
        long maxChars = number("limits.maxCharacters", v, 1, Long.MAX_VALUE, problems);
        long maxBlocks = number("limits.maxBlocks", v, 1, 10_000_000, problems);
        boolean keepTemp = bool("keepTemp", v, problems);

        String formality = v.getOrDefault("deepl.formality", "default").toLowerCase(Locale.ROOT);
        if (!FORMALITY.contains(formality)) problems.add("deepl.formality must be one of " + FORMALITY);
        String apiVersion = v.get("azure.apiVersion");
        if (apiVersion == null || !apiVersion.matches("\\d{4}-\\d{2}-\\d{2}(-preview)?"))
            problems.add("azure.apiVersion must look like 2024-11-30");

        Optional<Secret> azureKey = secret(env.get("AZURE_DI_KEY"));
        Optional<Secret> deeplKey = secret(env.get("DEEPL_AUTH_KEY"));
        if (deeplKey.isPresent() && deepl != null) {
            boolean freeKey = deeplKey.get().reveal().endsWith(":fx");
            String host = deepl.getHost();
            if (freeKey && "api.deepl.com".equals(host))
                problems.add("DEEPL_AUTH_KEY is a Free key (:fx) but deepl.baseUrl is the Pro host; use https://api-free.deepl.com");
            if (!freeKey && "api-free.deepl.com".equals(host))
                problems.add("DEEPL_AUTH_KEY is a Pro key but deepl.baseUrl is the Free host; use https://api.deepl.com");
        }

        RetryPolicy retry = null;
        if (base != null && maxDelay != null && budget != null && attempts > 0) {
            try {
                retry = new RetryPolicy(attempts, base, maxDelay, budget);
            } catch (IllegalArgumentException e) {
                problems.add("retry settings: " + e.getMessage());
            }
        }
        if (!problems.isEmpty()) throw new ConfigException(problems);

        return new AppConfig(azure, azureKey, apiVersion, deepl, deeplKey,
                formality.equals("default") ? Optional.empty() : Optional.of(formality),
                Optional.ofNullable(v.get("deepl.glossaryId")).filter(s -> !s.isBlank()),
                connect, request, deadline, poll, retry,
                new AppConfig.Limits(maxFile, (int) maxPages, maxChars, (int) maxBlocks), keepTemp);
    }

    /** Fails if a stage that will run lacks its credential. Call after load, before any work. */
    public static void requireProviders(AppConfig c, boolean extraction, boolean translation) throws ConfigException {
        List<String> problems = new ArrayList<>();
        if (extraction && c.azureKey().isEmpty()) problems.add("AZURE_DI_KEY is not set");
        if (extraction && c.azureEndpoint().getHost() != null && c.azureEndpoint().getHost().equals("example.cognitiveservices.azure.com"))
            problems.add("AZURE_DI_ENDPOINT is not set");
        if (translation && c.deeplKey().isEmpty()) problems.add("DEEPL_AUTH_KEY is not set");
        if (!problems.isEmpty()) throw new ConfigException(problems);
    }

    private static Optional<Secret> secret(String v) {
        return v == null || v.isBlank() ? Optional.empty() : Optional.of(Secret.of(v.trim()));
    }

    private static URI uri(String k, Map<String, String> v, List<String> problems) {
        try {
            URI u = new URI(v.get(k));
            String scheme = u.getScheme() == null ? "" : u.getScheme().toLowerCase(Locale.ROOT);
            boolean local = "127.0.0.1".equals(u.getHost()) || "localhost".equals(u.getHost());
            if (u.getHost() == null) problems.add(k + " has no host");
            else if (!scheme.equals("https") && !(scheme.equals("http") && local))
                problems.add(k + " must use https (http only for 127.0.0.1)");
            if (u.getUserInfo() != null) problems.add(k + " must not contain credentials");
            return u;
        } catch (URISyntaxException | NullPointerException e) {
            problems.add(k + " is not a valid URL");
            return null;
        }
    }

    private static Duration duration(String k, Map<String, String> v, List<String> problems) {
        String raw = v.get(k);
        try {
            Duration d = raw.matches("\\d+") ? Duration.ofSeconds(Long.parseLong(raw)) : Duration.parse(raw);
            if (d.isZero() || d.isNegative()) {
                problems.add(k + " must be positive");
                return null;
            }
            return d;
        } catch (DateTimeParseException | NullPointerException e) {
            problems.add(k + " must be seconds or an ISO-8601 duration like PT30S");
            return null;
        }
    }

    private static long number(String k, Map<String, String> v, long min, long max, List<String> problems) {
        try {
            long n = Long.parseLong(v.get(k));
            if (n < min || n > max) {
                problems.add(k + " must be between " + min + " and " + max);
                return -1;
            }
            return n;
        } catch (NumberFormatException | NullPointerException e) {
            problems.add(k + " must be a whole number");
            return -1;
        }
    }

    private static boolean bool(String k, Map<String, String> v, List<String> problems) {
        String raw = v.get(k).toLowerCase(Locale.ROOT);
        if (raw.equals("true") || raw.equals("false")) return Boolean.parseBoolean(raw);
        problems.add(k + " must be true or false");
        return false;
    }
}
