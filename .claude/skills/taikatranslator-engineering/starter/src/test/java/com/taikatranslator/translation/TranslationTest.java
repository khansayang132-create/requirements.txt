package com.taikatranslator.translation;

import com.taikatranslator.translation.TranslationValidator.Block;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

class TranslationTest {

    private final PlaceholderProtector p = new PlaceholderProtector();
    private final TranslationValidator v = new TranslationValidator(3.0);

    @Test
    void protectEscapesXmlAndWrapsTokens() {
        var prot = p.protect("Pay {amount} to A & B <now> via https://pay.example.com/x?a=1&b=2");
        assertEquals(List.of("{amount}", "https://pay.example.com/x?a=1&b=2"), prot.tokens());
        assertTrue(prot.xml().contains("A &amp; B &lt;now&gt;"));
        assertTrue(prot.xml().contains("<ph id=\"0\">{amount}</ph>"));
    }

    @Test
    void urlDoesNotSwallowSentencePunctuation() {
        assertEquals(List.of("https://example.com/help"), PlaceholderProtector.tokensIn("See https://example.com/help."));
        assertEquals(List.of("https://example.com/a?b=1"), PlaceholderProtector.tokensIn("(https://example.com/a?b=1), then"));
    }

    @Test
    void roundTripAfterSimulatedTranslation() {
        var prot = p.protect("Hello {name}, total %1$.2f EUR. Ask a@b.com & co.");
        // An engine that moved the placeholders and translated the text around them.
        String translated = prot.xml()
                .replace("Hello ", "Hola ")
                .replace(", total ", ", total ")
                .replace("Ask ", "Pregunta a ")
                .replace(" &amp; co.", " y cía.");
        String restored = p.restore(translated, prot.tokens());
        assertEquals("Hola {name}, total %1$.2f EUR. Pregunta a a@b.com y cía.", restored);
    }

    @Test
    void restoreUsesOriginalTokensEvenIfEngineAlteredThem() {
        var prot = p.protect("Ref {0}");
        String altered = prot.xml().replace("{0}", "{O}");
        assertEquals("Ref {0}", p.restore(altered, prot.tokens()));
    }

    @Test
    void lostOrDuplicatedPlaceholderIsAnError() {
        var prot = p.protect("A {x} B {y}");
        String lost = prot.xml().replaceAll("<ph id=\"1\">.*?</ph>", "");
        assertThrows(IllegalStateException.class, () -> p.restore(lost, prot.tokens()));
        String dup = prot.xml() + "<ph id=\"0\">{x}</ph>";
        assertThrows(IllegalStateException.class, () -> p.restore(dup, prot.tokens()));
    }

    @Test
    void validatorFindsMissingEmptyAndExtraBlocks() {
        var r = v.validate(List.of("p1", "p2", "p3"), List.of(
                new Block("p1", "Hello world", "Hola mundo"),
                new Block("p2", "Second paragraph", " "),
                new Block("p9", "Ghost", "Fantasma")));
        assertFalse(r.passed());
        List<String> msgs = r.findings().stream().map(f -> f.blockId() + ":" + f.message()).toList();
        assertTrue(msgs.contains("p3:block missing from translation"), msgs.toString());
        assertTrue(msgs.contains("p9:unexpected block not in source"), msgs.toString());
        assertTrue(msgs.contains("p2:empty translation for non-empty source"), msgs.toString());
    }

    @Test
    void validatorCatchesPlaceholderCorruption() {
        var r = v.validate(List.of("a"), List.of(new Block("a", "Total: {amount} EUR", "Total: {importe} EUR")));
        assertFalse(r.passed());
    }

    @Test
    void untranslatedAndOddLengthAreWarningsNotErrors() {
        var r = v.validate(List.of("a", "b", "c"), List.of(
                new Block("a", "This clause remains in force", "This clause remains in force"),
                new Block("b", "The parties agree to the terms below", "Las partes " + "x".repeat(200)),
                new Block("c", "ACME GmbH", "ACME GmbH")));
        assertTrue(r.passed());
        assertEquals(2, r.findings().size(), r.findings().toString());
        assertTrue(r.findings().stream().noneMatch(TranslationValidator.Finding::error));
    }

    @Test
    void duplicateIdsAreErrors() {
        var r = v.validate(List.of("a"), List.of(new Block("a", "x", "y"), new Block("a", "x", "y")));
        assertFalse(r.passed());
    }
}
