package com.taikatranslator.validation;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.poi.xwpf.usermodel.XWPFDocument;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/**
 * Checks a produced file before anything reports it as a success.
 * A filename existing is not evidence. Problems are collected, not thrown,
 * so the processing report can list all of them.
 */
public final class ArtifactValidator {

    public enum Type { PDF, PNG, DOCX, JSON }

    public record Result(Path path, Type type, List<String> problems) {
        public Result {
            problems = List.copyOf(problems);
        }

        public boolean ok() {
            return problems.isEmpty();
        }
    }

    private static final byte[] PDF_MAGIC = {'%', 'P', 'D', 'F', '-'};
    private static final byte[] PNG_MAGIC = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
    private static final byte[] ZIP_MAGIC = {'P', 'K', 3, 4};

    private final ObjectMapper json = new ObjectMapper();

    public Result validate(Path path, Type type) {
        List<String> problems = new ArrayList<>();
        if (!Files.isRegularFile(path)) {
            problems.add("missing or not a regular file");
            return new Result(path, type, problems);
        }
        try {
            long size = Files.size(path);
            if (size == 0) {
                problems.add("file is empty");
                return new Result(path, type, problems);
            }
            switch (type) {
                case PDF -> checkMagic(path, PDF_MAGIC, "PDF", problems);
                case PNG -> checkPng(path, problems);
                case DOCX -> checkDocx(path, problems);
                case JSON -> checkJson(path, problems);
            }
        } catch (IOException e) {
            problems.add("unreadable: " + e.getClass().getSimpleName());
        }
        return new Result(path, type, problems);
    }

    /** Also asserts required JSON fields exist, e.g. "pages", "paragraphs". */
    public Result validateJson(Path path, String... requiredFields) {
        Result base = validate(path, Type.JSON);
        if (!base.ok()) return base;
        List<String> problems = new ArrayList<>();
        try {
            JsonNode root = json.readTree(path.toFile());
            for (String f : requiredFields) if (!root.has(f)) problems.add("missing required field '" + f + "'");
        } catch (IOException e) {
            problems.add("invalid JSON");
        }
        return new Result(path, Type.JSON, problems);
    }

    private static void checkMagic(Path path, byte[] magic, String label, List<String> problems) throws IOException {
        byte[] head = readHead(path, magic.length);
        if (!Arrays.equals(head, magic)) problems.add("not a " + label + " file (bad signature)");
    }

    private static void checkPng(Path path, List<String> problems) throws IOException {
        byte[] head = readHead(path, 24);
        if (head.length < 24 || !Arrays.equals(Arrays.copyOf(head, 8), PNG_MAGIC)) {
            problems.add("not a PNG file (bad signature)");
            return;
        }
        // First chunk must be IHDR with non-zero width and height (big-endian).
        if (head[12] != 'I' || head[13] != 'H' || head[14] != 'D' || head[15] != 'R') {
            problems.add("PNG first chunk is not IHDR");
            return;
        }
        long w = readUInt(head, 16), h = readUInt(head, 20);
        if (w == 0 || h == 0) problems.add("PNG has zero width or height");
    }

    private static void checkDocx(Path path, List<String> problems) throws IOException {
        checkMagic(path, ZIP_MAGIC, "ZIP/DOCX", problems);
        if (!problems.isEmpty()) return;
        try (InputStream in = Files.newInputStream(path); XWPFDocument doc = new XWPFDocument(in)) {
            if (doc.getBodyElements().isEmpty()) problems.add("DOCX opens but has no body elements");
        } catch (Exception e) {
            problems.add("DOCX does not open in Apache POI: " + e.getClass().getSimpleName());
        }
    }

    private void checkJson(Path path, List<String> problems) {
        try {
            json.readTree(path.toFile());
        } catch (IOException e) {
            problems.add("invalid JSON");
        }
    }

    private static byte[] readHead(Path path, int n) throws IOException {
        try (InputStream in = Files.newInputStream(path)) {
            return in.readNBytes(n);
        }
    }

    private static long readUInt(byte[] b, int off) {
        return ((b[off] & 0xFFL) << 24) | ((b[off + 1] & 0xFFL) << 16) | ((b[off + 2] & 0xFFL) << 8) | (b[off + 3] & 0xFFL);
    }
}
