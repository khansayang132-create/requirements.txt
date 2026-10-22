package com.taikatranslator.vision;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.taikatranslator.geometry.NormalizedBox;
import com.taikatranslator.validation.ArtifactValidator;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.TimeUnit;

/**
 * Runs the Python vision stage (vision/segmenter.py) as a subprocess.
 *
 * <ul>
 *   <li>Paths only on the command line; document content never goes through arguments or env.</li>
 *   <li>Hard timeout: the process tree is destroyed and the failure is {@link Failure#TIMEOUT}.</li>
 *   <li>Exit codes are mapped (2 usage, 3 bad input, 4 internal) instead of "it failed".</li>
 *   <li>Outputs are validated before use: artifacts.json schema and values, mask.png and
 *       cleaned.png as real PNGs. A zero exit with bad output is {@link Failure#INVALID_OUTPUT}.</li>
 *   <li>stderr is captured (truncated) for the report; stdout is ignored except as a liveness hint.</li>
 * </ul>
 */
public final class VisionRunner {

    public enum Failure { NOT_AVAILABLE, TIMEOUT, USAGE, BAD_INPUT, INTERNAL, INVALID_OUTPUT }

    public static final class VisionException extends Exception {
        public final Failure failure;

        VisionException(Failure failure, String message) {
            super("vision " + failure + ": " + message);
            this.failure = failure;
        }
    }

    public enum Kind { STAMP, SIGNATURE, UNKNOWN_MARK }

    public record Artifact(Kind kind, NormalizedBox box, double confidence) { }

    public record Result(List<Artifact> artifacts, Path mask, Path cleaned, List<String> limitations) { }

    private final List<String> python;
    private final Path script;
    private final Duration timeout;
    private final ObjectMapper json = new ObjectMapper();
    private final ArtifactValidator validator = new ArtifactValidator();

    /** @param python e.g. List.of("python3") or List.of("/opt/venv/bin/python", "-I") */
    public VisionRunner(List<String> python, Path script, Duration timeout) {
        this.python = List.copyOf(python);
        this.script = Objects.requireNonNull(script);
        this.timeout = Objects.requireNonNull(timeout);
    }

    public Result run(Path pageImage, Path outDir) throws VisionException, InterruptedException {
        if (!Files.isRegularFile(script)) throw new VisionException(Failure.NOT_AVAILABLE, "script not found: " + script.getFileName());
        List<String> cmd = new ArrayList<>(python);
        cmd.addAll(List.of(script.toString(), "--input", pageImage.toString(), "--out-dir", outDir.toString()));
        Process p;
        Path stderr;
        try {
            Files.createDirectories(outDir);
            stderr = outDir.resolve("vision.stderr.txt");
            p = new ProcessBuilder(cmd).redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(stderr.toFile()).start();
        } catch (IOException e) {
            throw new VisionException(Failure.NOT_AVAILABLE, "cannot start " + python.get(0) + ": " + e.getClass().getSimpleName());
        }
        try {
            if (!p.waitFor(timeout.toMillis(), TimeUnit.MILLISECONDS)) {
                p.descendants().forEach(ProcessHandle::destroyForcibly);
                p.destroyForcibly();
                p.waitFor(5, TimeUnit.SECONDS);
                throw new VisionException(Failure.TIMEOUT, "no result within " + timeout);
            }
        } catch (InterruptedException e) {
            p.descendants().forEach(ProcessHandle::destroyForcibly);
            p.destroyForcibly();
            throw e;
        }
        int code = p.exitValue();
        String err = tail(stderr);
        switch (code) {
            case 0: break;
            case 2: throw new VisionException(Failure.USAGE, err);
            case 3: throw new VisionException(Failure.BAD_INPUT, err);
            default: throw new VisionException(Failure.INTERNAL, "exit " + code + ": " + err);
        }
        return readOutputs(outDir);
    }

    Result readOutputs(Path outDir) throws VisionException {
        Path report = outDir.resolve("artifacts.json"), mask = outDir.resolve("mask.png"), cleaned = outDir.resolve("cleaned.png");
        List<String> problems = new ArrayList<>();
        problems.addAll(validator.validateJson(report, "schemaVersion", "image", "artifacts").problems());
        problems.addAll(validator.validate(mask, ArtifactValidator.Type.PNG).problems());
        problems.addAll(validator.validate(cleaned, ArtifactValidator.Type.PNG).problems());
        if (!problems.isEmpty()) throw new VisionException(Failure.INVALID_OUTPUT, String.join("; ", problems));
        try {
            JsonNode root = json.readTree(report.toFile());
            if (root.path("schemaVersion").asInt() != 1)
                throw new VisionException(Failure.INVALID_OUTPUT, "unsupported schemaVersion " + root.path("schemaVersion"));
            List<Artifact> out = new ArrayList<>();
            for (JsonNode a : root.path("artifacts")) {
                Kind kind;
                try {
                    kind = Kind.valueOf(a.path("kind").asText().toUpperCase());
                } catch (IllegalArgumentException e) {
                    throw new VisionException(Failure.INVALID_OUTPUT, "unknown artifact kind '" + a.path("kind").asText() + "'");
                }
                JsonNode b = a.path("bbox_norm");
                if (!b.isArray() || b.size() != 4) throw new VisionException(Failure.INVALID_OUTPUT, "bbox_norm must have 4 numbers");
                double conf = a.path("confidence").asDouble(Double.NaN);
                if (!(conf >= 0 && conf <= 1)) throw new VisionException(Failure.INVALID_OUTPUT, "confidence outside [0,1]");
                NormalizedBox box;
                try {
                    box = new NormalizedBox(b.get(0).asDouble(), b.get(1).asDouble(), b.get(2).asDouble(), b.get(3).asDouble());
                } catch (RuntimeException e) {
                    throw new VisionException(Failure.INVALID_OUTPUT, "bad bbox: " + e.getMessage());
                }
                out.add(new Artifact(kind, box, conf));
            }
            List<String> limitations = new ArrayList<>();
            root.path("limitations").forEach(l -> limitations.add(l.asText()));
            return new Result(out, mask, cleaned, limitations);
        } catch (IOException e) {
            throw new VisionException(Failure.INVALID_OUTPUT, "artifacts.json unreadable");
        }
    }

    private static String tail(Path p) {
        try {
            String s = Files.readString(p, StandardCharsets.UTF_8).strip();
            return s.length() <= 500 ? s : "..." + s.substring(s.length() - 500);
        } catch (IOException e) {
            return "";
        }
    }
}
