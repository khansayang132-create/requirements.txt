package com.taikatranslator.layout;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * Finds the largest font size at which translated text fits its box.
 *
 * <p>Guarantees: the returned size is finite, positive and inside
 * [minSize, maxSize]; every character of the input appears in the returned
 * lines (no truncation); when nothing fits even at minSize the result is
 * marked overflow with a warning; identical inputs give identical outputs.
 */
public final class TextFitter {

    /**
     * @param minSizePt   smallest readable size (e.g. 7 for body text, 6 in table cells)
     * @param maxSizePt   largest allowed size, usually the source size
     * @param stepPt      search granularity; sizes tried are maxSize, maxSize-step, ... minSize
     * @param lineSpacing line height as a multiple of font size (1.15 is Word's default)
     */
    public record Config(double minSizePt, double maxSizePt, double stepPt, double lineSpacing) {
        public Config {
            if (!(minSizePt > 0) || !Double.isFinite(maxSizePt) || maxSizePt < minSizePt)
                throw new IllegalArgumentException("need 0 < minSize <= maxSize, got " + minSizePt + ".." + maxSizePt);
            if (!(stepPt > 0) || !Double.isFinite(stepPt)) throw new IllegalArgumentException("step must be > 0");
            if (!(lineSpacing >= 1.0) || !Double.isFinite(lineSpacing)) throw new IllegalArgumentException("lineSpacing must be >= 1");
        }
    }

    public record Result(double fontSizePt, List<String> lines, boolean overflow, List<String> warnings) {
        public Result {
            lines = List.copyOf(lines);
            warnings = List.copyOf(warnings);
        }
    }

    private final TextMeasurer measurer;
    private final Config config;

    public TextFitter(TextMeasurer measurer, Config config) {
        this.measurer = Objects.requireNonNull(measurer);
        this.config = Objects.requireNonNull(config);
    }

    public Result fit(String text, double boxWidthPt, double boxHeightPt) {
        Objects.requireNonNull(text, "text");
        if (text.isBlank()) return new Result(config.maxSizePt(), List.of(), false, List.of());

        if (!(boxWidthPt > 0) || !(boxHeightPt > 0) || !Double.isFinite(boxWidthPt) || !Double.isFinite(boxHeightPt)) {
            List<String> lines = wrap(text, config.minSizePt(), Double.MAX_VALUE);
            return new Result(config.minSizePt(), lines, true,
                    List.of("box has no usable area (" + boxWidthPt + "x" + boxHeightPt + " pt); text kept at minimum size"));
        }

        int steps = (int) Math.floor((config.maxSizePt() - config.minSizePt()) / config.stepPt() + 1e-9);
        for (int i = 0; i <= steps; i++) {
            double size = config.maxSizePt() - i * config.stepPt();
            List<String> lines = wrap(text, size, boxWidthPt);
            if (fits(lines, size, boxWidthPt, boxHeightPt)) return new Result(size, lines, false, List.of());
        }
        double size = config.minSizePt();
        List<String> lines = wrap(text, size, boxWidthPt);
        if (fits(lines, size, boxWidthPt, boxHeightPt)) return new Result(size, lines, false, List.of());
        double needed = lines.size() * size * config.lineSpacing();
        return new Result(size, lines, true, List.of(String.format(
                "text needs %.1f pt height at minimum size %.1f pt but box is %.1f x %.1f pt",
                needed, size, boxWidthPt, boxHeightPt)));
    }

    private boolean fits(List<String> lines, double size, double boxW, double boxH) {
        if (lines.size() * size * config.lineSpacing() > boxH + 1e-6) return false;
        for (String line : lines) if (measurer.width(line, size) > boxW + 1e-6) return false;
        return true;
    }

    /** Greedy word wrap. Respects explicit line breaks; splits words longer than a line by code point. */
    List<String> wrap(String text, double size, double maxWidth) {
        List<String> out = new ArrayList<>();
        for (String paragraph : text.split("\r\n|\r|\n", -1)) {
            if (paragraph.isEmpty()) { out.add(""); continue; }
            StringBuilder line = new StringBuilder();
            for (String word : paragraph.split(" +")) {
                if (word.isEmpty()) continue;
                String candidate = line.length() == 0 ? word : line + " " + word;
                if (measurer.width(candidate, size) <= maxWidth) {
                    line.setLength(0);
                    line.append(candidate);
                    continue;
                }
                if (line.length() > 0) { out.add(line.toString()); line.setLength(0); }
                if (measurer.width(word, size) <= maxWidth) { line.append(word); continue; }
                // Hard-break an over-long word (URLs, German compounds) without losing characters.
                int[] cps = word.codePoints().toArray();
                StringBuilder chunk = new StringBuilder();
                for (int cp : cps) {
                    String next = chunk.toString() + Character.toString(cp);
                    if (chunk.length() > 0 && measurer.width(next, size) > maxWidth) {
                        out.add(chunk.toString());
                        chunk.setLength(0);
                    }
                    chunk.appendCodePoint(cp);
                }
                line.append(chunk);
            }
            out.add(line.toString());
        }
        return out;
    }
}
