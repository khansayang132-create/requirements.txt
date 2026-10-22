package com.taikatranslator.pipeline;

import com.fasterxml.jackson.databind.JsonNode;
import com.taikatranslator.geometry.CoordinateNormalizer;
import com.taikatranslator.geometry.PageInfo;
import com.taikatranslator.pipeline.CanonicalDocument.Block;
import com.taikatranslator.pipeline.CanonicalDocument.Paragraph;
import com.taikatranslator.pipeline.CanonicalDocument.Role;
import com.taikatranslator.pipeline.CanonicalDocument.Table;
import com.taikatranslator.provider.AzureLayoutClient;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * analyzeResult (prebuilt-layout) → {@link CanonicalDocument}.
 *
 * <p>Azure lists the paragraphs inside table cells in {@code paragraphs} too.
 * They are dropped by span containment so table text isn't emitted twice.
 * Blocks are ordered by the reading order Azure returns (span offset).
 */
public final class AzureLayoutMapper {

    private final CoordinateNormalizer normalizer;
    private final List<String> recoveries = new ArrayList<>();

    public AzureLayoutMapper(CoordinateNormalizer normalizer) {
        this.normalizer = normalizer;
    }

    public List<String> recoveries() {
        return List.copyOf(recoveries);
    }

    public CanonicalDocument map(JsonNode result) {
        List<PageInfo> pages = AzureLayoutClient.pages(result);
        Map<Integer, PageInfo> byNumber = new HashMap<>();
        for (PageInfo p : pages) byNumber.put(p.pageNumber(), p);

        List<long[]> tableSpans = new ArrayList<>();
        List<Ordered> ordered = new ArrayList<>();

        int t = 0;
        for (JsonNode table : result.path("tables")) {
            String id = "t" + (++t);
            int rows = table.path("rowCount").asInt(), cols = table.path("columnCount").asInt();
            List<List<String>> cells = new ArrayList<>();
            for (int r = 0; r < rows; r++) {
                List<String> row = new ArrayList<>();
                for (int c = 0; c < cols; c++) row.add("");
                cells.add(row);
            }
            for (JsonNode cell : table.path("cells")) {
                int r = cell.path("rowIndex").asInt(), c = cell.path("columnIndex").asInt();
                if (r >= rows || c >= cols) throw new IllegalStateException(id + ": cell [" + r + "," + c + "] outside " + rows + "x" + cols);
                cells.get(r).set(c, cell.path("content").asText(""));
            }
            for (JsonNode s : table.path("spans")) tableSpans.add(new long[]{s.path("offset").asLong(), s.path("offset").asLong() + s.path("length").asLong()});
            Located loc = locate(id, table, byNumber);
            ordered.add(new Ordered(firstOffset(table), new Table(id, rows, cols, cells, loc.page, loc.result.box())));
        }

        int p = 0;
        for (JsonNode para : result.path("paragraphs")) {
            long off = firstOffset(para);
            if (insideAny(off, tableSpans)) continue;
            String id = "p" + (++p);
            Located loc = locate(id, para, byNumber);
            ordered.add(new Ordered(off, new Paragraph(id, role(para.path("role").asText("")), para.path("content").asText(""), loc.page, loc.result.box())));
        }

        ordered.sort(Comparator.comparingLong(Ordered::offset));
        return new CanonicalDocument(pages, ordered.stream().map(Ordered::block).toList());
    }

    private record Ordered(long offset, Block block) { }

    private record Located(int page, CoordinateNormalizer.Result result) { }

    private Located locate(String id, JsonNode element, Map<Integer, PageInfo> pages) {
        JsonNode region = element.path("boundingRegions").path(0);
        int pageNumber = region.path("pageNumber").asInt(-1);
        PageInfo page = pages.get(pageNumber);
        if (page == null) throw new IllegalStateException(id + ": bounding region refers to unknown page " + pageNumber);
        CoordinateNormalizer.Result r = normalizer.normalize(AzureLayoutClient.polygon(region), page);
        r.recoveries().forEach(msg -> recoveries.add(id + ": " + msg));
        return new Located(pageNumber, r);
    }

    private static long firstOffset(JsonNode element) {
        return element.path("spans").path(0).path("offset").asLong(Long.MAX_VALUE);
    }

    private static boolean insideAny(long offset, List<long[]> spans) {
        for (long[] s : spans) if (offset >= s[0] && offset < s[1]) return true;
        return false;
    }

    static Role role(String azureRole) {
        return switch (azureRole) {
            case "title" -> Role.TITLE;
            case "sectionHeading" -> Role.HEADING;
            case "pageHeader" -> Role.HEADER;
            case "pageFooter" -> Role.FOOTER;
            case "footnote" -> Role.FOOTNOTE;
            case "pageNumber" -> Role.PAGE_NUMBER;
            default -> Role.BODY;
        };
    }
}
