package com.taikatranslator.config;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.5. */
class ConfigLoaderTest {

    @TempDir
    Path dir;

    private static ConfigLoader.ConfigException fails(Map<String, String> env, Optional<Path> file, Map<String, String> over) {
        return assertThrows(ConfigLoader.ConfigException.class, () -> ConfigLoader.load(env, file, over));
    }

    @Test
    void defaultsAreValid() throws Exception {
        AppConfig c = ConfigLoader.load(Map.of(), Optional.empty(), Map.of());
        assertEquals(4, c.retryPolicy().maxAttempts());
        assertEquals(Duration.ofSeconds(10), c.connectTimeout());
        assertTrue(c.azureKey().isEmpty());
        assertFalse(c.keepTemp());
    }

    @Test
    void precedenceIsOverrideThenEnvThenFileThenDefault() throws Exception {
        Path f = Files.writeString(dir.resolve("taika.properties"), "retry.maxAttempts=2\nlimits.maxPages=10\nhttp.requestTimeout=PT5S\n");
        AppConfig c = ConfigLoader.load(Map.of("TAIKA_MAX_PAGES", "20", "TAIKA_REQUEST_TIMEOUT", "7"), Optional.of(f),
                Map.of("limits.maxPages", "30"));
        assertEquals(2, c.retryPolicy().maxAttempts(), "file beats default");
        assertEquals(Duration.ofSeconds(7), c.requestTimeout(), "env beats file; bare seconds accepted");
        assertEquals(30, c.limits().maxPages(), "override beats env");
    }

    @Test
    void secretsInConfigFileAreRefusedByNameNotValue() throws Exception {
        Path f = Files.writeString(dir.resolve("bad.properties"), "deepl.authKey=supersecret123\nazure.password=hunter2\n");
        var e = fails(Map.of(), Optional.of(f), Map.of());
        assertEquals(2, e.problems.size(), e.getMessage());
        assertFalse(e.getMessage().contains("supersecret123"));
        assertFalse(e.getMessage().contains("hunter2"));
        assertTrue(e.getMessage().contains("deepl.authKey"));
    }

    @Test
    void unknownSettingIsAnErrorNotSilentlyIgnored() throws Exception {
        Path f = Files.writeString(dir.resolve("typo.properties"), "retry.maxAtempts=9\n");
        assertTrue(fails(Map.of(), Optional.of(f), Map.of()).getMessage().contains("retry.maxAtempts"));
        assertTrue(fails(Map.of(), Optional.empty(), Map.of("nope", "1")).getMessage().contains("nope"));
    }

    @Test
    void allProblemsAreReportedTogether() {
        var e = fails(Map.of("TAIKA_RETRY_MAX_ATTEMPTS", "0", "TAIKA_CONNECT_TIMEOUT", "-5", "DEEPL_FORMALITY", "rude",
                "AZURE_DI_API_VERSION", "latest", "TAIKA_KEEP_TEMP", "yes"), Optional.empty(), Map.of());
        assertEquals(5, e.problems.size(), e.getMessage());
    }

    @Test
    void endpointsMustBeHttpsExceptLocalhost() throws Exception {
        assertTrue(fails(Map.of("AZURE_DI_ENDPOINT", "http://evil.example.com"), Optional.empty(), Map.of())
                .getMessage().contains("https"));
        assertTrue(fails(Map.of("DEEPL_BASE_URL", "https://user:pw@api.deepl.com"), Optional.empty(), Map.of())
                .getMessage().contains("credentials"));
        assertTrue(fails(Map.of("DEEPL_BASE_URL", "not a url"), Optional.empty(), Map.of()).getMessage().contains("valid URL"));
        AppConfig c = ConfigLoader.load(Map.of("DEEPL_BASE_URL", "http://127.0.0.1:8080"), Optional.empty(), Map.of());
        assertEquals(8080, c.deeplBaseUrl().getPort());
    }

    @Test
    void freeKeyAgainstProHostIsCaughtAtStartup() {
        var e = fails(Map.of("DEEPL_AUTH_KEY", "abc:fx"), Optional.empty(), Map.of());
        assertTrue(e.getMessage().contains("api-free.deepl.com"));
        assertFalse(e.getMessage().contains("abc:fx"));
        var e2 = fails(Map.of("DEEPL_AUTH_KEY", "pro-key", "DEEPL_BASE_URL", "https://api-free.deepl.com"), Optional.empty(), Map.of());
        assertTrue(e2.getMessage().contains("Pro key"));
    }

    @Test
    void secretsNeverAppearInToStringOrDescribe() throws Exception {
        AppConfig c = ConfigLoader.load(Map.of("DEEPL_AUTH_KEY", "real-secret-value", "AZURE_DI_KEY", "azure-secret-value"),
                Optional.empty(), Map.of());
        assertFalse(c.toString().contains("real-secret-value"));
        assertFalse(c.toString().contains("azure-secret-value"));
        assertFalse(c.describe().toString().contains("secret-value"));
        assertEquals("[set]", c.describe().get("deepl.key"));
        assertEquals("real-secret-value", c.deeplKey().orElseThrow().reveal());
    }

    @Test
    void requiredProvidersCheckedBeforeWork() throws Exception {
        AppConfig none = ConfigLoader.load(Map.of(), Optional.empty(), Map.of());
        var e = assertThrows(ConfigLoader.ConfigException.class, () -> ConfigLoader.requireProviders(none, true, true));
        assertEquals(3, e.problems.size(), e.getMessage());
        AppConfig ok = ConfigLoader.load(Map.of("AZURE_DI_KEY", "k", "AZURE_DI_ENDPOINT", "https://x.cognitiveservices.azure.com",
                "DEEPL_AUTH_KEY", "k2"), Optional.empty(), Map.of());
        assertDoesNotThrow(() -> ConfigLoader.requireProviders(ok, true, true));
    }

    @Test
    void fingerprintChangesOnlyWithOutputAffectingSettings() throws Exception {
        String base = ConfigLoader.load(Map.of(), Optional.empty(), Map.of()).fingerprint();
        assertEquals(base, ConfigLoader.load(Map.of("TAIKA_REQUEST_TIMEOUT", "99", "DEEPL_AUTH_KEY", "x"), Optional.empty(), Map.of()).fingerprint());
        assertNotEquals(base, ConfigLoader.load(Map.of("DEEPL_FORMALITY", "more"), Optional.empty(), Map.of()).fingerprint());
        assertNotEquals(base, ConfigLoader.load(Map.of("DEEPL_GLOSSARY_ID", "g1"), Optional.empty(), Map.of()).fingerprint());
    }

    @Test
    void retryPolicyContradictionsAreConfigErrors() {
        var e = fails(Map.of("TAIKA_RETRY_BASE_DELAY", "PT30S", "TAIKA_RETRY_MAX_DELAY", "PT1S"), Optional.empty(), Map.of());
        assertTrue(e.getMessage().contains("retry settings"));
    }

    @Test
    void blankSecretIsTreatedAsMissing() throws Exception {
        assertTrue(ConfigLoader.load(Map.of("DEEPL_AUTH_KEY", "   "), Optional.empty(), Map.of()).deeplKey().isEmpty());
        assertThrows(IllegalArgumentException.class, () -> Secret.of(" "));
    }
}
