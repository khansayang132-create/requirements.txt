package com.taikatranslator.validation;

import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;

import static com.taikatranslator.validation.ArtifactValidator.Type.*;
import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.4 and TSK-6.6. */
class ArtifactValidatorTest {

    @TempDir
    Path dir;

    private final ArtifactValidator v = new ArtifactValidator();

    private Path docx(String name, String text) throws Exception {
        Path p = dir.resolve(name);
        try (XWPFDocument d = new XWPFDocument(); OutputStream out = Files.newOutputStream(p)) {
            d.createParagraph().createRun().setText(text);
            d.write(out);
        }
        return p;
    }

    @Test
    void missingAndEmptyFilesFail() throws Exception {
        assertFalse(v.validate(dir.resolve("nope.docx"), DOCX).ok());
        Path empty = Files.createFile(dir.resolve("empty.pdf"));
        var r = v.validate(empty, PDF);
        assertEquals("file is empty", r.problems().get(0));
    }

    @Test
    void realDocxPassesAndRenamedTextFails() throws Exception {
        assertTrue(v.validate(docx("ok.docx", "Hola"), DOCX).ok());
        Path fake = Files.writeString(dir.resolve("fake.docx"), "not a zip");
        assertFalse(v.validate(fake, DOCX).ok());
    }

    @Test
    void zipThatIsNotADocxFails() throws Exception {
        Path zip = dir.resolve("x.docx");
        try (var out = new java.util.zip.ZipOutputStream(Files.newOutputStream(zip))) {
            out.putNextEntry(new java.util.zip.ZipEntry("hello.txt"));
            out.write("hi".getBytes(StandardCharsets.UTF_8));
            out.closeEntry();
        }
        var r = v.validate(zip, DOCX);
        assertFalse(r.ok());
        assertTrue(r.problems().get(0).startsWith("DOCX does not open"), r.problems().toString());
    }

    @Test
    void truncatedDocxFails() throws Exception {
        Path good = docx("good.docx", "Texto");
        byte[] bytes = Files.readAllBytes(good);
        Path cut = Files.write(dir.resolve("cut.docx"), java.util.Arrays.copyOf(bytes, bytes.length / 2));
        assertFalse(v.validate(cut, DOCX).ok());
    }

    @Test
    void pngSignatureAndDimensions() throws Exception {
        Path png = dir.resolve("mask.png");
        ImageIO.write(new BufferedImage(4, 3, BufferedImage.TYPE_INT_RGB), "png", png.toFile());
        assertTrue(v.validate(png, PNG).ok());
        Path jpegNamedPng = dir.resolve("wrong.png");
        ImageIO.write(new BufferedImage(4, 3, BufferedImage.TYPE_INT_RGB), "jpg", jpegNamedPng.toFile());
        assertFalse(v.validate(jpegNamedPng, PNG).ok());
    }

    @Test
    void pdfSignature() throws Exception {
        assertTrue(v.validate(Files.writeString(dir.resolve("a.pdf"), "%PDF-1.7\n..."), PDF).ok());
        assertFalse(v.validate(Files.writeString(dir.resolve("b.pdf"), "<html>"), PDF).ok());
    }

    @Test
    void jsonStructureAndRequiredFields() throws Exception {
        Path good = Files.writeString(dir.resolve("extract.json"), "{\"pages\":[],\"paragraphs\":[]}");
        assertTrue(v.validateJson(good, "pages", "paragraphs").ok());
        assertEquals("missing required field 'tables'", v.validateJson(good, "tables").problems().get(0));
        Path broken = Files.writeString(dir.resolve("broken.json"), "{\"pages\":[");
        assertFalse(v.validate(broken, JSON).ok());
    }

    @Test
    void stageValidatePublish() throws Exception {
        AtomicPublisher pub = new AtomicPublisher();
        Path target = dir.resolve("out/result.docx");
        Path staged = pub.stage(target);
        assertEquals(target.getParent(), staged.getParent(), "staged next to target so the move is a rename");
        try (XWPFDocument d = new XWPFDocument(); OutputStream out = Files.newOutputStream(staged)) {
            d.createParagraph().createRun().setText("Hola");
            d.write(out);
        }
        assertTrue(v.validate(staged, DOCX).ok());
        assertEquals(AtomicPublisher.Mode.ATOMIC, pub.publish(staged, target, false));
        assertTrue(Files.exists(target));
        assertFalse(Files.exists(staged));
    }

    @Test
    void neverOverwritesSilently() throws Exception {
        AtomicPublisher pub = new AtomicPublisher();
        Path target = Files.writeString(dir.resolve("result.docx"), "previous run");
        Path staged = pub.stage(target);
        Files.writeString(staged, "new run");
        assertThrows(FileAlreadyExistsException.class, () -> pub.publish(staged, target, false));
        assertEquals("previous run", Files.readString(target));
        pub.publish(staged, target, true);
        assertEquals("new run", Files.readString(target));
    }

    @Test
    void failedValidationCanKeepDiagnostics() throws Exception {
        AtomicPublisher pub = new AtomicPublisher();
        Path target = dir.resolve("result.docx");
        Path staged = pub.stage(target);
        Files.writeString(staged, "garbage");
        assertFalse(v.validate(staged, DOCX).ok());
        pub.discard(staged, true);
        assertFalse(Files.exists(target));
        try (var s = Files.list(dir)) {
            assertTrue(s.anyMatch(p -> p.getFileName().toString().endsWith(".failed")));
        }
    }
}
