package com.taikatranslator.bench;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.taikatranslator.layout.AwtTextMeasurer;
import com.taikatranslator.pipeline.ReferencePipeline;
import com.taikatranslator.provider.Translator;
import com.taikatranslator.reporting.ProcessingReport;
import com.taikatranslator.reporting.RunLog;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.awt.Font;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.PrintStream;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.MemoryType;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Clock;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/**
 * TSK-6.9 / TSK-7.2 harness: times the local pipeline (mapping, translation
 * plumbing, layout fitting with real Carlito metrics, DOCX writing, validation,
 * inspection) on the fixture with in-process providers. Network time is
 * excluded on purpose; it belongs to the providers and is measured by live runs.
 *
 * <p>Default 5 measured iterations after 2 warm-ups, so CI stays fast.
 * For a baseline: {@code mvn verify -Dit.test=FixtureBenchmarkIT -Dbench.iterations=200}.
 * Writes target/benchmark/fixture-benchmark.json. No thresholds are asserted:
 * targets are set from a recorded baseline, not guessed.
 */
class FixtureBenchmarkIT {

    private static final ObjectMapper JSON = new ObjectMapper();

    @TempDir
    Path work;

    @Test
    void measuresTheLocalPipeline() throws Exception {
        int iterations = Integer.getInteger("bench.iterations", 5);
        int warmups = 2;
        JsonNode azure;
        Map<String, String> dictionary = new HashMap<>();
        try (InputStream a = res("mocks/azure-layout-service-agreement.json"); InputStream d = res("mocks/deepl-es-service-agreement.json")) {
            azure = JSON.readTree(a).get("analyzeResult");
            JSON.readTree(d).fields().forEachRemaining(e -> dictionary.put(e.getKey(), e.getValue().asText()));
        }
        Path input = work.resolve("in.pdf");
        try (InputStream in = res("fixtures/service-agreement.pdf")) {
            Files.copy(in, input, StandardCopyOption.REPLACE_EXISTING);
        }
        Translator translator = r -> {
            List<String> out = new ArrayList<>();
            for (String t : r.texts()) out.add(lookup(dictionary.get(t), t));
            return new Translator.Response(out, Optional.of("EN"), 0);
        };
        AwtTextMeasurer measurer = new AwtTextMeasurer("Carlito", Font.PLAIN);
        PrintStream sink = new PrintStream(OutputStream.nullOutputStream());
        int pages = azure.get("pages").size();

        resetPeaks();
        List<Long> nanos = new ArrayList<>();
        for (int i = 0; i < warmups + iterations; i++) {
            Path out = work.resolve("out-" + i + ".docx");
            ReferencePipeline p = new ReferencePipeline(doc -> azure, translator, measurer, Clock.systemUTC(),
                    new RunLog("bench-" + i, Clock.systemUTC(), sink));
            long t0 = System.nanoTime();
            ProcessingReport r = p.run(input, out, "ES", false);
            long dt = System.nanoTime() - t0;
            assertNotEquals(ProcessingReport.Status.FAILED, r.overall(), "benchmark runs must succeed");
            if (i >= warmups) nanos.add(dt);
            Files.deleteIfExists(out);
        }
        Collections.sort(nanos);
        double medianMs = nanos.get(nanos.size() / 2) / 1e6;
        double p95Ms = nanos.get(Math.min(nanos.size() - 1, (int) Math.ceil(nanos.size() * 0.95) - 1)) / 1e6;

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("what", "local pipeline on the synthetic fixture; providers in-process; network excluded");
        result.put("iterations", iterations);
        result.put("warmups", warmups);
        result.put("pages", pages);
        result.put("medianMsPerDocument", round(medianMs));
        result.put("p95MsPerDocument", round(p95Ms));
        result.put("medianMsPerPage", round(medianMs / pages));
        result.put("peakHeapMb", round(peakHeapBytes() / 1048576.0));
        result.put("java", System.getProperty("java.version"));
        result.put("cpus", Runtime.getRuntime().availableProcessors());
        result.put("measurerFont", measurer.resolvedFamily());
        Path dir = Files.createDirectories(Path.of("target", "benchmark"));
        JSON.enable(SerializationFeature.INDENT_OUTPUT).writeValue(dir.resolve("fixture-benchmark.json").toFile(), result);

        assertTrue(medianMs > 0 && p95Ms >= medianMs, result.toString());
        System.out.println("benchmark: " + result);
    }

    private static String lookup(String v, String key) {
        if (v == null) throw new IllegalStateException("no fixture translation for a block");
        return v;
    }

    private static InputStream res(String path) {
        InputStream in = FixtureBenchmarkIT.class.getClassLoader().getResourceAsStream(path);
        assertNotNull(in, path);
        return in;
    }

    private static void resetPeaks() {
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans()) pool.resetPeakUsage();
    }

    private static long peakHeapBytes() {
        long sum = 0;
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans())
            if (pool.getType() == MemoryType.HEAP && pool.getPeakUsage() != null) sum += pool.getPeakUsage().getUsed();
        return sum;
    }

    private static double round(double v) {
        return Math.round(v * 100) / 100.0;
    }
}
