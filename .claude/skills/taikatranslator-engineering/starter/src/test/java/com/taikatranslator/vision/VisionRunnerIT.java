package com.taikatranslator.vision;

import com.taikatranslator.vision.VisionRunner.Failure;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import javax.imageio.ImageIO;
import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Graphics2D;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.List;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;

/**
 * The Java/Python contract. Fake scripts prove timeout, exit-code mapping and
 * output validation; the real segmenter runs when python3 with Pillow and numpy exists.
 */
class VisionRunnerIT {

    private static final Path SEGMENTER = Path.of("vision", "segmenter.py");
    private static boolean pythonReady;

    @TempDir
    Path tmp;

    @BeforeAll
    static void probe() throws Exception {
        try {
            Process p = new ProcessBuilder("python3", "-c", "import PIL, numpy").redirectErrorStream(true).start();
            pythonReady = p.waitFor(30, TimeUnit.SECONDS) && p.exitValue() == 0;
        } catch (java.io.IOException e) {
            pythonReady = false;
        }
    }

    /** Skips without Python, unless VISION_REQUIRED is set (CI), where a skip would hide a broken setup. */
    private static void requirePython() {
        if (System.getenv("VISION_REQUIRED") != null) assertTrue(pythonReady, "VISION_REQUIRED is set but python3 with Pillow+numpy is missing");
        Assumptions.assumeTrue(pythonReady, "python3 with Pillow and numpy not available: NOT RUN");
    }

    private Path script(String body) throws Exception {
        return Files.writeString(tmp.resolve("fake_" + Math.abs(body.hashCode()) + ".py"), body);
    }

    private Path page() throws Exception {
        BufferedImage img = new BufferedImage(850, 1100, BufferedImage.TYPE_INT_RGB);
        Graphics2D g = img.createGraphics();
        g.setColor(Color.WHITE);
        g.fillRect(0, 0, 850, 1100);
        g.setColor(new Color(20, 20, 20));
        for (int i = 0; i < 10; i++) g.fillRect(80, 100 + i * 40, 620, 12);
        g.setColor(new Color(200, 30, 40));
        g.setStroke(new BasicStroke(10));
        g.drawOval(560, 760, 200, 200);
        g.dispose();
        Path p = tmp.resolve("page.png");
        ImageIO.write(img, "png", p.toFile());
        return p;
    }

    @Test
    void realSegmenterFindsTheStampAndProducesValidOutputs() throws Exception {
        requirePython();
        VisionRunner.Result r = new VisionRunner(List.of("python3"), SEGMENTER, Duration.ofSeconds(60)).run(page(), tmp.resolve("out"));
        assertEquals(1, r.artifacts().size(), r.toString());
        VisionRunner.Artifact a = r.artifacts().get(0);
        assertEquals(VisionRunner.Kind.STAMP, a.kind());
        assertEquals(560 / 850.0, a.box().x(), 0.03);
        assertEquals(760 / 1100.0, a.box().y(), 0.03);
        assertFalse(r.limitations().isEmpty(), "the baseline states its limitations");
    }

    @Test
    void hangingScriptIsKilledAtTheTimeout() throws Exception {
        requirePython();
        Path hang = script("import time\ntime.sleep(60)\n");
        long start = System.nanoTime();
        var e = assertThrows(VisionRunner.VisionException.class,
                () -> new VisionRunner(List.of("python3"), hang, Duration.ofMillis(800)).run(page(), tmp.resolve("o")));
        assertEquals(Failure.TIMEOUT, e.failure);
        assertTrue(Duration.ofNanos(System.nanoTime() - start).toSeconds() < 15, "did not wait for the script to finish");
    }

    @Test
    void exitCodesAreMapped() throws Exception {
        requirePython();
        record Case(int code, Failure failure) { }
        for (Case c : List.of(new Case(2, Failure.USAGE), new Case(3, Failure.BAD_INPUT), new Case(4, Failure.INTERNAL), new Case(1, Failure.INTERNAL))) {
            Path s = script("import sys\nsys.stderr.write('boom %d')\nsys.exit(" + c.code + ")\n");
            var e = assertThrows(VisionRunner.VisionException.class,
                    () -> new VisionRunner(List.of("python3"), s, Duration.ofSeconds(30)).run(page(), tmp.resolve("o" + c.code)));
            assertEquals(c.failure, e.failure);
            assertTrue(e.getMessage().contains("boom"), "stderr captured for diagnosis");
        }
    }

    @Test
    void zeroExitWithBadOutputIsInvalidOutput() throws Exception {
        requirePython();
        Path liar = script("import sys, os\nout = sys.argv[sys.argv.index('--out-dir') + 1]\nos.makedirs(out, exist_ok=True)\n"
                + "open(os.path.join(out, 'artifacts.json'), 'w').write('{\"schemaVersion\": 1, \"image\": {}, \"artifacts\": []}')\n"
                + "open(os.path.join(out, 'mask.png'), 'w').write('not a png')\n");
        var e = assertThrows(VisionRunner.VisionException.class,
                () -> new VisionRunner(List.of("python3"), liar, Duration.ofSeconds(30)).run(page(), tmp.resolve("o")));
        assertEquals(Failure.INVALID_OUTPUT, e.failure);
    }

    @Test
    void artifactValuesAreValidated() throws Exception {
        VisionRunner runner = new VisionRunner(List.of("python3"), SEGMENTER, Duration.ofSeconds(1));
        Path out = Files.createDirectories(tmp.resolve("v"));
        BufferedImage img = new BufferedImage(10, 10, BufferedImage.TYPE_INT_RGB);
        ImageIO.write(img, "png", out.resolve("mask.png").toFile());
        ImageIO.write(img, "png", out.resolve("cleaned.png").toFile());
        String[] bad = {
                "{\"schemaVersion\":2,\"image\":{},\"artifacts\":[]}",
                "{\"schemaVersion\":1,\"image\":{},\"artifacts\":[{\"kind\":\"logo\",\"bbox_norm\":[0,0,0.1,0.1],\"confidence\":0.5}]}",
                "{\"schemaVersion\":1,\"image\":{},\"artifacts\":[{\"kind\":\"stamp\",\"bbox_norm\":[0,0,0.1],\"confidence\":0.5}]}",
                "{\"schemaVersion\":1,\"image\":{},\"artifacts\":[{\"kind\":\"stamp\",\"bbox_norm\":[0.9,0,0.5,0.1],\"confidence\":0.5}]}",
                "{\"schemaVersion\":1,\"image\":{},\"artifacts\":[{\"kind\":\"stamp\",\"bbox_norm\":[0,0,0.1,0.1],\"confidence\":7}]}"};
        for (String b : bad) {
            Files.writeString(out.resolve("artifacts.json"), b);
            assertEquals(Failure.INVALID_OUTPUT, assertThrows(VisionRunner.VisionException.class, () -> runner.readOutputs(out)).failure, b);
        }
    }

    @Test
    void missingInterpreterOrScriptIsNotAvailable() throws Exception {
        assertEquals(Failure.NOT_AVAILABLE, assertThrows(VisionRunner.VisionException.class,
                () -> new VisionRunner(List.of("python3"), tmp.resolve("nope.py"), Duration.ofSeconds(1)).run(page(), tmp.resolve("o"))).failure);
        Path s = script("print(1)\n");
        assertEquals(Failure.NOT_AVAILABLE, assertThrows(VisionRunner.VisionException.class,
                () -> new VisionRunner(List.of("/definitely/not/python"), s, Duration.ofSeconds(1)).run(page(), tmp.resolve("o"))).failure);
    }
}
