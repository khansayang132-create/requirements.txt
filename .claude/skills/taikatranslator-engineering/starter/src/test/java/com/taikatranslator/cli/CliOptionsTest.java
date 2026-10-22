package com.taikatranslator.cli;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.1. */
class CliOptionsTest {

    @FunctionalInterface
    interface ThrowingCall {
        Object run() throws Exception;
    }

    @TempDir
    Path dir;

    private Path pdf(String name) throws Exception {
        Path p = dir.resolve(name);
        Files.createDirectories(p.getParent());
        return Files.writeString(p, "%PDF-1.7\n");
    }

    private static CliOptions.CliException fails(ExitCode code, ThrowingCall call) {
        CliOptions.CliException e = assertThrows(CliOptions.CliException.class, call::run);
        assertEquals(code, e.exitCode, e.getMessage());
        return e;
    }

    @Test
    void validArgumentsWithSpacesInPaths() throws Exception {
        Path in = pdf("my docs/contrato final.pdf");
        Path out = dir.resolve("salida con espacios");
        CliOptions o = CliOptions.parse(new String[]{"--input", in.toString(), "--output-dir", out.toString(), "--target-lang", "es"});
        assertEquals("ES", o.targetLang());
        Path docx = o.validateFilesystem();
        assertEquals("contrato final.ES.docx", docx.getFileName().toString());
        assertTrue(Files.isDirectory(out), "output dir created");
    }

    @Test
    void missingRequiredArgumentsPrintUsage() {
        var e = fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--output-dir", "x", "--target-lang", "ES"}));
        assertTrue(e.getMessage().contains("Usage:"));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--input", "a.pdf", "--target-lang", "ES"}));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--input", "a.pdf", "--output-dir", "x"}));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--input"}));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--input", "--output-dir"}));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--bogus"}));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--help"}));
    }

    @Test
    void invalidLanguageCodesAreRejected() {
        String[] base = {"--input", "a.pdf", "--output-dir", "x", "--target-lang"};
        fails(ExitCode.USAGE, () -> CliOptions.parse(concat(base, "spanish")));
        var e = fails(ExitCode.USAGE, () -> CliOptions.parse(concat(base, "EN")));
        assertTrue(e.getMessage().contains("EN-US"));
        fails(ExitCode.USAGE, () -> CliOptions.parse(concat(base, "PT")));
        fails(ExitCode.USAGE, () -> CliOptions.parse(new String[]{"--input", "a.pdf", "--output-dir", "x", "--target-lang", "ES", "--source-lang", "EN-US"}));
    }

    @Test
    void missingInputFile() {
        fails(ExitCode.INPUT_ERROR, () -> CliOptions.parse(new String[]{"--input", dir.resolve("none.pdf").toString(),
                "--output-dir", dir.toString(), "--target-lang", "ES"}).validateFilesystem());
    }

    @Test
    void unsupportedTypeAndMismatchedContent() throws Exception {
        Path docx = Files.writeString(dir.resolve("a.docx"), "x");
        fails(ExitCode.INPUT_ERROR, () -> CliOptions.parse(new String[]{"--input", docx.toString(),
                "--output-dir", dir.toString(), "--target-lang", "ES"}).validateFilesystem());
        Path fakePdf = Files.writeString(dir.resolve("fake.pdf"), "<html>");
        var e = fails(ExitCode.INPUT_ERROR, () -> CliOptions.parse(new String[]{"--input", fakePdf.toString(),
                "--output-dir", dir.toString(), "--target-lang", "ES"}).validateFilesystem());
        assertTrue(e.getMessage().contains("does not match"));
    }

    @Test
    void directoryAsInputIsRejected() {
        fails(ExitCode.INPUT_ERROR, () -> CliOptions.parse(new String[]{"--input", dir.toString(),
                "--output-dir", dir.toString(), "--target-lang", "ES"}).validateFilesystem());
    }

    @Test
    void outputDirThatIsAFileIsRejected() throws Exception {
        Path in = pdf("a.pdf");
        Path file = Files.writeString(dir.resolve("not-a-dir"), "x");
        fails(ExitCode.INPUT_ERROR, () -> CliOptions.parse(new String[]{"--input", in.toString(),
                "--output-dir", file.toString(), "--target-lang", "ES"}).validateFilesystem());
    }

    @Test
    void existingResultIsNotOverwrittenWithoutFlag() throws Exception {
        Path in = pdf("doc.pdf");
        Files.writeString(dir.resolve("doc.ES.docx"), "old");
        fails(ExitCode.OUTPUT_EXISTS, () -> CliOptions.parse(new String[]{"--input", in.toString(),
                "--output-dir", dir.toString(), "--target-lang", "ES"}).validateFilesystem());
        assertNotNull(CliOptions.parse(new String[]{"--input", in.toString(), "--output-dir", dir.toString(),
                "--target-lang", "ES", "--overwrite"}).validateFilesystem());
    }

    @Test
    void imageInputsAreSniffed() throws Exception {
        Path jpg = Files.write(dir.resolve("scan.JPG"), new byte[]{(byte) 0xFF, (byte) 0xD8, (byte) 0xFF, 0x00});
        assertNotNull(CliOptions.parse(new String[]{"--input", jpg.toString(), "--output-dir", dir.toString(),
                "--target-lang", "ES"}).validateFilesystem());
        Path tif = Files.write(dir.resolve("scan.tiff"), new byte[]{'I', 'I', 42, 0, 8, 0, 0, 0});
        assertNotNull(CliOptions.parse(new String[]{"--input", tif.toString(), "--output-dir", dir.toString(),
                "--target-lang", "EN-GB"}).validateFilesystem());
    }

    @Test
    void exitCodesAreDistinct() {
        assertEquals(ExitCode.values().length, java.util.Arrays.stream(ExitCode.values()).mapToInt(c -> c.code).distinct().count());
        assertEquals(0, ExitCode.OK.code);
        assertEquals(2, ExitCode.USAGE.code);
    }

    private static String[] concat(String[] a, String b) {
        String[] out = java.util.Arrays.copyOf(a, a.length + 1);
        out[a.length] = b;
        return out;
    }
}
