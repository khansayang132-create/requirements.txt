package com.taikatranslator.pipeline;

import com.taikatranslator.geometry.NormalizedBox;
import com.taikatranslator.geometry.PageInfo;

import java.util.List;

/**
 * Provider-neutral document model. Extraction adapters produce it; everything
 * downstream (validation, translation, layout, DOCX) consumes only this.
 * Geometry is always {@link NormalizedBox}.
 */
public record CanonicalDocument(List<PageInfo> pages, List<Block> blocks) {

    public CanonicalDocument {
        pages = List.copyOf(pages);
        blocks = List.copyOf(blocks);
    }

    public enum Role { TITLE, HEADING, BODY, HEADER, FOOTER, FOOTNOTE, PAGE_NUMBER }

    public sealed interface Block permits Paragraph, Table {
        String id();
        int page();
        NormalizedBox box();
    }

    public record Paragraph(String id, Role role, String text, int page, NormalizedBox box) implements Block { }

    /** cells[row][column]; merged cells repeat nothing, the covered positions hold "". */
    public record Table(String id, int rows, int columns, List<List<String>> cells, int page, NormalizedBox box) implements Block { }
}
