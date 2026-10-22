package com.taikatranslator.layout;

import java.awt.Font;
import java.awt.font.FontRenderContext;
import java.awt.geom.AffineTransform;

/**
 * Real font metrics through Java2D (works headless). Measures at a 1000 pt
 * reference size and scales, so results are stable across sizes.
 *
 * <p>Use the same font family the DOCX will declare. If that font isn't
 * installed, Java substitutes one and the numbers drift: record the resolved
 * family ({@link #resolvedFamily()}) in the processing report.
 */
public final class AwtTextMeasurer implements TextMeasurer {
    private static final float REFERENCE = 1000f;
    private static final FontRenderContext FRC = new FontRenderContext(new AffineTransform(), true, true);
    private final Font font;

    public AwtTextMeasurer(String family, int style) {
        this.font = new Font(family, style, 1).deriveFont(REFERENCE);
    }

    public String resolvedFamily() {
        return font.getFamily();
    }

    @Override
    public double width(String text, double fontSizePt) {
        if (text.isEmpty()) return 0;
        return font.getStringBounds(text, FRC).getWidth() * fontSizePt / REFERENCE;
    }
}
