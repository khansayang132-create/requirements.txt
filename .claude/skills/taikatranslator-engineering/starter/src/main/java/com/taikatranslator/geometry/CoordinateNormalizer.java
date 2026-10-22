package com.taikatranslator.geometry;

import java.util.ArrayList;
import java.util.List;

/**
 * Converts provider coordinates into {@link NormalizedBox}.
 *
 * <p>Documented recovery: a box that overflows the page by at most
 * {@code clampTolerance} (fraction of the page) is clamped and the result
 * carries a recovery note. Anything worse is a {@link GeometryException}.
 * Providers often report polygons a hair outside the page for text touching
 * the edge; real overflow means wrong units or wrong page metadata.
 */
public final class CoordinateNormalizer {

    public record Result(NormalizedBox box, List<String> recoveries) {
        public Result {
            recoveries = List.copyOf(recoveries);
        }

        public boolean recovered() {
            return !recoveries.isEmpty();
        }
    }

    private final double clampTolerance;

    public CoordinateNormalizer(double clampTolerance) {
        if (!(clampTolerance >= 0 && clampTolerance < 0.5))
            throw new IllegalArgumentException("clampTolerance must be in [0, 0.5)");
        this.clampTolerance = clampTolerance;
    }

    public CoordinateNormalizer() {
        this(0.01);
    }

    /**
     * @param polygon x1,y1,x2,y2,... in the page's unit (Azure order: clockwise from top-left)
     */
    public Result normalize(double[] polygon, PageInfo page) {
        if (polygon == null || polygon.length == 0)
            throw new GeometryException(GeometryException.Reason.MISSING_COORDINATES, "page " + page.pageNumber() + ": no polygon");
        if (polygon.length < 4 || polygon.length % 2 != 0)
            throw new GeometryException(GeometryException.Reason.MALFORMED_POLYGON,
                    "page " + page.pageNumber() + ": polygon needs an even number of values (>= 4), got " + polygon.length);

        double minX = Double.POSITIVE_INFINITY, minY = Double.POSITIVE_INFINITY;
        double maxX = Double.NEGATIVE_INFINITY, maxY = Double.NEGATIVE_INFINITY;
        for (int i = 0; i < polygon.length; i += 2) {
            double px = polygon[i], py = polygon[i + 1];
            if (!Double.isFinite(px) || !Double.isFinite(py))
                throw new GeometryException(GeometryException.Reason.NON_FINITE_VALUE, "page " + page.pageNumber() + ": non-finite coordinate");
            minX = Math.min(minX, px); maxX = Math.max(maxX, px);
            minY = Math.min(minY, py); maxY = Math.max(maxY, py);
        }

        double w = page.unit() == PageInfo.Unit.NORMALIZED ? 1.0 : page.width();
        double h = page.unit() == PageInfo.Unit.NORMALIZED ? 1.0 : page.height();
        double x0 = minX / w, x1 = maxX / w, y0 = minY / h, y1 = maxY / h;

        if (page.unit() == PageInfo.Unit.NORMALIZED && (x1 > 1.5 || y1 > 1.5))
            throw new GeometryException(GeometryException.Reason.UNIT_MISMATCH,
                    "page " + page.pageNumber() + ": values up to " + Math.max(maxX, maxY) + " labelled NORMALIZED; are these pixels?");

        if (x1 - x0 <= 0 || y1 - y0 <= 0)
            throw new GeometryException(GeometryException.Reason.ZERO_AREA, "page " + page.pageNumber() + ": polygon has zero width or height");

        List<String> recoveries = new ArrayList<>();
        double t = clampTolerance;
        if (x0 < -t || y0 < -t || x1 > 1 + t || y1 > 1 + t)
            throw new GeometryException(GeometryException.Reason.OUT_OF_PAGE, String.format(
                    "page %d: box [%.4f..%.4f]x[%.4f..%.4f] exceeds tolerance %.3f",
                    page.pageNumber(), x0, x1, y0, y1, t));
        if (x0 < 0 || y0 < 0 || x1 > 1 || y1 > 1) {
            recoveries.add(String.format("clamped box [%.4f..%.4f]x[%.4f..%.4f] to the page", x0, x1, y0, y1));
            x0 = Math.max(0, x0); y0 = Math.max(0, y0);
            x1 = Math.min(1, x1); y1 = Math.min(1, y1);
            if (x1 - x0 <= 0 || y1 - y0 <= 0)
                throw new GeometryException(GeometryException.Reason.ZERO_AREA, "page " + page.pageNumber() + ": nothing left after clamping");
        }

        NormalizedBox box = new NormalizedBox(x0, y0, x1 - x0, y1 - y0).rotateClockwise(page.rotation());
        return new Result(box, recoveries);
    }
}
