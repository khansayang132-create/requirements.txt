package com.taikatranslator.docx;

import com.taikatranslator.docx.DocxInspector.Element;
import com.taikatranslator.docx.DocxInspector.Para;
import com.taikatranslator.docx.DocxInspector.Snapshot;
import com.taikatranslator.docx.DocxInspector.Table;

import java.util.ArrayList;
import java.util.List;

/**
 * Compares an actual snapshot to an expected one and explains every difference
 * in a sentence an engineer can act on. An empty list means equal.
 */
public final class StructureDiff {
    private StructureDiff() { }

    public static List<String> compare(Snapshot expected, Snapshot actual) {
        List<String> d = new ArrayList<>();
        if (expected.body().size() != actual.body().size())
            d.add("body has " + actual.body().size() + " elements, expected " + expected.body().size());
        int n = Math.min(expected.body().size(), actual.body().size());
        for (int i = 0; i < n; i++) {
            Element e = expected.body().get(i), a = actual.body().get(i);
            String at = "element " + i + ": ";
            if (e.getClass() != a.getClass()) {
                d.add(at + "is a " + a.getClass().getSimpleName() + ", expected " + e.getClass().getSimpleName());
                continue;
            }
            if (e instanceof Para ep && a instanceof Para ap) {
                if (!ep.text().equals(ap.text())) d.add(at + "text \"" + clip(ap.text()) + "\", expected \"" + clip(ep.text()) + "\"");
                if (!eq(ep.style(), ap.style())) d.add(at + "style " + ap.style() + ", expected " + ep.style());
                if (!ep.alignment().equals(ap.alignment())) d.add(at + "alignment " + ap.alignment() + ", expected " + ep.alignment());
                if (!ep.fontSizes().equals(ap.fontSizes())) d.add(at + "font sizes " + ap.fontSizes() + ", expected " + ep.fontSizes());
                if (ep.images().size() != ap.images().size()) d.add(at + ap.images().size() + " images, expected " + ep.images().size());
                for (int k = 0; k < Math.min(ep.images().size(), ap.images().size()); k++) {
                    var ei = ep.images().get(k);
                    var ai = ap.images().get(k);
                    if (ei.widthEmu() != ai.widthEmu() || ei.heightEmu() != ai.heightEmu())
                        d.add(at + "image " + k + " is " + ai.widthEmu() + "x" + ai.heightEmu() + " EMU, expected " + ei.widthEmu() + "x" + ei.heightEmu());
                }
            } else if (e instanceof Table et && a instanceof Table tt) {
                if (et.rows() != tt.rows() || et.columns() != tt.columns())
                    d.add(at + "table is " + tt.rows() + "x" + tt.columns() + ", expected " + et.rows() + "x" + et.columns());
                for (int r = 0; r < Math.min(et.rows(), tt.rows()); r++)
                    for (int c = 0; c < Math.min(et.cells().get(r).size(), tt.cells().get(r).size()); c++)
                        if (!et.cells().get(r).get(c).equals(tt.cells().get(r).get(c)))
                            d.add(at + "cell [" + r + "," + c + "] \"" + clip(tt.cells().get(r).get(c)) + "\", expected \"" + clip(et.cells().get(r).get(c)) + "\"");
            }
        }
        if (expected.section() != null && !expected.section().equals(actual.section()))
            d.add("section " + actual.section() + ", expected " + expected.section());
        return d;
    }

    private static boolean eq(Object a, Object b) {
        return a == null ? b == null : a.equals(b);
    }

    private static String clip(String s) {
        return s.length() <= 60 ? s : s.substring(0, 57) + "...";
    }
}
