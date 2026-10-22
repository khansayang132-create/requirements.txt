package com.taikatranslator.reporting;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.PrintStream;
import java.time.Clock;
import java.util.Map;
import java.util.Objects;

/**
 * One JSON object per line, every line carrying the run's {@code runId}.
 * Field values pass through {@link Redactor}. Never pass document text here;
 * log counts and ids instead. In a project that already uses SLF4J/Logback,
 * put runId in the MDC and use a JSON encoder; the event shape stays the same.
 */
public final class RunLog {
    private final ObjectMapper json = new ObjectMapper();
    private final String runId;
    private final Clock clock;
    private final PrintStream out;

    public RunLog(String runId, Clock clock, PrintStream out) {
        this.runId = Objects.requireNonNull(runId);
        this.clock = Objects.requireNonNull(clock);
        this.out = Objects.requireNonNull(out);
    }

    public String runId() {
        return runId;
    }

    public void event(String level, String stage, String event, Map<String, ?> fields) {
        ObjectNode n = json.createObjectNode();
        n.put("timestamp", clock.instant().toString());
        n.put("level", level);
        n.put("runId", runId);
        n.put("stage", stage);
        n.put("event", event);
        fields.forEach((k, v) -> {
            if (v == null) n.putNull(k);
            else if (v instanceof Number num) n.putPOJO(k, num);
            else if (v instanceof Boolean b) n.put(k, b);
            else n.put(k, Redactor.redact(v.toString()));
        });
        out.println(n.toString());
    }

    public void info(String stage, String event, Map<String, ?> fields) {
        event("INFO", stage, event, fields);
    }

    public void warn(String stage, String event, Map<String, ?> fields) {
        event("WARN", stage, event, fields);
    }

    public void error(String stage, String event, Map<String, ?> fields) {
        event("ERROR", stage, event, fields);
    }
}
