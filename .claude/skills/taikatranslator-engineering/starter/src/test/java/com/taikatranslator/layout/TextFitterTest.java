package com.taikatranslator.layout;

import org.junit.jupiter.api.Test;

import java.awt.Font;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-5.2.3. Uses a fixed-advance measurer so results don't depend on installed fonts. */
class TextFitterTest {

    // Each code point is 0.5 em wide: at 10 pt a character is 5 pt.
    private final TextMeasurer mono = new FixedAdvanceMeasurer(0.5);
    private final TextFitter.Config cfg = new TextFitter.Config(6, 12, 0.5, 1.2);
    private final TextFitter fitter = new TextFitter(mono, cfg);

    private static void assertSane(TextFitter.Result r, TextFitter.Config c) {
        assertTrue(Double.isFinite(r.fontSizePt()), "finite");
        assertTrue(r.fontSizePt() > 0, "positive");
        assertTrue(r.fontSizePt() >= c.minSizePt() && r.fontSizePt() <= c.maxSizePt(), "within limits");
    }

    private static String joinedNoSpaces(List<String> lines) {
        return String.join("", lines).replace(" ", "");
    }

    @Test
    void shorterTranslationKeepsMaximumSize() {
        var r = fitter.fit("Hola", 200, 30);
        assertEquals(12, r.fontSizePt());
        assertFalse(r.overflow());
        assertEquals(List.of("Hola"), r.lines());
    }

    @Test
    void longerTranslationShrinksUntilItFits() {
        // English "Total amount due" (16 chars) became Spanish (29 chars) in a box sized for the English.
        String es = "Importe total a pagar ya mismo";
        var r = fitter.fit(es, 16 * 6, 12 * 1.2 + 0.01);
        assertSane(r, cfg);
        assertFalse(r.overflow());
        assertTrue(r.fontSizePt() < 12);
        for (String line : r.lines()) assertTrue(mono.width(line, r.fontSizePt()) <= 16 * 6 + 1e-6);
    }

    @Test
    void emptyAndBlankStrings() {
        for (String s : new String[]{"", "   ", "\n"}) {
            var r = fitter.fit(s, 100, 20);
            assertSane(r, cfg);
            assertFalse(r.overflow());
            assertTrue(r.warnings().isEmpty());
        }
    }

    @Test
    void veryLongStringOverflowsWithWarningAndNoTruncation() {
        String text = "palabra ".repeat(400).trim();
        var r = fitter.fit(text, 100, 40);
        assertSane(r, cfg);
        assertEquals(6, r.fontSizePt());
        assertTrue(r.overflow());
        assertEquals(1, r.warnings().size());
        assertEquals(text.replace(" ", ""), joinedNoSpaces(r.lines()), "every character kept");
    }

    @Test
    void unicodeAccentsAndMixedScriptCountCodePointsNotChars() {
        String text = "Çağrı ñandú — 東京 مرحبا 😀";
        var r = fitter.fit(text, 400, 30);
        assertSane(r, cfg);
        assertEquals(text.replace(" ", ""), joinedNoSpaces(r.lines()));
        // The emoji is one code point (two UTF-16 chars) and is measured as one.
        assertEquals(1 * 0.5 * 10, mono.width("😀", 10), 1e-9);
    }

    @Test
    void explicitLineBreaksArePreserved() {
        var r = fitter.fit("Línea uno\nLínea dos", 400, 100);
        assertEquals(List.of("Línea uno", "Línea dos"), r.lines());
        assertEquals(12, r.fontSizePt());
    }

    @Test
    void narrowTableCellBreaksLongWordsWithoutLosingCharacters() {
        String word = "Datenschutzgrundverordnung";
        var r = fitter.fit(word, 20, 400);
        assertSane(r, cfg);
        assertTrue(r.lines().size() > 1);
        assertEquals(word, String.join("", r.lines()));
        for (String line : r.lines()) assertTrue(mono.width(line, r.fontSizePt()) <= 20 + 1e-6);
    }

    @Test
    void minimumReadableSizeIsEnforced() {
        var r = fitter.fit("x".repeat(50), 10, 5);
        assertEquals(6, r.fontSizePt());
        assertTrue(r.overflow());
    }

    @Test
    void degenerateBoxIsAWarningNotAZeroFont() {
        for (double[] box : new double[][]{{0, 10}, {10, 0}, {-5, 10}, {Double.NaN, 10}, {10, Double.POSITIVE_INFINITY}}) {
            var r = fitter.fit("texto", box[0], box[1]);
            assertSane(r, cfg);
            assertTrue(r.overflow());
            assertFalse(r.warnings().isEmpty());
        }
    }

    @Test
    void deterministicForIdenticalInputs() {
        String text = "El contrato entra en vigor en la fecha de la firma de ambas partes.";
        assertEquals(fitter.fit(text, 120, 50), fitter.fit(text, 120, 50));
    }

    @Test
    void configRejectsInvalidLimits() {
        assertThrows(IllegalArgumentException.class, () -> new TextFitter.Config(0, 12, 0.5, 1.2));
        assertThrows(IllegalArgumentException.class, () -> new TextFitter.Config(10, 8, 0.5, 1.2));
        assertThrows(IllegalArgumentException.class, () -> new TextFitter.Config(6, 12, 0, 1.2));
        assertThrows(IllegalArgumentException.class, () -> new TextFitter.Config(6, 12, 0.5, 0.9));
        assertThrows(IllegalArgumentException.class, () -> new TextFitter.Config(6, Double.NaN, 0.5, 1.2));
    }

    @Test
    void awtMeasurerUsesRealMetricsHeadless() {
        AwtTextMeasurer awt = new AwtTextMeasurer(Font.SANS_SERIF, Font.PLAIN);
        double narrow = awt.width("iiiiiiiiii", 12);
        double wide = awt.width("WWWWWWWWWW", 12);
        assertTrue(wide > narrow * 1.5, "proportional font: W is wider than i");
        assertEquals(awt.width("abc", 24), 2 * awt.width("abc", 12), 1e-6, "scales linearly");
        assertNotNull(awt.resolvedFamily());
    }
}
