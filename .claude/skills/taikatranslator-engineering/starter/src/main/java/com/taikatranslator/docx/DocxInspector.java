package com.taikatranslator.docx;

import org.apache.poi.xwpf.usermodel.IBodyElement;
import org.apache.poi.xwpf.usermodel.ParagraphAlignment;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFFooter;
import org.apache.poi.xwpf.usermodel.XWPFHeader;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFPicture;
import org.apache.poi.xwpf.usermodel.XWPFRun;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTPageSz;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSectPr;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSimpleField;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTTcPr;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.STMerge;

import java.io.IOException;
import java.io.InputStream;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.TreeSet;

/**
 * Reads a DOCX back into a structural snapshot that tests compare against an
 * expected snapshot. ZIP timestamps and XML attribute order vary between runs,
 * so byte comparison is meaningless; this is what "same document" means.
 *
 * <p>Units: font sizes in points, image extents in EMU (914,400 per inch),
 * page size and margins in twips (1,440 per inch).
 */
public final class DocxInspector {

    public sealed interface Element permits Para, Table { }

    public record Image(String relationId, String contentType, long widthEmu, long heightEmu) { }

    public record Para(String style, String text, String alignment, List<Double> fontSizes, List<Image> images) implements Element { }

    /** cells is the grid: merged-away positions hold "". merges lists "row,col rowSpanxcolSpan" for spans > 1x1. */
    public record Table(int rows, int columns, List<List<String>> cells, List<String> merges) implements Element { }

    public record Section(long pageWidthTwips, long pageHeightTwips, String orientation) { }

    public record Snapshot(List<Element> body, Section section, List<String> headers, List<String> footers,
                           boolean pageNumberField) {
        public long paragraphCount() { return body.stream().filter(e -> e instanceof Para).count(); }
        public long tableCount() { return body.stream().filter(e -> e instanceof Table).count(); }
        public long imageCount() {
            return body.stream().filter(e -> e instanceof Para).mapToLong(e -> ((Para) e).images().size()).sum();
        }
        public String allText() {
            StringBuilder sb = new StringBuilder();
            for (Element e : body) {
                if (e instanceof Para p) sb.append(p.text()).append('\n');
                else if (e instanceof Table t) t.cells().forEach(r -> sb.append(String.join("\t", r)).append('\n'));
            }
            return sb.toString();
        }
    }

    public Snapshot inspect(Path docx) throws IOException {
        try (InputStream in = Files.newInputStream(docx); XWPFDocument doc = new XWPFDocument(in)) {
            List<Element> body = new ArrayList<>();
            for (IBodyElement el : doc.getBodyElements()) {
                if (el instanceof XWPFParagraph p) body.add(para(p));
                else if (el instanceof XWPFTable t) body.add(table(t));
            }
            List<String> headers = new ArrayList<>(), footers = new ArrayList<>();
            boolean pageField = false;
            for (XWPFHeader h : doc.getHeaderList())
                for (XWPFParagraph p : h.getParagraphs()) if (!p.getText().isBlank()) headers.add(p.getText().strip());
            for (XWPFFooter f : doc.getFooterList())
                for (XWPFParagraph p : f.getParagraphs()) {
                    if (hasPageField(p)) pageField = true;
                    else if (!p.getText().isBlank()) footers.add(p.getText().strip());
                }
            return new Snapshot(body, section(doc), headers, footers, pageField);
        }
    }

    private static Para para(XWPFParagraph p) {
        TreeSet<Double> sizes = new TreeSet<>();
        List<Image> images = new ArrayList<>();
        for (XWPFRun r : p.getRuns()) {
            Double size = r.getFontSizeAsDouble();
            if (size != null) sizes.add(size);
            for (XWPFPicture pic : r.getEmbeddedPictures()) {
                var ext = pic.getCTPicture().getSpPr().getXfrm().getExt();
                String rel = pic.getCTPicture().getBlipFill().getBlip().getEmbed();
                String type = pic.getPictureData() == null ? null : pic.getPictureData().getPackagePart().getContentType();
                images.add(new Image(rel, type, ext.getCx(), ext.getCy()));
            }
        }
        ParagraphAlignment a = p.getAlignment();
        return new Para(p.getStyle(), p.getText(), a == null ? "LEFT" : a.name(), List.copyOf(sizes), images);
    }

    /** Rebuilds the logical grid from gridSpan (horizontal) and vMerge (vertical). */
    private static Table table(XWPFTable t) {
        int rows = t.getRows().size();
        List<List<String>> grid = new ArrayList<>();
        List<int[]> anchors = new ArrayList<>(); // {row, col, colSpan}
        List<List<Boolean>> continues = new ArrayList<>();
        int cols = 0;
        for (int r = 0; r < rows; r++) {
            List<String> line = new ArrayList<>();
            List<Boolean> cont = new ArrayList<>();
            for (XWPFTableCell c : t.getRow(r).getTableCells()) {
                CTTcPr pr = c.getCTTc().getTcPr();
                int span = pr != null && pr.isSetGridSpan() ? pr.getGridSpan().getVal().intValue() : 1;
                boolean vCont = pr != null && pr.isSetVMerge()
                        && (pr.getVMerge().getVal() == null || pr.getVMerge().getVal() == STMerge.CONTINUE);
                if (!vCont && (span > 1 || (pr != null && pr.isSetVMerge()))) anchors.add(new int[]{r, line.size(), span});
                line.add(vCont ? "" : c.getText());
                cont.add(vCont);
                for (int k = 1; k < span; k++) { line.add(""); cont.add(vCont); }
            }
            cols = Math.max(cols, line.size());
            grid.add(line);
            continues.add(cont);
        }
        List<String> merges = new ArrayList<>();
        for (int[] a : anchors) {
            int rowSpan = 1;
            while (a[0] + rowSpan < rows && a[1] < continues.get(a[0] + rowSpan).size() && continues.get(a[0] + rowSpan).get(a[1])) rowSpan++;
            if (rowSpan > 1 || a[2] > 1) merges.add(a[0] + "," + a[1] + " " + rowSpan + "x" + a[2]);
        }
        return new Table(rows, cols, grid, merges);
    }

    private static boolean hasPageField(XWPFParagraph p) {
        for (CTSimpleField f : p.getCTP().getFldSimpleList())
            if (f.getInstr() != null && f.getInstr().trim().toUpperCase().startsWith("PAGE")) return true;
        return p.getCTP().xmlText().contains("instrText") && p.getCTP().xmlText().matches("(?s).*instrText[^>]*>\\s*PAGE\\b.*");
    }

    private static Section section(XWPFDocument doc) {
        CTSectPr s = doc.getDocument().getBody().getSectPr();
        if (s == null || !s.isSetPgSz()) return null;
        CTPageSz sz = s.getPgSz();
        long w = toLong(sz.getW()), h = toLong(sz.getH());
        String orient = sz.isSetOrient() ? sz.getOrient().toString() : (w > h ? "landscape" : "portrait");
        return new Section(w, h, orient);
    }

    private static long toLong(Object v) {
        if (v instanceof BigInteger b) return b.longValue();
        return Long.parseLong(Objects.toString(v));
    }
}
