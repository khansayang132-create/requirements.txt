package com.taikatranslator.docx;

import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.layout.TextFitter;
import com.taikatranslator.layout.TextMeasurer;
import com.taikatranslator.pipeline.CanonicalDocument;
import com.taikatranslator.pipeline.CanonicalDocument.Paragraph;
import com.taikatranslator.pipeline.CanonicalDocument.Role;
import com.taikatranslator.pipeline.CanonicalDocument.Span;
import com.taikatranslator.pipeline.CanonicalDocument.Table;
import org.apache.poi.wp.usermodel.HeaderFooterType;
import org.apache.poi.xwpf.usermodel.ParagraphAlignment;
import org.apache.poi.xwpf.usermodel.TableRowHeightRule;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFFooter;
import org.apache.poi.xwpf.usermodel.XWPFHeader;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFRun;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTPageSz;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSectPr;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSimpleField;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTTcPr;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.STMerge;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.STPageOrientation;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Flow-layout DOCX from a translated {@link CanonicalDocument}: paragraphs and
 * tables in reading order, font size fitted to each block's original box.
 * Text never gets cut; overflow is reported as a layout warning.
 *
 * <ul>
 *   <li>Merged cells: horizontal spans become {@code w:gridSpan} (covered cells removed),
 *       vertical spans become {@code w:vMerge restart/continue}.</li>
 *   <li>Page headers/footers go into the DOCX header/footer parts once (deduplicated
 *       across pages), not into the body.</li>
 *   <li>A page-number block becomes a PAGE field so every page shows its own number;
 *       copying page 1's literal "1" would print "1" on every page.</li>
 * </ul>
 */
public final class DocxAssembler {

    private static final double POINTS_PER_INCH = 72.0;
    private static final int TWIPS_PER_INCH = 1440;

    private final TextMeasurer measurer;

    public DocxAssembler(TextMeasurer measurer) {
        this.measurer = measurer;
    }

    public List<String> write(CanonicalDocument doc, Path out) throws IOException {
        List<String> warnings = new ArrayList<>();
        PageInfo first = doc.pages().get(0);
        double pageWpt = toPoints(first.width(), first.unit());
        double pageHpt = toPoints(first.height(), first.unit());

        Set<String> headers = new LinkedHashSet<>();
        Set<String> footers = new LinkedHashSet<>();
        boolean pageNumber = false;

        try (XWPFDocument d = new XWPFDocument()) {
            for (CanonicalDocument.Block b : doc.blocks()) {
                if (b instanceof Paragraph p) {
                    switch (p.role()) {
                        case HEADER -> { headers.add(p.text().strip()); continue; }
                        case FOOTER -> { footers.add(p.text().strip()); continue; }
                        case PAGE_NUMBER -> { pageNumber = true; continue; }
                        default -> { }
                    }
                    writeParagraph(d, p, pageWpt, pageHpt, warnings);
                } else if (b instanceof Table t) {
                    writeTable(d, t, pageWpt, pageHpt);
                }
            }
            writeHeaderFooter(d, headers, footers, pageNumber);
            setPageSize(d, first);
            try (OutputStream os = Files.newOutputStream(out)) {
                d.write(os);
            }
        }
        return warnings;
    }

    private void writeParagraph(XWPFDocument d, Paragraph p, double pageWpt, double pageHpt, List<String> warnings) {
        double max = switch (p.role()) {
            case TITLE -> 20;
            case HEADING -> 14;
            default -> 11;
        };
        TextFitter fitter = new TextFitter(measurer, new TextFitter.Config(7, max, 0.5, 1.15));
        double[] box = p.box().toPoints(pageWpt, pageHpt);
        TextFitter.Result fit = fitter.fit(p.text(), box[2], box[3]);
        fit.warnings().forEach(w -> warnings.add(p.id() + ": " + w));

        XWPFParagraph para = d.createParagraph();
        if (p.role() == Role.TITLE) para.setStyle("Title");
        else if (p.role() == Role.HEADING) para.setStyle("Heading1");
        XWPFRun run = para.createRun();
        run.setFontSize(fit.fontSizePt());
        if (p.role() == Role.TITLE || p.role() == Role.HEADING) run.setBold(true);
        setTextWithBreaks(run, p.text());
    }

    private void writeTable(XWPFDocument d, Table t, double pageWpt, double pageHpt) {
        XWPFTable table = d.createTable(t.rows(), t.columns());
        double[] boxPt = t.box().toPoints(pageWpt, pageHpt);
        double cellWidthPt = boxPt[2] / t.columns();
        // Minimum row height from the source geometry. Without it, a row made only of merged-cell
        // continuations has no content of its own and renderers collapse it to zero height.
        int rowTwips = (int) Math.round(boxPt[3] / t.rows() * 20);
        for (int r = 0; r < t.rows(); r++) {
            table.getRow(r).setHeight(rowTwips);
            table.getRow(r).setHeightRule(TableRowHeightRule.AT_LEAST);
        }
        TextFitter fitter = new TextFitter(measurer, new TextFitter.Config(6, 10, 0.5, 1.15));
        for (int r = 0; r < t.rows(); r++) {
            for (int c = 0; c < t.columns(); c++) {
                if (t.covered(r, c)) continue;
                String text = t.cells().get(r).get(c);
                XWPFRun run = table.getRow(r).getCell(c).getParagraphs().get(0).createRun();
                run.setFontSize(fitter.fit(text, cellWidthPt * spanAt(t, r, c).colSpan(), Double.MAX_VALUE / 4).fontSizePt());
                setTextWithBreaks(run, text);
            }
        }
        // Vertical first (cell indexes are still the grid), then remove horizontally covered cells right to left.
        for (Span s : t.spans()) {
            if (s.rowSpan() < 2) continue;
            for (int r = s.row(); r < s.row() + s.rowSpan(); r++)
                tcPr(table.getRow(r).getCell(s.col())).addNewVMerge().setVal(r == s.row() ? STMerge.RESTART : STMerge.CONTINUE);
        }
        for (int r = 0; r < t.rows(); r++) {
            XWPFTableRow row = table.getRow(r);
            for (int c = t.columns() - 1; c >= 0; c--) {
                Span s = horizontalSpanCovering(t, r, c);
                if (s == null) continue;
                if (c == s.col()) tcPr(row.getCell(c)).addNewGridSpan().setVal(BigInteger.valueOf(s.colSpan()));
                else row.removeCell(c);
            }
        }
    }

    private static Span spanAt(Table t, int r, int c) {
        for (Span s : t.spans()) if (s.row() == r && s.col() == c) return s;
        return new Span(r, c, 1, 1);
    }

    /** The span with colSpan > 1 whose rows include r and columns include c, if any. */
    private static Span horizontalSpanCovering(Table t, int r, int c) {
        for (Span s : t.spans())
            if (s.colSpan() > 1 && r >= s.row() && r < s.row() + s.rowSpan() && c >= s.col() && c < s.col() + s.colSpan())
                return s;
        return null;
    }

    private static CTTcPr tcPr(XWPFTableCell cell) {
        return cell.getCTTc().isSetTcPr() ? cell.getCTTc().getTcPr() : cell.getCTTc().addNewTcPr();
    }

    private void writeHeaderFooter(XWPFDocument d, Set<String> headers, Set<String> footers, boolean pageNumber) {
        if (!headers.isEmpty()) {
            XWPFHeader h = d.createHeader(HeaderFooterType.DEFAULT);
            for (String text : headers) {
                XWPFParagraph p = h.createParagraph();
                p.setAlignment(ParagraphAlignment.CENTER);
                p.createRun().setText(text);
            }
        }
        if (!footers.isEmpty() || pageNumber) {
            XWPFFooter f = d.createFooter(HeaderFooterType.DEFAULT);
            for (String text : footers) {
                XWPFParagraph p = f.createParagraph();
                p.setAlignment(ParagraphAlignment.CENTER);
                p.createRun().setText(text);
            }
            if (pageNumber) {
                XWPFParagraph p = f.createParagraph();
                p.setAlignment(ParagraphAlignment.CENTER);
                CTSimpleField field = p.getCTP().addNewFldSimple();
                field.setInstr("PAGE");
                field.addNewR().addNewT().setStringValue("1"); // cached result; Word/LibreOffice recompute it per page
            }
        }
    }

    private static void setTextWithBreaks(XWPFRun run, String text) {
        String[] lines = text.split("\r\n|\r|\n", -1);
        for (int i = 0; i < lines.length; i++) {
            if (i > 0) run.addBreak();
            run.setText(lines[i], i);
        }
    }

    private static void setPageSize(XWPFDocument d, PageInfo page) {
        if (page.unit() != PageInfo.Unit.INCH && page.unit() != PageInfo.Unit.POINT) return; // pixels have no physical size
        double wIn = page.unit() == PageInfo.Unit.INCH ? page.width() : page.width() / POINTS_PER_INCH;
        double hIn = page.unit() == PageInfo.Unit.INCH ? page.height() : page.height() / POINTS_PER_INCH;
        CTSectPr sect = d.getDocument().getBody().isSetSectPr() ? d.getDocument().getBody().getSectPr() : d.getDocument().getBody().addNewSectPr();
        CTPageSz sz = sect.isSetPgSz() ? sect.getPgSz() : sect.addNewPgSz();
        sz.setW(BigInteger.valueOf(Math.round(wIn * TWIPS_PER_INCH)));
        sz.setH(BigInteger.valueOf(Math.round(hIn * TWIPS_PER_INCH)));
        sz.setOrient(wIn > hIn ? STPageOrientation.LANDSCAPE : STPageOrientation.PORTRAIT);
    }

    private static double toPoints(double v, PageInfo.Unit unit) {
        return switch (unit) {
            case INCH -> v * POINTS_PER_INCH;
            case POINT -> v;
            case PIXEL -> v * POINTS_PER_INCH / 96.0; // assumption: 96 dpi when the image carries no DPI
            case NORMALIZED -> v * 612; // Letter width; only used when no physical size exists
        };
    }
}
