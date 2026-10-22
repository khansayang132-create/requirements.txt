package com.taikatranslator.cli;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.config.AppConfig;
import com.taikatranslator.config.ConfigLoader;
import com.taikatranslator.core.CheckpointStore;
import com.taikatranslator.core.InputLimits;
import com.taikatranslator.core.RunWorkspace;
import com.taikatranslator.core.TranslationCache;
import com.taikatranslator.layout.AwtTextMeasurer;
import com.taikatranslator.pipeline.ReferencePipeline;
import com.taikatranslator.provider.AzureLayoutClient;
import com.taikatranslator.provider.DeepLTranslator;
import com.taikatranslator.reporting.ProcessingReport;
import com.taikatranslator.reporting.RunLog;
import com.taikatranslator.retry.RetryExecutor;
import com.taikatranslator.retry.Sleeper;

import java.awt.Font;
import java.io.IOException;
import java.io.PrintStream;
import java.net.http.HttpClient;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

/**
 * Command-line entry point.
 *
 * <pre>
 * java -jar target/taikatranslator.jar --input in.pdf --output-dir out --target-lang ES
 * </pre>
 *
 * Order: arguments → configuration → filesystem → file-size limit → credentials →
 * work. Nothing that costs money happens before every cheap check has passed.
 * stdout carries JSON log lines; stderr carries one-line messages for people.
 *
 * <p>Resume: extraction results and translations are cached under
 * {@code <output-dir>/.taika/<input-sha256-prefix>/}. Rerunning the same input
 * with the same output-affecting settings reuses them; a changed input or
 * setting never does. The cache holds translated text, so it lives with the
 * output and is subject to the same handling rules.
 */
public final class Main {

    private Main() { }

    public static void main(String[] args) {
        // POI logs through log4j-api; route it to the built-in simple logger instead of an error banner.
        System.setProperty("log4j2.loggerContextFactory", "org.apache.logging.log4j.simple.SimpleLoggerContextFactory");
        System.setProperty("java.awt.headless", "true");
        System.exit(run(args, System.getenv(), System.out, System.err).code);
    }

    /** Testable core: no System.exit, injectable environment and streams. */
    public static ExitCode run(String[] args, Map<String, String> env, PrintStream out, PrintStream err) {
        for (String a : args) {
            if (a.equals("-h") || a.equals("--help")) {
                out.println(CliOptions.USAGE);
                return ExitCode.OK;
            }
        }
        CliOptions opts;
        Path docx;
        AppConfig config;
        try {
            opts = CliOptions.parse(args);
            config = ConfigLoader.load(env, opts.configFile(), Map.of());
            docx = opts.validateFilesystem();
            new InputLimits(config.limits()).checkFile(opts.input());
            ConfigLoader.requireProviders(config, true, true);
        } catch (CliOptions.CliException e) {
            err.println("error: " + e.getMessage());
            return e.exitCode;
        } catch (ConfigLoader.ConfigException e) {
            err.println("error: " + e.getMessage());
            return ExitCode.CONFIG_ERROR;
        } catch (InputLimits.LimitExceeded e) {
            err.println("error: " + e.getMessage());
            return ExitCode.LIMIT_EXCEEDED;
        } catch (IOException e) {
            err.println("error: cannot read input: " + e.getClass().getSimpleName());
            return ExitCode.INPUT_ERROR;
        }

        String runId = "run-" + DateTimeFormatter.ofPattern("yyyyMMdd'T'HHmmss").withZone(ZoneOffset.UTC).format(Clock.systemUTC().instant())
                + "-" + HexFormat.of().formatHex(new SecureRandom().generateSeed(3));
        Clock clock = Clock.systemUTC();
        RunLog log = new RunLog(runId, clock, out);
        log.info("cli", "run_started", Map.of("targetLang", opts.targetLang()));

        RunWorkspace workspace = null;
        ProcessingReport report = null;
        try {
            workspace = RunWorkspace.create(Path.of(System.getProperty("java.io.tmpdir")), runId);
            String inputSha = CheckpointStore.sha256(opts.input());
            Path cacheDir = opts.outputDir().resolve(".taika").resolve(inputSha.substring(0, 16));
            CheckpointStore checkpoints = new CheckpointStore(cacheDir);

            HttpClient http = HttpClient.newBuilder().connectTimeout(config.connectTimeout()).build();
            RetryExecutor retry = new RetryExecutor(config.retryPolicy(), Sleeper.SYSTEM, Math::random,
                    (op, n, e, wait) -> log.warn("provider", "retry", Map.of("operation", op, "retry", n,
                            "category", e.category().name(), "waitMs", wait.toMillis())));
            AzureLayoutClient azure = new AzureLayoutClient(http, config.azureEndpoint(), config.azureKey().orElseThrow().reveal(),
                    config.azureApiVersion(), retry, Sleeper.SYSTEM, clock, config.requestTimeout(), config.pollInterval(),
                    config.analysisDeadline());
            DeepLTranslator deepl = new DeepLTranslator(http, config.deeplBaseUrl(), config.deeplKey().orElseThrow().reveal(),
                    retry, config.requestTimeout());
            TranslationCache cache = new TranslationCache(deepl, cacheDir.resolve("translations.jsonl"), config.fingerprint());

            ObjectMapper json = new ObjectMapper();
            String contentType = contentType(opts.input());
            ReferencePipeline.Extractor extractor = bytes -> {
                CheckpointStore.Lookup hit = checkpoints.find("extraction", inputSha, config.fingerprint());
                if (hit.hit()) {
                    log.info("extraction", "checkpoint_reused", Map.of());
                    try {
                        return json.readTree(hit.output().get().toFile());
                    } catch (IOException e) {
                        log.warn("extraction", "checkpoint_unreadable", Map.of());
                    }
                }
                AzureLayoutClient.Analysis a = azure.analyze(bytes, contentType);
                try {
                    Path saved = cacheDir.resolve("extraction.json");
                    json.writeValue(saved.toFile(), a.analyzeResult());
                    checkpoints.record("extraction", inputSha, config.fingerprint(), saved);
                } catch (IOException e) {
                    log.warn("extraction", "checkpoint_not_saved", Map.of("error", e.getClass().getSimpleName()));
                }
                return a.analyzeResult();
            };

            // The DOCX declares Calibri; Carlito has identical metrics and is freely installable on servers.
            AwtTextMeasurer measurer = new AwtTextMeasurer("Carlito", Font.PLAIN);
            if (!measurer.resolvedFamily().equalsIgnoreCase("Carlito"))
                log.warn("assembly", "measurer_font_substituted", Map.of("resolved", measurer.resolvedFamily()));
            ReferencePipeline pipeline = new ReferencePipeline(extractor, cache, measurer, clock, log, new InputLimits(config.limits()));
            ProcessingReport r = pipeline.run(opts.input(), docx, opts.targetLang(), opts.overwrite());
            r.environment("measurerFont", measurer.resolvedFamily());
            config.describe().forEach((k, v) -> r.environment("config." + k, v));
            r.input("translationCacheHits", cache.hits());
            report = r;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            err.println("interrupted");
            return ExitCode.INTERRUPTED;
        } catch (IOException | RuntimeException e) {
            err.println("error: " + e.getClass().getSimpleName() + ": " + e.getMessage());
            return ExitCode.PROCESSING_ERROR;
        } finally {
            if (workspace != null) {
                try {
                    boolean ok = report != null && report.overall() != ProcessingReport.Status.FAILED;
                    RunWorkspace.Disposition d = workspace.finish(ok, opts.keepTemp() || config.keepTemp());
                    if (d != RunWorkspace.Disposition.DELETED) err.println("temp folder kept: " + workspace.dir());
                } catch (IOException e) {
                    err.println("warning: temp folder not removed: " + workspace.dir());
                }
            }
        }

        ExitCode code = exitCode(report);
        Path reportPath = docx.resolveSibling(docx.getFileName().toString().replaceFirst("\\.docx$", ".report.json"));
        try {
            Path tmp = Files.createTempFile(reportPath.getParent(), ".report.", ".part");
            report.write(tmp);
            Files.move(tmp, reportPath, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException e) {
            err.println("error: report not written: " + e.getClass().getSimpleName());
            return ExitCode.PROCESSING_ERROR;
        }
        err.println(report.overall() + " (exit " + code.code + "): report " + reportPath
                + (Files.exists(docx) ? ", document " + docx : ", no document written"));
        return code;
    }

    static ExitCode exitCode(ProcessingReport r) {
        switch (r.overall()) {
            case SUCCESS: return ExitCode.OK;
            case SUCCESS_WITH_WARNINGS: return ExitCode.OK_WITH_WARNINGS;
            default: break;
        }
        Optional<String> category = r.failureCategory();
        if (category.isPresent()) {
            switch (category.get()) {
                case "LIMIT_EXCEEDED": return ExitCode.LIMIT_EXCEEDED;
                case "OUTPUT_EXISTS": return ExitCode.OUTPUT_EXISTS;
                default: return ExitCode.PROVIDER_ERROR; // categories come from provider failures
            }
        }
        if (r.anyGateFailed()) return ExitCode.VALIDATION_FAILED;
        return ExitCode.PROCESSING_ERROR;
    }

    private static String contentType(Path input) {
        String n = input.getFileName().toString().toLowerCase(Locale.ROOT);
        if (n.endsWith(".pdf")) return "application/pdf";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".tif") || n.endsWith(".tiff")) return "image/tiff";
        return "application/octet-stream";
    }
}
