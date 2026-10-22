package com.taikatranslator.provider;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.docx.DocxInspector;
import com.taikatranslator.docx.DocxInspector.Element;
import com.taikatranslator.docx.DocxInspector.Para;
import com.taikatranslator.docx.DocxInspector.Snapshot;
import com.taikatranslator.docx.StructureDiff;
import com.taikatranslator.geometry.CoordinateNormalizer;
import com.taikatranslator.layout.FixedAdvanceMeasurer;
import com.taikatranslator.pipeline.AzureLayoutMapper;
import com.taikatranslator.pipeline.CanonicalDocument;
import com.taikatranslator.pipeline.ReferencePipeline;
import com.taikatranslator.reporting.ProcessingReport;
import com.taikatranslator.reporting.RunLog;
import com.taikatranslator.retry.RetryExecutor;
import com.taikatranslator.retry.RetryPolicy;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.PrintStream;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

/**
 * TSK-5.2.5 + TSK-5.2.6: the synthetic service agreement through every stage,
 * with Azure mocked from a fixture file and DeepL served by a local stub that
 * translates from a fixture dictionary. Expected results live in
 * src/test/resources/expected/, not in this class.
 *
 * <p>Evidence (DOCX, report, log) is copied to target/e2e-evidence/ for CI to archive.
 */
class EndToEndFixtureIT {

    private static final ObjectMapper JSON = new ObjectMapper();
    private static final Path EVIDENCE = Path.of("target", "e2e-evidence");
    private static JsonNode azureMock;
    private static Map<String, String> deeplMock;
    private static JsonNode expectedExtraction;
    private static JsonNode expectedStructure;

    private final Clock clock = Clock.fixed(Instant.parse("2026-10-23T00:00:00Z"), ZoneOffset.UTC);

    @TempDir
    Path work;

    @BeforeAll
    static void load() throws IOException {
        azureMock = resource("mocks/azure-layout-service-agreement.json").get("analyzeResult");
        deeplMock = new HashMap<>();
        resource("mocks/deepl-es-service-agreement.json").fields().forEachRemaining(e -> deeplMock.put(e.getKey(), e.getValue().asText()));
        expectedExtraction = resource("expected/service-agreement.extraction.json");
        expectedStructure = resource("expected/service-agreement.ES.structure.json");
        Files.createDirectories(EVIDENCE);
    }

    private static JsonNode resource(String path) throws IOException {
        try (InputStream in = EndToEndFixtureIT.class.getClassLoader().getResourceAsStream(path)) {
            assertNotNull(in, "missing test resource " + path);
            return JSON.readTree(in);
        }
    }

    private Path input() throws IOException {
        Path p = work.resolve("service agreement.pdf");
        try (InputStream in = getClass().getClassLoader().getResourceAsStream("fixtures/service-agreement.pdf")) {
            assertNotNull(in, "fixture PDF missing; run fixtures/make_fixtures.py");
            Files.copy(in, p, StandardCopyOption.REPLACE_EXISTING);
        }
        return p;
    }

    /** DeepL stub: looks up each protected-XML text in the fixture dictionary; unknown text is a 400. */
    private StubServer deepl(Map<String, String> dictionary) throws IOException {
        return new StubServer((req, n) -> {
            JsonNode body = JSON.readTree(req.body());
            List<Map<String, String>> out = new ArrayList<>();
            for (JsonNode t : body.get("text")) {
                String es = dictionary.get(t.asText());
                if (es == null) return StubServer.Reply.json(400, "{\"message\":\"no fixture translation\"}");
                out.add(Map.of("detected_source_language", "EN", "text", es));
            }
            return StubServer.Reply.json(200, JSON.writeValueAsString(Map.of("translations", out)));
        });
    }

    private record Run(ProcessingReport report, String log) { }

    private Run run(StubServer stub, Path out, boolean overwrite) throws Exception {
        ByteArrayOutputStream logBuf = new ByteArrayOutputStream();
        RunLog log = new RunLog("e2e-run", clock, new PrintStream(logBuf, true, StandardCharsets.UTF_8));
        RetryExecutor retry = new RetryExecutor(RetryPolicy.noRetries());
        DeepLTranslator translator = new DeepLTranslator(HttpClient.newHttpClient(), stub.baseUri(), "fixture-key:fx", retry, Duration.ofSeconds(5));
        ReferencePipeline pipeline = new ReferencePipeline(doc -> azureMock, translator, new FixedAdvanceMeasurer(0.5), clock, log);
        ProcessingReport report = pipeline.run(input(), out, "ES", overwrite);
        return new Run(report, logBuf.toString(StandardCharsets.UTF_8));
    }

    @Test
    void extractionMatchesDocumentedExpectation() {
        AzureLayoutMapper mapper = new AzureLayoutMapper(new CoordinateNormalizer());
        CanonicalDocument doc = mapper.map(azureMock);
        JsonNode expected = expectedExtraction.get("blocks");
        assertEquals(expected.size(), doc.blocks().size(), "table cell paragraphs must not be duplicated");
        List<String> problems = new ArrayList<>();
        for (int i = 0; i < expected.size(); i++) {
            JsonNode e = expected.get(i);
            CanonicalDocument.Block b = doc.blocks().get(i);
            if (!e.get("id").asText().equals(b.id())) problems.add(i + ": id " + b.id() + ", expected " + e.get("id").asText());
            if (b instanceof CanonicalDocument.Paragraph p) {
                if (!e.get("text").asText().equals(p.text())) problems.add(i + ": text '" + p.text() + "'");
                if (!e.get("role").asText().equals(p.role().name())) problems.add(i + ": role " + p.role());
            } else if (b instanceof CanonicalDocument.Table t) {
                if (t.rows() != e.get("rows").asInt() || t.columns() != e.get("columns").asInt()) problems.add(i + ": table shape");
                if (!JSON.valueToTree(t.cells()).equals(e.get("cells"))) problems.add(i + ": table cells " + t.cells());
            }
        }
        assertTrue(problems.isEmpty(), "extraction differs:\n" + String.join("\n", problems));
        assertEquals(1, mapper.recoveries().size(), "the 0.6% overflow on p4 is clamped and recorded");
        assertTrue(mapper.recoveries().get(0).startsWith("p4: clamped"));
    }

    @Test
    void fullPipelinePassesEveryGateAndPreservesStructure() throws Exception {
        Path out = work.resolve("out/service agreement.ES.docx");
        Files.createDirectories(out.getParent());
        Run r;
        try (StubServer stub = deepl(deeplMock)) {
            r = run(stub, out, false);
        }
        Path reportFile = work.resolve("report.json");
        r.report().write(reportFile);
        Files.copy(reportFile, EVIDENCE.resolve("report.json"), StandardCopyOption.REPLACE_EXISTING);
        Files.writeString(EVIDENCE.resolve("run.log.jsonl"), r.log());
        if (Files.exists(out)) Files.copy(out, EVIDENCE.resolve("service-agreement.ES.docx"), StandardCopyOption.REPLACE_EXISTING);

        Map<String, Object> m = r.report().toMap();
        String reportJson = JSON.writerWithDefaultPrettyPrinter().writeValueAsString(m);

        // 1. Execution + every gate recorded and passed
        assertNotEquals(ProcessingReport.Status.FAILED, r.report().overall(), reportJson);
        JsonNode gates = JSON.valueToTree(m.get("gates"));
        List<String> gateNames = new ArrayList<>();
        gates.forEach(g -> {
            gateNames.add(g.get("name").asText());
            assertTrue(g.get("passed").asBoolean(), "gate failed: " + g);
        });
        assertEquals(List.of("content.extracted", "content.translated", "artifact.integrity", "structure", "execution"), gateNames);
        assertEquals("SUCCESS_WITH_WARNINGS", m.get("status").toString(), "clamp recovery is a warning, not silence");

        // 2. Visual gate is explicitly SKIPPED, never claimed
        JsonNode stages = JSON.valueToTree(m.get("stages"));
        boolean visualSkipped = false;
        for (JsonNode s : stages) if (s.get("name").asText().equals("visual")) visualSkipped = s.get("status").asText().equals("SKIPPED");
        assertTrue(visualSkipped);

        // 3. Artifact published and reopened; structure equals the expected file
        assertTrue(Files.exists(out));
        Snapshot actual = new DocxInspector().inspect(out);
        List<String> diff = StructureDiff.compare(expectedSnapshot(actual), actual);
        assertTrue(diff.isEmpty(), "DOCX structure differs from expected/service-agreement.ES.structure.json:\n" + String.join("\n", diff));

        // 4. Text expansion: the long Spanish line shrank to fit instead of being cut
        Para last = (Para) actual.body().get(actual.body().size() - 1);
        assertEquals("Importe total adeudado pendiente de pago", last.text());
        assertTrue(last.fontSizes().get(0) < 11.0);

        // 5. Auditability: input hash, run id, no secrets, no document text in the log
        assertEquals(64, JSON.valueToTree(m.get("inputs")).get("sha256").asText().length());
        assertFalse(r.log().contains("fixture-key"), "key leaked into log");
        assertFalse(r.log().contains("Importe total"), "document text leaked into log");
        for (String line : r.log().strip().split("\n")) assertEquals("e2e-run", JSON.readTree(line).get("runId").asText());
    }

    /** Builds the expected snapshot from the JSON file. Alignment is LEFT and there are no images in this fixture. */
    private static Snapshot expectedSnapshot(Snapshot actual) {
        List<Element> body = new ArrayList<>();
        for (JsonNode e : expectedStructure.get("body")) {
            if (e.get("type").asText().equals("paragraph")) {
                String style = e.get("style").isNull() ? null : e.get("style").asText();
                body.add(new Para(style, e.get("text").asText(), "LEFT", List.of(e.get("fontSize").asDouble()), List.of()));
            } else {
                List<List<String>> cells = new ArrayList<>();
                e.get("cells").forEach(row -> {
                    List<String> r = new ArrayList<>();
                    row.forEach(c -> r.add(c.asText()));
                    cells.add(r);
                });
                body.add(new DocxInspector.Table(e.get("rows").asInt(), e.get("columns").asInt(), cells));
            }
        }
        JsonNode s = expectedStructure.get("section");
        return new Snapshot(body, new DocxInspector.Section(s.get("pageWidthTwips").asLong(), s.get("pageHeightTwips").asLong(), s.get("orientation").asText()));
    }

    @Test
    void repeatedRunsProduceTheSameStructure() throws Exception {
        Path a = work.resolve("a/out.docx"), b = work.resolve("b/out.docx");
        try (StubServer stub = deepl(deeplMock)) {
            run(stub, a, false);
            run(stub, b, false);
        }
        assertTrue(StructureDiff.compare(new DocxInspector().inspect(a), new DocxInspector().inspect(b)).isEmpty());
    }

    @Test
    void missingTranslationFailsCleanlyAndPublishesNothing() throws Exception {
        Map<String, String> partial = new HashMap<>(deeplMock);
        partial.remove("Total amount due");
        Path out = work.resolve("fail/out.docx");
        Run r;
        try (StubServer stub = deepl(partial)) {
            r = run(stub, out, false);
        }
        assertEquals(ProcessingReport.Status.FAILED, r.report().overall());
        assertFalse(Files.exists(out), "a failed run must not leave a result behind");
        JsonNode stages = JSON.valueToTree(r.report().toMap().get("stages"));
        assertEquals("CLIENT", stages.get(stages.size() - 1).get("errorCategory").asText());
    }

    @Test
    void existingResultIsNotOverwritten() throws Exception {
        Path out = work.resolve("keep/out.docx");
        Files.createDirectories(out.getParent());
        Files.writeString(out, "previous result");
        Run r;
        try (StubServer stub = deepl(deeplMock)) {
            r = run(stub, out, false);
        }
        assertEquals(ProcessingReport.Status.FAILED, r.report().overall());
        assertEquals("previous result", Files.readString(out));
    }
}
