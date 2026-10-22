package com.taikatranslator.reporting;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.io.IOException;
import java.nio.file.Path;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Machine-readable record of a run: the evidence for the six acceptance gates.
 * Schema: templates/processing-report.schema.json in the skill folder.
 */
public final class ProcessingReport {

    public enum Status { SUCCESS, SUCCESS_WITH_WARNINGS, FAILED, SKIPPED }

    public record Stage(String name, Status status, long durationMs, int retries,
                        Map<String, Number> counts, List<String> warnings, String errorCategory) { }

    public record Artifact(String role, String path, String sha256, long bytes, boolean valid, List<String> problems) { }

    public record Gate(String name, boolean passed, String evidence) { }

    private final String runId;
    private final Instant startedAt;
    private final Clock clock;
    private final Map<String, String> environment = new LinkedHashMap<>();
    private final Map<String, Object> inputs = new LinkedHashMap<>();
    private final List<Stage> stages = new ArrayList<>();
    private final List<Artifact> artifacts = new ArrayList<>();
    private final List<Gate> gates = new ArrayList<>();

    public ProcessingReport(String runId, Clock clock) {
        this.runId = runId;
        this.clock = clock;
        this.startedAt = clock.instant();
    }

    public ProcessingReport environment(String key, String value) {
        environment.put(key, Redactor.redact(value));
        return this;
    }

    /** Record input facts (file name, sha256, page count, languages). Never document text or keys. */
    public ProcessingReport input(String key, Object value) {
        inputs.put(key, value);
        return this;
    }

    public void stage(String name, Status status, Duration duration, int retries,
                      Map<String, Number> counts, List<String> warnings, String errorCategory) {
        stages.add(new Stage(name, status, duration.toMillis(), retries, Map.copyOf(counts), List.copyOf(warnings), errorCategory));
    }

    public void artifact(Artifact a) {
        artifacts.add(a);
    }

    public void gate(String name, boolean passed, String evidence) {
        gates.add(new Gate(name, passed, evidence));
    }

    /** FAILED if any stage failed or any gate failed; warnings downgrade SUCCESS. */
    public Status overall() {
        if (stages.isEmpty()) return Status.FAILED;
        boolean warn = false;
        for (Stage s : stages) {
            if (s.status() == Status.FAILED) return Status.FAILED;
            if (s.status() == Status.SUCCESS_WITH_WARNINGS) warn = true;
        }
        for (Gate g : gates) if (!g.passed()) return Status.FAILED;
        for (Artifact a : artifacts) if (!a.valid()) return Status.FAILED;
        return warn ? Status.SUCCESS_WITH_WARNINGS : Status.SUCCESS;
    }

    public Map<String, Object> toMap() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("schemaVersion", 1);
        m.put("runId", runId);
        m.put("startedAt", startedAt.toString());
        m.put("finishedAt", clock.instant().toString());
        m.put("status", overall().name());
        m.put("environment", environment);
        m.put("inputs", inputs);
        m.put("stages", stages);
        m.put("artifacts", artifacts);
        m.put("gates", gates);
        return m;
    }

    public void write(Path path) throws IOException {
        new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT).writeValue(path.toFile(), toMap());
    }
}
