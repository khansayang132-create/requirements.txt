package com.taikatranslator.pipeline;

import com.fasterxml.jackson.databind.JsonNode;
import com.taikatranslator.docx.DocxAssembler;
import com.taikatranslator.docx.DocxInspector;
import com.taikatranslator.geometry.CoordinateNormalizer;
import com.taikatranslator.layout.TextMeasurer;
import com.taikatranslator.pipeline.CanonicalDocument.Block;
import com.taikatranslator.pipeline.CanonicalDocument.Paragraph;
import com.taikatranslator.pipeline.CanonicalDocument.Table;
import com.taikatranslator.provider.Translator;
import com.taikatranslator.reporting.ProcessingReport;
import com.taikatranslator.reporting.ProcessingReport.Status;
import com.taikatranslator.reporting.RunLog;
import com.taikatranslator.retry.ProviderException;
import com.taikatranslator.translation.PlaceholderProtector;
import com.taikatranslator.translation.TranslationValidator;
import com.taikatranslator.validation.ArtifactValidator;
import com.taikatranslator.validation.AtomicPublisher;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * How the stages and the six acceptance gates fit together. Not a framework:
 * a worked example to adapt into the real project's orchestration.
 *
 * <p>extraction result → canonical model → structural validation → translation
 * (protected placeholders) → translation validation → DOCX → artifact
 * validation → structure check → atomic publish → report.
 */
public final class ReferencePipeline {

    public interface Extractor {
        JsonNode analyze(byte[] document) throws ProviderException, InterruptedException;
    }

    private final Extractor extractor;
    private final Translator translator;
    private final TextMeasurer measurer;
    private final Clock clock;
    private final RunLog log;

    public ReferencePipeline(Extractor extractor, Translator translator, TextMeasurer measurer, Clock clock, RunLog log) {
        this.extractor = extractor;
        this.translator = translator;
        this.measurer = measurer;
        this.clock = clock;
        this.log = log;
    }

    public ProcessingReport run(Path input, Path finalDocx, String targetLang, boolean overwrite) throws InterruptedException {
        ProcessingReport report = new ProcessingReport(log.runId(), clock);
        report.environment("java", System.getProperty("java.version"));
        report.input("file", input.getFileName().toString()).input("targetLang", targetLang);
        try {
            report.input("sha256", sha256(input));

            // 1. Extraction
            Instant t0 = clock.instant();
            JsonNode raw = extractor.analyze(Files.readAllBytes(input));
            AzureLayoutMapper mapper = new AzureLayoutMapper(new CoordinateNormalizer());
            CanonicalDocument source = mapper.map(raw);
            long paragraphs = source.blocks().stream().filter(b -> b instanceof Paragraph).count();
            long tables = source.blocks().stream().filter(b -> b instanceof Table).count();
            stage(report, "extraction", t0, mapper.recoveries(), 0,
                    Map.of("pages", source.pages().size(), "paragraphs", paragraphs, "tables", tables));

            // 2. Structural validation of the model
            List<String> structural = structuralProblems(source);
            report.gate("content.extracted", structural.isEmpty() && !source.blocks().isEmpty(),
                    structural.isEmpty() ? source.blocks().size() + " blocks extracted" : String.join("; ", structural));
            if (!structural.isEmpty()) return report;

            // 3. Translation with protected placeholders
            t0 = clock.instant();
            PlaceholderProtector protector = new PlaceholderProtector();
            List<String> ids = new ArrayList<>();
            List<String> sources = new ArrayList<>();
            for (Block b : source.blocks()) {
                if (b instanceof Paragraph p) { ids.add(p.id()); sources.add(p.text()); }
                else if (b instanceof Table t)
                    for (int r = 0; r < t.rows(); r++)
                        for (int c = 0; c < t.columns(); c++) { ids.add(t.id() + "[" + r + "," + c + "]"); sources.add(t.cells().get(r).get(c)); }
            }
            List<PlaceholderProtector.Protected> prot = sources.stream().map(protector::protect).toList();
            Translator.Response resp = translator.translate(new Translator.Request(
                    prot.stream().map(PlaceholderProtector.Protected::xml).toList(), Optional.empty(), targetLang, true));
            if (resp.texts().size() != sources.size())
                throw new IllegalStateException("translator returned " + resp.texts().size() + " texts for " + sources.size());
            List<String> translated = new ArrayList<>();
            for (int i = 0; i < sources.size(); i++) translated.add(protector.restore(resp.texts().get(i), prot.get(i).tokens()));
            stage(report, "translation", t0, List.of(), resp.retries(), Map.of("blocks", sources.size()));

            // 4. Translation validation
            List<TranslationValidator.Block> tb = new ArrayList<>();
            for (int i = 0; i < ids.size(); i++) tb.add(new TranslationValidator.Block(ids.get(i), sources.get(i), translated.get(i)));
            TranslationValidator.Result tv = new TranslationValidator(3.0).validate(ids, tb);
            report.gate("content.translated", tv.passed(), tv.checked() + " blocks checked, " + tv.errorCount() + " errors, "
                    + (tv.findings().size() - tv.errorCount()) + " warnings");
            if (!tv.passed()) return report;

            // 5. Layout + DOCX, staged next to the destination
            t0 = clock.instant();
            CanonicalDocument target = substitute(source, translated);
            AtomicPublisher publisher = new AtomicPublisher();
            Path staged = publisher.stage(finalDocx);
            List<String> layoutWarnings = new DocxAssembler(measurer).write(target, staged);
            stage(report, "assembly", t0, layoutWarnings, 0, Map.of("layoutWarnings", layoutWarnings.size()));

            // 6. Artifact integrity
            ArtifactValidator.Result av = new ArtifactValidator().validate(staged, ArtifactValidator.Type.DOCX);
            report.artifact(new ProcessingReport.Artifact("docx", finalDocx.toString(), av.ok() ? sha256(staged) : null,
                    Files.exists(staged) ? Files.size(staged) : 0, av.ok(), av.problems()));
            report.gate("artifact.integrity", av.ok(), av.ok() ? "DOCX reopened in Apache POI" : String.join("; ", av.problems()));
            if (!av.ok()) { publisher.discard(staged, true); return report; }

            // 7. Structure preserved
            DocxInspector.Snapshot snap = new DocxInspector().inspect(staged);
            long bodyParas = target.blocks().stream().filter(b -> b instanceof Paragraph p
                    && p.role() != CanonicalDocument.Role.HEADER && p.role() != CanonicalDocument.Role.FOOTER
                    && p.role() != CanonicalDocument.Role.PAGE_NUMBER).count();
            boolean structureOk = snap.paragraphCount() >= bodyParas && snap.tableCount() == tables;
            report.gate("structure", structureOk, "paragraphs " + snap.paragraphCount() + " (expected >= " + bodyParas
                    + "), tables " + snap.tableCount() + " (expected " + tables + ")");
            if (!structureOk) { publisher.discard(staged, true); return report; }

            // 8. Publish
            publisher.publish(staged, finalDocx, overwrite);
            report.gate("execution", true, "all stages completed");
            // Visual fidelity is a separate gate with its own tooling; never mark it passed here.
            report.stage("visual", Status.SKIPPED, Duration.ZERO, 0, Map.of(),
                    List.of("not run by this pipeline; run scripts/visual_diff.py"), null);
            log.info("pipeline", "run_completed", Map.of("status", report.overall().name()));
        } catch (ProviderException e) {
            report.stage("provider", Status.FAILED, Duration.ZERO, 0, Map.of(), List.of(e.getMessage()), e.category().name());
            log.error("pipeline", "provider_failed", Map.of("category", e.category().name(), "httpStatus", e.httpStatus()));
        } catch (IOException | RuntimeException e) {
            report.stage("pipeline", Status.FAILED, Duration.ZERO, 0, Map.of(), List.of(e.getClass().getSimpleName() + ": " + e.getMessage()), null);
            log.error("pipeline", "failed", Map.of("error", e.getClass().getSimpleName()));
        }
        return report;
    }

    private void stage(ProcessingReport r, String name, Instant start, List<String> warnings, int retries, Map<String, Number> counts) {
        Duration d = Duration.between(start, clock.instant());
        r.stage(name, warnings.isEmpty() ? Status.SUCCESS : Status.SUCCESS_WITH_WARNINGS, d, retries, counts, warnings, null);
        log.info(name, "stage_completed", Map.of("durationMs", d.toMillis(), "retries", retries, "warnings", warnings.size()));
    }

    static List<String> structuralProblems(CanonicalDocument d) {
        List<String> out = new ArrayList<>();
        if (d.pages().isEmpty()) out.add("no pages");
        for (Block b : d.blocks()) {
            if (b.page() < 1 || b.page() > d.pages().size()) out.add(b.id() + ": page " + b.page() + " out of range");
            if (b instanceof Table t && (t.rows() < 1 || t.columns() < 1)) out.add(t.id() + ": empty table");
        }
        return out;
    }

    private static CanonicalDocument substitute(CanonicalDocument src, List<String> translated) {
        List<Block> out = new ArrayList<>();
        int i = 0;
        for (Block b : src.blocks()) {
            if (b instanceof Paragraph p) out.add(new Paragraph(p.id(), p.role(), translated.get(i++), p.page(), p.box()));
            else if (b instanceof Table t) {
                List<List<String>> cells = new ArrayList<>();
                for (int r = 0; r < t.rows(); r++) {
                    List<String> row = new ArrayList<>();
                    for (int c = 0; c < t.columns(); c++) row.add(translated.get(i++));
                    cells.add(row);
                }
                out.add(new Table(t.id(), t.rows(), t.columns(), cells, t.page(), t.box()));
            }
        }
        return new CanonicalDocument(src.pages(), out);
    }

    static String sha256(Path p) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(Files.readAllBytes(p)));
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
