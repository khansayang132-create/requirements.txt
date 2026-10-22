package com.taikatranslator.reporting;

import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Last line of defence before anything reaches a log or report. The first line
 * is not putting secrets into messages at all.
 */
public final class Redactor {
    private static final String MASK = "[REDACTED]";

    private static final List<Pattern> PATTERNS = List.of(
            // Authorization: DeepL-Auth-Key xxx / Bearer xxx / Basic xxx
            Pattern.compile("(?i)(authorization\\s*[:=]\\s*)(\"?)(?:deepl-auth-key|bearer|basic)\\s+[^\\s\",]+"),
            Pattern.compile("(?i)(deepl-auth-key\\s+)()[^\\s\",]+"),
            // Azure key header and query-string or JSON style keys
            Pattern.compile("(?i)(ocp-apim-subscription-key\\s*[:=]\\s*)(\"?)[^\\s\",]+"),
            Pattern.compile("(?i)((?:api[_-]?key|auth[_-]?key|subscription[_-]?key|access[_-]?token|secret|password)\"?\\s*[:=]\\s*)(\"?)[^\\s\",&]+"),
            // SAS signatures in blob URLs
            Pattern.compile("(?i)([?&]sig=)()[^&\\s\"]+")
    );

    private Redactor() { }

    public static String redact(String s) {
        if (s == null) return null;
        String out = s;
        for (Pattern p : PATTERNS) {
            Matcher m = p.matcher(out);
            out = m.replaceAll(r -> Matcher.quoteReplacement(r.group(1) + r.group(2) + MASK));
        }
        return out;
    }
}
