package com.taikatranslator.translation;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Shields tokens that must survive translation unchanged (format placeholders,
 * URLs, emails, reference numbers) by wrapping them in {@code <ph>} tags, for
 * DeepL with {@code tag_handling=xml} and {@code ignore_tags=ph}.
 *
 * <p>With tag_handling=xml the rest of the text is XML, so {@code & < >} are
 * escaped on the way out and unescaped on the way back. Forgetting this
 * corrupts every "A & B" in a document.
 */
public final class PlaceholderProtector {

    public record Protected(String xml, List<String> tokens) {
        public Protected {
            tokens = List.copyOf(tokens);
        }
    }

    private static final Pattern TOKEN = Pattern.compile(String.join("|",
            "\\{\\{[^{}]+}}",                          // {{name}}
            "\\{[A-Za-z0-9_]+}",                       // {0} {name}
            "%(?:\\d+\\$)?[-+ 0#]*\\d*(?:\\.\\d+)?[sdfiuxXeEgGc%]", // %s %1$d %.2f
            "https?://[^\\s<>\"]*[^\\s<>\".,;:!?)\\]}'’”]", // URLs, minus trailing sentence punctuation
            "[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}" // emails
    ));
    private static final Pattern PH = Pattern.compile("<ph id=\"(\\d+)\">(.*?)</ph>", Pattern.DOTALL);

    public Protected protect(String text) {
        List<String> tokens = new ArrayList<>();
        StringBuilder out = new StringBuilder();
        Matcher m = TOKEN.matcher(text);
        int last = 0;
        while (m.find()) {
            out.append(escape(text.substring(last, m.start())));
            out.append("<ph id=\"").append(tokens.size()).append("\">").append(escape(m.group())).append("</ph>");
            tokens.add(m.group());
            last = m.end();
        }
        out.append(escape(text.substring(last)));
        return new Protected(out.toString(), tokens);
    }

    /**
     * Restores tokens from the original list (never from the translated XML, in
     * case the engine touched them). Throws if a placeholder was lost or duplicated.
     */
    public String restore(String translatedXml, List<String> tokens) {
        int[] seen = new int[tokens.size()];
        StringBuilder out = new StringBuilder();
        Matcher m = PH.matcher(translatedXml);
        int last = 0;
        while (m.find()) {
            out.append(unescape(translatedXml.substring(last, m.start())));
            int id = Integer.parseInt(m.group(1));
            if (id < 0 || id >= tokens.size()) throw new IllegalStateException("unknown placeholder id " + id);
            seen[id]++;
            out.append(tokens.get(id));
            last = m.end();
        }
        out.append(unescape(translatedXml.substring(last)));
        for (int i = 0; i < seen.length; i++)
            if (seen[i] != 1) throw new IllegalStateException("placeholder " + i + " appears " + seen[i] + " times after translation");
        return out.toString();
    }

    static String escape(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    static String unescape(String s) {
        return s.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", "\"").replace("&apos;", "'").replace("&amp;", "&");
    }

    /** Tokens found in plain text, for validation. */
    public static List<String> tokensIn(String text) {
        List<String> out = new ArrayList<>();
        Matcher m = TOKEN.matcher(text);
        while (m.find()) out.add(m.group());
        return out;
    }
}
