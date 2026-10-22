package com.taikatranslator.docx;

import org.apache.poi.xwpf.usermodel.IBodyElement;
import org.apache.poi.xwpf.usermodel.ParagraphAlignment;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.usermodel.XWPFParagraph;
import org.apache.poi.xwpf.usermodel.XWPFPicture;
import org.apache.poi.xwpf.usermodel.XWPFRun;
import org.apache.poi.xwpf.usermodel.XWPFTable;
import org.apache.poi.xwpf.usermodel.XWPFTableCell;
import org.apache.poi.xwpf.usermodel.XWPFTableRow;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTPageSz;
import org.openxmlformats.schemas.wordprocessingml.x2006.main.CTSectPr;

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

    public record Table(int rows, int columns, List<List<String>> cells) implements Element { }

    public record Section(long pageWidthTwips, long pageHeightTwips, String orientation) { }

    public record Snapshot(List<Element> body, Section section) {
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
            return new Snapshot(body, section(doc));
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

    private static Table table(XWPFTable t) {
        List<List<String>> cells = new ArrayList<>();
        int cols = 0;
        for (XWPFTableRow row : t.getRows()) {
            List<String> r = new ArrayList<>();
            for (XWPFTableCell c : row.getTableCells()) r.add(c.getText());
            cols = Math.max(cols, r.size());
            cells.add(r);
        }
        return new Table(t.getRows().size(), cols, cells);
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
