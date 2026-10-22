package com.taikatranslator.core;

import com.taikatranslator.config.AppConfig;
import com.taikatranslator.pipeline.CanonicalDocument;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * TSK-6.7. Checked in two places, both before money is spent:
 * file size before upload to extraction; pages, blocks and characters
 * before anything is sent to translation.
 */
public final class InputLimits {

    public static final class LimitExceeded extends Exception {
        public final String limit;
        public final long actual;
        public final long allowed;

        LimitExceeded(String limit, long actual, long allowed) {
            super(limit + " is " + actual + ", limit is " + allowed);
            this.limit = limit;
            this.actual = actual;
            this.allowed = allowed;
        }
    }

    private final AppConfig.Limits limits;

    public InputLimits(AppConfig.Limits limits) {
        this.limits = limits;
    }

    public void checkFile(Path input) throws IOException, LimitExceeded {
        long size = Files.size(input);
        if (size > limits.maxFileBytes()) throw new LimitExceeded("file size (bytes)", size, limits.maxFileBytes());
    }

    /** @return the number of characters that will be sent for translation */
    public long checkDocument(CanonicalDocument doc) throws LimitExceeded {
        if (doc.pages().size() > limits.maxPages()) throw new LimitExceeded("pages", doc.pages().size(), limits.maxPages());
        long blocks = 0, chars = 0;
        for (CanonicalDocument.Block b : doc.blocks()) {
            if (b instanceof CanonicalDocument.Paragraph p) {
                blocks++;
                chars += p.text().codePointCount(0, p.text().length());
            } else if (b instanceof CanonicalDocument.Table t) {
                for (var row : t.cells())
                    for (String cell : row) {
                        blocks++;
                        chars += cell.codePointCount(0, cell.length());
                    }
            }
        }
        if (blocks > limits.maxBlocks()) throw new LimitExceeded("blocks", blocks, limits.maxBlocks());
        if (chars > limits.maxCharacters()) throw new LimitExceeded("characters to translate", chars, limits.maxCharacters());
        return chars;
    }
}
