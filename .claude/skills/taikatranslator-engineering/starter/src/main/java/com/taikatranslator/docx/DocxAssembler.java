package com.taikatranslator.docx;

import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.layout.TextFitter;
import com.taikatranslator.layout.TextMeasurer;
import com.taikatranslator.pipeline.CanonicalDocument;
import com.taikatranslator.pipeline.CanonicalDocument.Paragraph;
import com.taikatranslator.pipeline.CanonicalDocument.Role;
import com.taikatranslator.pipeline.CanonicalDocument.Table;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFRun;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTPageSz;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSectPr;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.STPageOrientation;

import java.io.IOException;
import java.io.OutputStream;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/**
 * Flow-layout DOCX from a translated {@link CanonicalDocument}: paragraphs and
 * tables in reading order, font size fitted to each block's original box.
 * Text never gets cut; overflow is reported as a layout warning.
 *
 * <p>Header/footer/page-number blocks are skipped here; put them in the DOCX
 * header/footer parts in the real assembler.
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

        try (XWPFDocument d = new XWPFDocument()) {
            for (CanonicalDocument.Block b : doc.blocks()) {
                if (b instanceof Paragraph p) {
                    if (p.role() == Role.HEADER || p.role() == Role.FOOTER || p.role() == Role.PAGE_NUMBER) continue;
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
                    String[] lines = p.text().split("\r\n|\r|\n", -1);
                    for (int i = 0; i < lines.length; i++) {
                        if (i > 0) run.addBreak();
                        run.setText(lines[i], i);
                    }
                } else if (b instanceof Table t) {
                    XWPFTable table = d.createTable(t.rows(), t.columns());
                    double cellWidthPt = t.box().toPoints(pageWpt, pageHpt)[2] / t.columns();
                    TextFitter fitter = new TextFitter(measurer, new TextFitter.Config(6, 10, 0.5, 1.15));
                    for (int r = 0; r < t.rows(); r++) {
                        for (int c = 0; c < t.columns(); c++) {
                            String text = t.cells().get(r).get(c);
                            XWPFParagraph cp = table.getRow(r).getCell(c).getParagraphs().get(0);
                            XWPFRun run = cp.createRun();
                            TextFitter.Result fit = fitter.fit(text, cellWidthPt, Double.MAX_VALUE / 4);
                            run.setFontSize(fit.fontSizePt());
                            run.setText(text);
                        }
                    }
                }
            }
            setPageSize(d, first);
            try (OutputStream os = Files.newOutputStream(out)) {
                d.write(os);
            }
        }
        return warnings;
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
