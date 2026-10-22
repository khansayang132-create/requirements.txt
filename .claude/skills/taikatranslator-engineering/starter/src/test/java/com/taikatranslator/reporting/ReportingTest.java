package com.taikatranslator.reporting;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.2 and the processing report. */
class ReportingTest {

    private final Clock fixed = Clock.fixed(Instant.parse("2026-10-23T00:00:00Z"), ZoneOffset.UTC);
    private final ObjectMapper json = new ObjectMapper();

    @Test
    void redactsEveryCredentialShape() {
        String[] leaks = {
                "Authorization: DeepL-Auth-Key 1234abcd-ef56:fx",
                "authorization=Bearer eyJhbGciOi.payload.sig",
                "Ocp-Apim-Subscription-Key: 0123456789abcdef0123456789abcdef",
                "{\"api_key\":\"sk-live-secret\"}",
                "password=hunter2&user=a",
                "https://acct.blob.core.windows.net/c/f.pdf?sv=2024&sig=AbC%2Bdef&se=2026"
        };
        String[] secrets = {"1234abcd-ef56:fx", "eyJhbGciOi.payload.sig", "0123456789abcdef0123456789abcdef",
                "sk-live-secret", "hunter2", "AbC%2Bdef"};
        for (int i = 0; i < leaks.length; i++) {
            String out = Redactor.redact(leaks[i]);
            assertFalse(out.contains(secrets[i]), out);
            assertTrue(out.contains("[REDACTED]"), out);
        }
        assertEquals("stage translation finished", Redactor.redact("stage translation finished"));
        assertNull(Redactor.redact(null));
    }

    @Test
    void runLogEmitsOneJsonObjectPerLineWithRunId() throws Exception {
        ByteArrayOutputStream buf = new ByteArrayOutputStream();
        RunLog log = new RunLog("run-42", fixed, new PrintStream(buf, true, StandardCharsets.UTF_8));
        log.info("translation", "stage_completed", Map.of("durationMs", 842, "status", "SUCCESS", "translatedBlocks", 37));
        log.error("translation", "provider_error", Map.of("detail", "Authorization: DeepL-Auth-Key abc:fx"));

        String[] lines = buf.toString(StandardCharsets.UTF_8).strip().split("\n");
        assertEquals(2, lines.length);
        JsonNode first = json.readTree(lines[0]);
        assertEquals("2026-10-23T00:00:00Z", first.get("timestamp").asText());
        assertEquals("run-42", first.get("runId").asText());
        assertEquals(842, first.get("durationMs").asInt());
        assertTrue(first.get("durationMs").isNumber());
        assertFalse(lines[1].contains("abc:fx"));
    }

    @Test
    void reportStatusFollowsStagesGatesAndArtifacts(@TempDir Path dir) throws Exception {
        ProcessingReport r = new ProcessingReport("run-1", fixed)
                .environment("java", "17")
                .input("file", "contract.pdf");
        assertEquals(ProcessingReport.Status.FAILED, r.overall(), "no stages = nothing proven");

        r.stage("extraction", ProcessingReport.Status.SUCCESS, Duration.ofMillis(1200), 0, Map.of("pages", 3, "blocks", 41), List.of(), null);
        r.stage("layout", ProcessingReport.Status.SUCCESS_WITH_WARNINGS, Duration.ofMillis(80), 0, Map.of("overflowBlocks", 1), List.of("block p2-7 overflow"), null);
        r.gate("execution", true, "all stages reported");
        r.artifact(new ProcessingReport.Artifact("docx", "out/contract.ES.docx", "ab12", 2048, true, List.of()));
        assertEquals(ProcessingReport.Status.SUCCESS_WITH_WARNINGS, r.overall());

        r.gate("structure", false, "table 1 has 3 rows, expected 4");
        assertEquals(ProcessingReport.Status.FAILED, r.overall());

        Path out = dir.resolve("report.json");
        r.write(out);
        JsonNode n = json.readTree(out.toFile());
        assertEquals(1, n.get("schemaVersion").asInt());
        assertEquals("FAILED", n.get("status").asText());
        assertEquals(2, n.get("stages").size());
        assertEquals(41, n.get("stages").get(0).get("counts").get("blocks").asInt());
    }

    @Test
    void invalidArtifactFailsTheRun() {
        ProcessingReport r = new ProcessingReport("run-2", fixed);
        r.stage("assembly", ProcessingReport.Status.SUCCESS, Duration.ZERO, 0, Map.of(), List.of(), null);
        r.artifact(new ProcessingReport.Artifact("docx", "x.docx", null, 0, false, List.of("file is empty")));
        assertEquals(ProcessingReport.Status.FAILED, r.overall());
    }
}
