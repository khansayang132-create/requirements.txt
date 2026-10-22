package com.taikatranslator.layout;

/** Width of a run of text in points at a font size in points. */
@FunctionalInterface
public interface TextMeasurer {
    double width(String text, double fontSizePt);
}
