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

    /**
     * cells[row][column]. A merged cell's text sits at its anchor (top-left);
     * the positions it covers hold "". {@code spans} lists only cells larger than 1x1.
     */
    public record Table(String id, int rows, int columns, List<List<String>> cells, List<Span> spans, int page,
                        NormalizedBox box) implements Block {
        public Table {
            spans = List.copyOf(spans);
        }

        /** True if (row, col) is covered by a span anchored elsewhere. */
        public boolean covered(int row, int col) {
            for (Span s : spans)
                if (row >= s.row() && row < s.row() + s.rowSpan() && col >= s.col() && col < s.col() + s.colSpan()
                        && !(row == s.row() && col == s.col())) return true;
            return false;
        }
    }

    public record Span(int row, int col, int rowSpan, int colSpan) {
        public Span {
            if (row < 0 || col < 0 || rowSpan < 1 || colSpan < 1) throw new IllegalArgumentException("invalid span");
        }
    }
}
