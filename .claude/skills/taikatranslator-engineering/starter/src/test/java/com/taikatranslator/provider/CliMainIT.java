package com.taikatranslator.provider;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.core.CheckpointStore;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.*;

/**
 * TSK-6.1 end to end: launches target/taikatranslator.jar as a separate process
 * with a clean environment, against one local stub that plays both Azure and
 * DeepL. Checks exit codes, outputs, resume behaviour and what reached the network.
 */
class CliMainIT {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Path JAR = Path.of("target", "taikatranslator.jar");
    private static JsonNode azureMock;
    private static Map<String, String> deeplMock;

    @TempDir
    Path work;

    @BeforeAll
    static void load() throws IOException {
        assertTrue(Files.exists(JAR), "run `mvn verify` so the JAR is packaged before integration tests");
        try (InputStream in = CliMainIT.class.getClassLoader().getResourceAsStream("mocks/azure-layout-service-agreement.json")) {
            azureMock = JSON.readTree(in);
        }
        deeplMock = new HashMap<>();
        try (InputStream in = CliMainIT.class.getClassLoader().getResourceAsStream("mocks/deepl-es-service-agreement.json")) {
            JSON.readTree(in).fields().forEachRemaining(e -> deeplMock.put(e.getKey(), e.getValue().asText()));
        }
    }

    /** One stub for both providers. deeplStatus != 200 makes every translate call fail with it. */
    private static final class Providers implements AutoCloseable {
        final AtomicInteger azureCalls = new AtomicInteger();
        final AtomicInteger deeplCalls = new AtomicInteger();
        final StubServer server;
        int port;

        Providers(int deeplStatus) throws IOException {
            server = new StubServer((req, n) -> {
                if (req.path().startsWith("/documentintelligence/")) {
                    azureCalls.incrementAndGet();
                    return new StubServer.Reply(202, "", Map.of("Operation-Location", "http://127.0.0.1:" + port + "/op/1"));
                }
                if (req.path().startsWith("/op/")) {
                    azureCalls.incrementAndGet();
                    return StubServer.Reply.json(200, JSON.writeValueAsString(azureMock));
                }
                if (req.path().equals("/v2/translate")) {
                    deeplCalls.incrementAndGet();
                    if (deeplStatus != 200) return StubServer.Reply.json(deeplStatus, "{\"message\":\"stub\"}");
                    List<Map<String, String>> out = new ArrayList<>();
                    for (JsonNode t : JSON.readTree(req.body()).get("text")) {
                        String es = deeplMock.get(t.asText());
                        if (es == null) return StubServer.Reply.json(400, "{\"message\":\"no fixture translation\"}");
                        out.add(Map.of("text", es));
                    }
                    return StubServer.Reply.json(200, JSON.writeValueAsString(Map.of("translations", out)));
                }
                return StubServer.Reply.json(404, "{}");
            });
            port = server.baseUri().getPort();
        }

        Map<String, String> env() {
            return new HashMap<>(Map.of(
                    "AZURE_DI_ENDPOINT", "http://127.0.0.1:" + port,
                    "AZURE_DI_KEY", "azure-test-key-123",
                    "DEEPL_BASE_URL", "http://127.0.0.1:" + port,
                    "DEEPL_AUTH_KEY", "deepl-test-key-456",
                    "TAIKA_POLL_INTERVAL", "PT0.01S",
                    "TAIKA_RETRY_BASE_DELAY", "PT0.01S",
                    "TAIKA_RETRY_MAX_DELAY", "PT0.05S"));
        }

        @Override
        public void close() {
            server.close();
        }
    }

    private record Result(int exit, String stdout, String stderr) { }

    private Result run(Map<String, String> env, String... args) throws Exception {
        List<String> cmd = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(),
                "-Djava.io.tmpdir=" + work.resolve("tmp"), "-jar", JAR.toAbsolutePath().toString()));
        cmd.addAll(List.of(args));
        Files.createDirectories(work.resolve("tmp"));
        ProcessBuilder pb = new ProcessBuilder(cmd);
        pb.environment().clear();
        pb.environment().putAll(env);
        Path outFile = work.resolve("stdout.txt"), errFile = work.resolve("stderr.txt");
        pb.redirectOutput(outFile.toFile()).redirectError(errFile.toFile());
        Process p = pb.start();
        assertTrue(p.waitFor(120, TimeUnit.SECONDS), "process timed out");
        return new Result(p.exitValue(), Files.readString(outFile, StandardCharsets.UTF_8), Files.readString(errFile, StandardCharsets.UTF_8));
    }

    private Path input() throws IOException {
        Path p = work.resolve("in dir/service agreement.pdf");
        Files.createDirectories(p.getParent());
        try (InputStream in = getClass().getClassLoader().getResourceAsStream("fixtures/service-agreement.pdf")) {
            Files.copy(in, p, StandardCopyOption.REPLACE_EXISTING);
        }
        return p;
    }

    private String[] args(Path in, Path outDir, String... extra) {
        List<String> a = new ArrayList<>(List.of("--input", in.toString(), "--output-dir", outDir.toString(), "--target-lang", "ES"));
        a.addAll(List.of(extra));
        return a.toArray(String[]::new);
    }

    @Test
    void usageAndHelp() throws Exception {
        Result none = run(Map.of());
        assertEquals(2, none.exit, none.stderr);
        assertTrue(none.stderr.contains("Usage:"));
        Result help = run(Map.of(), "--help");
        assertEquals(0, help.exit);
        assertTrue(help.stdout.contains("Exit codes:"));
    }

    @Test
    void cheapChecksFailBeforeAnyNetworkCall() throws Exception {
        try (Providers p = new Providers(200)) {
            Path in = input(), out = work.resolve("out");

            Map<String, String> badConfig = p.env();
            badConfig.put("TAIKA_RETRY_MAX_ATTEMPTS", "0");
            assertEquals(4, run(badConfig, args(in, out)).exit, "invalid setting");

            Map<String, String> noKeys = p.env();
            noKeys.remove("AZURE_DI_KEY");
            Result r = run(noKeys, args(in, out));
            assertEquals(4, r.exit);
            assertTrue(r.stderr.contains("AZURE_DI_KEY is not set"), r.stderr);

            Map<String, String> tiny = p.env();
            tiny.put("TAIKA_MAX_FILE_BYTES", "100");
            assertEquals(9, run(tiny, args(in, out)).exit, "file over the size limit");

            assertEquals(3, run(p.env(), args(work.resolve("missing.pdf"), out)).exit, "missing input");
            assertEquals(0, p.azureCalls.get() + p.deeplCalls.get(), "nothing reached the providers");
        }
    }

    @Test
    void fullRunRefusesOverwriteAndResumesWithoutPayingTwice() throws Exception {
        try (Providers p = new Providers(200)) {
            Path in = input(), out = work.resolve("out dir");

            // 1. First run: extraction + translation hit the providers
            Result first = run(p.env(), args(in, out));
            assertEquals(1, first.exit, "SUCCESS_WITH_WARNINGS (clamped box) maps to exit 1\n" + first.stderr);
            Path docx = out.resolve("service agreement.ES.docx");
            Path reportFile = out.resolve("service agreement.ES.report.json");
            assertTrue(Files.exists(docx));
            JsonNode report = JSON.readTree(reportFile.toFile());
            assertEquals("SUCCESS_WITH_WARNINGS", report.get("status").asText());
            assertEquals(2, p.azureCalls.get(), "submit + one poll");
            assertEquals(1, p.deeplCalls.get());

            // Logs: JSON lines with one runId, no keys, no document text
            String runId = report.get("runId").asText();
            for (String line : first.stdout.strip().split("\n")) assertEquals(runId, JSON.readTree(line).get("runId").asText());
            for (String s : List.of(first.stdout, first.stderr, Files.readString(reportFile))) {
                assertFalse(s.contains("azure-test-key-123"), "Azure key leaked");
                assertFalse(s.contains("deepl-test-key-456"), "DeepL key leaked");
                assertFalse(s.contains("Importe total"), "document text leaked into logs/report");
            }
            assertEquals("[set]", report.get("environment").get("config.deepl.key").asText());
            try (var tmp = Files.list(work.resolve("tmp"))) {
                assertEquals(0, tmp.filter(f -> f.getFileName().toString().startsWith("taika-")).count(), "workspace removed after success");
            }

            // 2. Same command again: refused, original untouched
            String hash = CheckpointStore.sha256(docx);
            Result second = run(p.env(), args(in, out));
            assertEquals(8, second.exit, second.stderr);
            assertEquals(hash, CheckpointStore.sha256(docx));

            // 3. --overwrite: extraction checkpoint and translation cache reused, providers not called again
            Result third = run(p.env(), args(in, out, "--overwrite"));
            assertEquals(1, third.exit, third.stderr);
            assertEquals(2, p.azureCalls.get(), "extraction came from the checkpoint");
            assertEquals(1, p.deeplCalls.get(), "translations came from the cache");
            assertTrue(third.stdout.contains("checkpoint_reused"));
            // 7 paragraphs (header, title, heading, 3 body, page number) + 7 non-blank cells (8 minus the merged-away one)
            assertEquals(14, JSON.readTree(reportFile.toFile()).get("inputs").get("translationCacheHits").asInt());
        }
    }

    @Test
    void documentLimitStopsBeforeTranslation() throws Exception {
        try (Providers p = new Providers(200)) {
            Map<String, String> env = p.env();
            env.put("TAIKA_MAX_CHARACTERS", "50");
            Path out = work.resolve("out");
            Result r = run(env, args(input(), out));
            assertEquals(9, r.exit, r.stderr);
            assertEquals(0, p.deeplCalls.get(), "nothing sent for translation");
            assertFalse(Files.exists(out.resolve("service agreement.ES.docx")));
            JsonNode report = JSON.readTree(out.resolve("service agreement.ES.report.json").toFile());
            assertEquals("FAILED", report.get("status").asText());
        }
    }

    @Test
    void quotaExceededIsAProviderErrorWithDiagnosticsKept() throws Exception {
        try (Providers p = new Providers(456)) {
            Path out = work.resolve("out");
            Result r = run(p.env(), args(input(), out));
            assertEquals(5, r.exit, r.stderr);
            assertEquals(1, p.deeplCalls.get(), "456 is never retried");
            assertFalse(Files.exists(out.resolve("service agreement.ES.docx")));
            assertTrue(r.stderr.contains("temp folder kept"), r.stderr);
            JsonNode report = JSON.readTree(out.resolve("service agreement.ES.report.json").toFile());
            assertEquals("FAILED", report.get("status").asText());
        }
    }
}
