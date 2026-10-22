package com.taikatranslator.layout;

/**
 * Every code point advances {@code emFraction * fontSize}. The character-count
 * fallback, and the deterministic measurer for tests (AWT metrics vary with
 * the fonts installed on a machine).
 */
public record FixedAdvanceMeasurer(double emFraction) implements TextMeasurer {

    public FixedAdvanceMeasurer {
        if (!(emFraction > 0) || !Double.isFinite(emFraction)) throw new IllegalArgumentException("emFraction must be > 0");
    }

    @Override
    public double width(String text, double fontSizePt) {
        return text.codePointCount(0, text.length()) * emFraction * fontSizePt;
    }
}
