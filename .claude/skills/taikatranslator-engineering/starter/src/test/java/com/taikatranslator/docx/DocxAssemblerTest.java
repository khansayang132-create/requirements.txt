package com.taikatranslator.docx;

import com.taikatranslator.geometry.NormalizedBox;
import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.layout.FixedAdvanceMeasurer;
import com.taikatranslator.pipeline.CanonicalDocument;
import com.taikatranslator.pipeline.CanonicalDocument.Paragraph;
import com.taikatranslator.pipeline.CanonicalDocument.Role;
import com.taikatranslator.pipeline.CanonicalDocument.Span;
import com.taikatranslator.validation.ArtifactValidator;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.file.Path;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;

/** TSK-5.2.6: merged cells, headers/footers and page numbers survive the round trip. */
class DocxAssemblerTest {

    @TempDir
    Path dir;

    private static final NormalizedBox BOX = new NormalizedBox(0.1, 0.1, 0.8, 0.1);
    private static final List<PageInfo> PAGES = List.of(new PageInfo(1, 210 / 25.4, 297 / 25.4, PageInfo.Unit.INCH, 0)); // A4 exactly: 210 x 297 mm

    private DocxInspector.Snapshot build(List<CanonicalDocument.Block> blocks) throws Exception {
        Path out = dir.resolve("t.docx");
        new DocxAssembler(new FixedAdvanceMeasurer(0.5)).write(new CanonicalDocument(PAGES, blocks), out);
        assertTrue(new ArtifactValidator().validate(out, ArtifactValidator.Type.DOCX).ok());
        return new DocxInspector().inspect(out);
    }

    private static List<List<String>> grid(String[][] g) {
        return java.util.Arrays.stream(g).map(List::of).toList();
    }

    @Test
    void horizontalVerticalAndBlockMergesRoundTrip() throws Exception {
        // 4 x 3 grid:
        //  [ A (1x3)          ]
        //  [ B (2x1) | C | D  ]
        //  [   ...   | E (2x2)]
        //  [ F |    ...       ]
        String[][] cells = {
                {"A", "", ""},
                {"B", "C", "D"},
                {"", "E", ""},
                {"F", "", ""}};
        List<Span> spans = List.of(new Span(0, 0, 1, 3), new Span(1, 0, 2, 1), new Span(2, 1, 2, 2));
        var t = new CanonicalDocument.Table("t1", 4, 3, grid(cells), spans, 1, BOX);
        var snap = build(List.of(t));

        var table = (DocxInspector.Table) snap.body().get(0);
        assertEquals(4, table.rows());
        assertEquals(3, table.columns());
        assertEquals(List.of("0,0 1x3", "1,0 2x1", "2,1 2x2"), table.merges());
        assertEquals(grid(cells), table.cells());
    }

    @Test
    void everyRowHasAMinimumHeightSoMergeOnlyRowsDoNotCollapse() throws Exception {
        // Seen in a LibreOffice render: a row made only of merge continuations collapsed to zero height.
        String[][] cells = {{"B", "C"}, {"", "E"}, {"F", ""}};
        List<Span> spans = List.of(new Span(0, 0, 2, 1), new Span(1, 1, 2, 1));
        Path out = dir.resolve("rows.docx");
        new DocxAssembler(new FixedAdvanceMeasurer(0.5)).write(new CanonicalDocument(PAGES,
                List.of(new CanonicalDocument.Table("t1", 3, 2, grid(cells), spans, 1, BOX))), out);
        try (var in = java.nio.file.Files.newInputStream(out); var doc = new org.apache.poi.xwpf.usermodel.XWPFDocument(in)) {
            for (var row : doc.getTables().get(0).getRows()) {
                assertTrue(row.getHeight() > 0, "row height set");
                assertEquals(org.apache.poi.xwpf.usermodel.TableRowHeightRule.AT_LEAST, row.getHeightRule());
            }
        }
    }

    @Test
    void tableWithoutMergesIsUnchanged() throws Exception {
        String[][] cells = {{"a", "b"}, {"c", "d"}};
        var snap = build(List.of(new CanonicalDocument.Table("t1", 2, 2, grid(cells), List.of(), 1, BOX)));
        var table = (DocxInspector.Table) snap.body().get(0);
        assertEquals(List.of(), table.merges());
        assertEquals(grid(cells), table.cells());
    }

    @Test
    void headersFootersAndPageNumbersLeaveTheBody() throws Exception {
        var snap = build(List.of(
                new Paragraph("h1", Role.HEADER, "CONFIDENCIAL", 1, BOX),
                new Paragraph("p1", Role.BODY, "Cuerpo", 1, BOX),
                new Paragraph("h2", Role.HEADER, "CONFIDENCIAL", 2, BOX), // repeated on page 2: written once
                new Paragraph("f1", Role.FOOTER, "Página de prueba", 1, BOX),
                new Paragraph("n1", Role.PAGE_NUMBER, "1", 1, BOX)));
        assertEquals(1, snap.paragraphCount(), "only the body paragraph is in the body");
        assertEquals(List.of("CONFIDENCIAL"), snap.headers());
        assertEquals(List.of("Página de prueba"), snap.footers());
        assertTrue(snap.pageNumberField(), "page number is a PAGE field, not the literal text \"1\"");
        assertEquals(new DocxInspector.Section(11906, 16838, "portrait"), snap.section(), "A4 in twips");
    }

    @Test
    void noHeaderFooterPartsWhenThereIsNothingToPut() throws Exception {
        var snap = build(List.of(new Paragraph("p1", Role.BODY, "x", 1, BOX)));
        assertEquals(List.of(), snap.headers());
        assertEquals(List.of(), snap.footers());
        assertFalse(snap.pageNumberField());
    }
}
