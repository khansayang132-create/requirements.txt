package com.taikatranslator.core;

import com.taikatranslator.config.AppConfig;
import com.taikatranslator.geometry.NormalizedBox;
import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.pipeline.CanonicalDocument;
import com.taikatranslator.provider.Translator;
import com.taikatranslator.retry.ProviderException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.FileSystems;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-6.6 (workspace), TSK-6.7 (limits), TSK-6.8 (checkpoints and translation cache). */
class CoreTest {

    @TempDir
    Path tmp;

    // ---- RunWorkspace

    @Test
    void workspaceIsPrivateAndDeletedAfterSuccess() throws Exception {
        RunWorkspace ws = RunWorkspace.create(tmp, "run-1");
        assertTrue(ws.dir().getFileName().toString().startsWith("taika-run-1-"));
        if (FileSystems.getDefault().supportedFileAttributeViews().contains("posix"))
            assertEquals("rwx------", PosixFilePermissions.toString(Files.getPosixFilePermissions(ws.dir())));
        Files.createDirectories(ws.resolve("pages"));
        Files.writeString(ws.resolve("pages/p1.png"), "x");
        assertEquals(RunWorkspace.Disposition.DELETED, ws.finish(true, false));
        assertFalse(Files.exists(ws.dir()));
    }

    @Test
    void workspaceKeptOnFailureOrRequest() throws Exception {
        RunWorkspace a = RunWorkspace.create(tmp, "a");
        assertEquals(RunWorkspace.Disposition.KEPT_FOR_DIAGNOSTICS, a.finish(false, false));
        assertTrue(Files.exists(a.dir()));
        RunWorkspace b = RunWorkspace.create(tmp, "b");
        assertEquals(RunWorkspace.Disposition.KEPT_ON_REQUEST, b.finish(true, true));
        assertTrue(Files.exists(b.dir()));
    }

    @Test
    void workspaceRejectsEscapesAndBadRunIds() throws Exception {
        RunWorkspace ws = RunWorkspace.create(tmp, "r");
        assertThrows(IllegalArgumentException.class, () -> ws.resolve("../../etc/passwd"));
        assertThrows(IllegalArgumentException.class, () -> RunWorkspace.create(tmp, "../x"));
    }

    @Test
    void deletionDoesNotFollowSymlinksOutOfTheWorkspace() throws Exception {
        Path outside = Files.writeString(tmp.resolve("precious.txt"), "keep me");
        RunWorkspace ws = RunWorkspace.create(tmp, "s");
        try {
            Files.createSymbolicLink(ws.resolve("link"), outside);
        } catch (UnsupportedOperationException | java.io.IOException e) {
            return; // filesystem without symlinks: nothing to prove
        }
        ws.finish(true, false);
        assertEquals("keep me", Files.readString(outside));
    }

    // ---- InputLimits

    private static CanonicalDocument doc(int pages, String... texts) {
        List<PageInfo> ps = new ArrayList<>();
        for (int i = 1; i <= pages; i++) ps.add(new PageInfo(i, 8.5, 11, PageInfo.Unit.INCH, 0));
        List<CanonicalDocument.Block> bs = new ArrayList<>();
        int n = 0;
        for (String t : texts)
            bs.add(new CanonicalDocument.Paragraph("p" + (++n), CanonicalDocument.Role.BODY, t, 1, new NormalizedBox(0.1, 0.1, 0.5, 0.1)));
        return new CanonicalDocument(ps, bs);
    }

    @Test
    void limitsStopOversizedInputsWithTheLimitNamed() throws Exception {
        InputLimits l = new InputLimits(new AppConfig.Limits(10, 2, 12, 3));
        Path big = Files.writeString(tmp.resolve("big.pdf"), "%PDF-1.7 and more");
        var e = assertThrows(InputLimits.LimitExceeded.class, () -> l.checkFile(big));
        assertEquals("file size (bytes)", e.limit);
        assertEquals("pages", assertThrows(InputLimits.LimitExceeded.class, () -> l.checkDocument(doc(3, "a"))).limit);
        assertEquals("blocks", assertThrows(InputLimits.LimitExceeded.class, () -> l.checkDocument(doc(1, "a", "b", "c", "d"))).limit);
        assertEquals("characters to translate",
                assertThrows(InputLimits.LimitExceeded.class, () -> l.checkDocument(doc(1, "0123456789", "abc"))).limit);
        assertEquals(12, l.checkDocument(doc(1, "😀😀", "0123456789")), "code points, not UTF-16 units");
    }

    // ---- CheckpointStore

    @Test
    void checkpointHitOnlyWhenInputConfigAndOutputAllMatch() throws Exception {
        CheckpointStore cs = new CheckpointStore(tmp.resolve("cp"));
        Path out = Files.writeString(tmp.resolve("extraction.json"), "{\"pages\":[]}");
        cs.record("extraction", "in1", "cfg1", out);

        assertTrue(cs.find("extraction", "in1", "cfg1").hit());
        assertEquals(CheckpointStore.Miss.ABSENT, cs.find("translation", "in1", "cfg1").miss());
        assertEquals(CheckpointStore.Miss.INPUT_CHANGED, cs.find("extraction", "in2", "cfg1").miss());
        assertEquals(CheckpointStore.Miss.CONFIG_CHANGED, cs.find("extraction", "in1", "cfg2").miss());
        Files.writeString(out, "{\"pages\":[1]}");
        assertEquals(CheckpointStore.Miss.OUTPUT_CHANGED, cs.find("extraction", "in1", "cfg1").miss());
        Files.delete(out);
        assertEquals(CheckpointStore.Miss.OUTPUT_MISSING, cs.find("extraction", "in1", "cfg1").miss());
    }

    @Test
    void corruptCheckpointIsAMissNotACrash() throws Exception {
        CheckpointStore cs = new CheckpointStore(tmp.resolve("cp"));
        Files.writeString(tmp.resolve("cp/extraction.checkpoint.json"), "{\"inputSha256\":");
        assertEquals(CheckpointStore.Miss.CORRUPT, cs.find("extraction", "a", "b").miss());
        assertThrows(IllegalArgumentException.class, () -> cs.find("../evil", "a", "b"));
    }

    // ---- TranslationCache

    /** Counts what reaches the "provider". */
    private static final class CountingTranslator implements Translator {
        final List<List<String>> calls = new ArrayList<>();

        @Override
        public Response translate(Request r) {
            calls.add(r.texts());
            List<String> out = new ArrayList<>();
            for (String t : r.texts()) out.add("ES:" + t);
            return new Response(out, Optional.of("EN"), 0);
        }
    }

    @Test
    void resumedRunPaysOnlyForNewBlocks() throws Exception {
        Path file = tmp.resolve("translations.jsonl");
        CountingTranslator provider = new CountingTranslator();
        TranslationCache first = new TranslationCache(provider, file, "fp");
        first.translate(new Translator.Request(List.of("a", "b"), Optional.empty(), "ES", true));

        TranslationCache resumed = new TranslationCache(provider, file, "fp");
        var r = resumed.translate(new Translator.Request(List.of("a", "b", "c", "a"), Optional.empty(), "ES", true));
        assertEquals(List.of("ES:a", "ES:b", "ES:c", "ES:a"), r.texts(), "order preserved, duplicates served");
        assertEquals(List.of(List.of("a", "b"), List.of("c")), provider.calls);
        assertEquals(3, resumed.hits());
        assertFalse(Files.readString(file).contains("\"a\""), "source text is not stored, only hashes");
    }

    @Test
    void differentTargetOrConfigNeverReusesTranslations() throws Exception {
        Path file = tmp.resolve("t.jsonl");
        CountingTranslator provider = new CountingTranslator();
        new TranslationCache(provider, file, "fp").translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", true));
        new TranslationCache(provider, file, "fp").translate(new Translator.Request(List.of("a"), Optional.empty(), "DE", true));
        new TranslationCache(provider, file, "other").translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", true));
        assertEquals(3, provider.calls.size());
    }

    @Test
    void tornLastLineIsSkippedOnLoad() throws Exception {
        Path file = tmp.resolve("t.jsonl");
        CountingTranslator provider = new CountingTranslator();
        new TranslationCache(provider, file, "fp").translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", true));
        Files.writeString(file, "{\"k\":\"abc", java.nio.file.StandardOpenOption.APPEND);
        TranslationCache reloaded = new TranslationCache(provider, file, "fp");
        assertEquals(1, reloaded.skippedLines());
        reloaded.translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", true));
        assertEquals(1, provider.calls.size(), "the intact entry is still used");
    }

    @Test
    void wrongCountFromProviderIsRejected() throws Exception {
        Translator broken = r -> new Translator.Response(Collections.emptyList(), Optional.empty(), 0);
        TranslationCache c = new TranslationCache(broken, tmp.resolve("x.jsonl"), "fp");
        assertThrows(ProviderException.class, () -> c.translate(new Translator.Request(List.of("a"), Optional.empty(), "ES", true)));
    }
}
