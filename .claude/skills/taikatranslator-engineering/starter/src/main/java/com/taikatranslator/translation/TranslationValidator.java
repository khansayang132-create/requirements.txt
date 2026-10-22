package com.taikatranslator.translation;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * Block-level checks after translation: nothing missing, nothing empty,
 * placeholders intact, nothing suspiciously untranslated.
 *
 * <p>Errors fail the translation gate. Warnings go in the report; a block that
 * is legitimately identical (a name, a number, a code) is a warning, not an error.
 */
public final class TranslationValidator {

    public record Block(String id, String source, String translated) { }

    public record Finding(String blockId, boolean error, String message) { }

    public record Result(List<Finding> findings, int checked) {
        public Result {
            findings = List.copyOf(findings);
        }

        public boolean passed() {
            return findings.stream().noneMatch(Finding::error);
        }

        public long errorCount() {
            return findings.stream().filter(Finding::error).count();
        }
    }

    private final double maxLengthRatio;

    /** @param maxLengthRatio warn when translated/source length is outside [1/r, r]; 3.0 is a sane start */
    public TranslationValidator(double maxLengthRatio) {
        if (!(maxLengthRatio > 1)) throw new IllegalArgumentException("ratio must be > 1");
        this.maxLengthRatio = maxLengthRatio;
    }

    public Result validate(List<String> expectedIds, List<Block> blocks) {
        List<Finding> f = new ArrayList<>();
        Map<String, Block> byId = new LinkedHashMap<>();
        for (Block b : blocks) {
            if (byId.put(b.id(), b) != null) f.add(new Finding(b.id(), true, "duplicate block id"));
        }
        for (String id : expectedIds) if (!byId.containsKey(id)) f.add(new Finding(id, true, "block missing from translation"));
        for (String id : byId.keySet()) if (!expectedIds.contains(id)) f.add(new Finding(id, true, "unexpected block not in source"));

        for (Block b : byId.values()) {
            String src = Objects.requireNonNullElse(b.source(), "");
            String dst = b.translated();
            if (dst == null || (dst.isBlank() && !src.isBlank())) {
                f.add(new Finding(b.id(), true, "empty translation for non-empty source"));
                continue;
            }
            if (!counts(PlaceholderProtector.tokensIn(src)).equals(counts(PlaceholderProtector.tokensIn(dst))))
                f.add(new Finding(b.id(), true, "placeholders, URLs or emails changed"));
            if (letters(src) >= 12 && src.strip().equals(dst.strip()))
                f.add(new Finding(b.id(), false, "translation identical to source; possibly untranslated"));
            int ls = src.strip().length(), ld = dst.strip().length();
            if (ls >= 20 && ld > 0) {
                double r = (double) ld / ls;
                if (r > maxLengthRatio || r < 1 / maxLengthRatio)
                    f.add(new Finding(b.id(), false, String.format("length ratio %.2f outside expected range", r)));
            }
        }
        return new Result(f, byId.size());
    }

    private static Map<String, Integer> counts(List<String> tokens) {
        Map<String, Integer> m = new HashMap<>();
        for (String t : tokens) m.merge(t, 1, Integer::sum);
        return m;
    }

    private static int letters(String s) {
        return (int) s.codePoints().filter(Character::isLetter).count();
    }
}
