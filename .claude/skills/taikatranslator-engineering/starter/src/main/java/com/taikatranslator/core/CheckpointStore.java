package com.taikatranslator.core;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Optional;

/**
 * TSK-6.8. Records each completed stage's output so an interrupted job can resume.
 *
 * <p>A checkpoint is reused only if the input hash AND the config fingerprint
 * match AND the output file still exists with the recorded SHA-256. Anything
 * else is treated as absent: a stale resume is worse than a re-run.
 * Checkpoint files are written to a temp name and renamed, so a crash mid-write
 * never leaves a half checkpoint.
 */
public final class CheckpointStore {

    public enum Miss { NONE, ABSENT, INPUT_CHANGED, CONFIG_CHANGED, OUTPUT_MISSING, OUTPUT_CHANGED, CORRUPT }

    public record Lookup(Optional<Path> output, Miss miss) {
        public boolean hit() {
            return output.isPresent();
        }
    }

    private final Path dir;
    private final ObjectMapper json = new ObjectMapper();

    public CheckpointStore(Path dir) throws IOException {
        this.dir = Files.createDirectories(dir);
    }

    public void record(String stage, String inputSha256, String configFingerprint, Path output) throws IOException {
        ObjectNode n = json.createObjectNode();
        n.put("stage", stage);
        n.put("inputSha256", inputSha256);
        n.put("configFingerprint", configFingerprint);
        n.put("output", output.toAbsolutePath().toString());
        n.put("outputSha256", sha256(output));
        Path file = file(stage);
        Path tmp = dir.resolve("." + file.getFileName() + ".tmp");
        json.writeValue(tmp.toFile(), n);
        Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    }

    public Lookup find(String stage, String inputSha256, String configFingerprint) {
        Path file = file(stage);
        if (!Files.exists(file)) return new Lookup(Optional.empty(), Miss.ABSENT);
        try {
            JsonNode n = json.readTree(file.toFile());
            if (!inputSha256.equals(n.path("inputSha256").asText())) return new Lookup(Optional.empty(), Miss.INPUT_CHANGED);
            if (!configFingerprint.equals(n.path("configFingerprint").asText())) return new Lookup(Optional.empty(), Miss.CONFIG_CHANGED);
            Path out = Path.of(n.path("output").asText());
            if (!Files.isRegularFile(out)) return new Lookup(Optional.empty(), Miss.OUTPUT_MISSING);
            if (!sha256(out).equals(n.path("outputSha256").asText())) return new Lookup(Optional.empty(), Miss.OUTPUT_CHANGED);
            return new Lookup(Optional.of(out), Miss.NONE);
        } catch (IOException | RuntimeException e) {
            return new Lookup(Optional.empty(), Miss.CORRUPT);
        }
    }

    private Path file(String stage) {
        if (!stage.matches("[a-z0-9-]{1,40}")) throw new IllegalArgumentException("stage name must be [a-z0-9-]{1,40}");
        return dir.resolve(stage + ".checkpoint.json");
    }

    public static String sha256(Path p) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            try (var in = Files.newInputStream(p)) {
                byte[] buf = new byte[64 * 1024];
                for (int n; (n = in.read(buf)) > 0; ) md.update(buf, 0, n);
            }
            return HexFormat.of().formatHex(md.digest());
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
