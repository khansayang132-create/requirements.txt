package com.taikatranslator.geometry;

import org.junit.jupiter.api.Test;

import static com.taikatranslator.geometry.GeometryException.Reason.*;
import static org.junit.jupiter.api.Assertions.*;

/** TSK-5.2.2. Every case either yields a documented box or an explicit reason. */
class CoordinateNormalizerTest {

    private static final double E = 1e-9;
    private final CoordinateNormalizer n = new CoordinateNormalizer(0.01);
    private final PageInfo letterInches = new PageInfo(1, 8.5, 11, PageInfo.Unit.INCH, 0);

    private static double[] rect(double x, double y, double w, double h) {
        return new double[]{x, y, x + w, y, x + w, y + h, x, y + h};
    }

    private static void assertBox(NormalizedBox b, double x, double y, double w, double h) {
        assertEquals(x, b.x(), 1e-6, "x");
        assertEquals(y, b.y(), 1e-6, "y");
        assertEquals(w, b.width(), 1e-6, "w");
        assertEquals(h, b.height(), 1e-6, "h");
    }

    private void assertReason(GeometryException.Reason r, Runnable call) {
        GeometryException e = assertThrows(GeometryException.class, call::run);
        assertEquals(r, e.reason(), e.getMessage());
    }

    @Test
    void inchPolygonOnPortraitPage() {
        var r = n.normalize(rect(0.85, 1.1, 4.25, 2.2), letterInches);
        assertBox(r.box(), 0.1, 0.1, 0.5, 0.2);
        assertFalse(r.recovered());
    }

    @Test
    void pixelPolygonOnLandscapeImage() {
        PageInfo img = new PageInfo(1, 2000, 1000, PageInfo.Unit.PIXEL, 0);
        assertTrue(img.landscape());
        assertBox(n.normalize(rect(500, 250, 1000, 500), img).box(), 0.25, 0.25, 0.5, 0.5);
    }

    @Test
    void pixelAndInchInputsForSameRegionAgree() {
        PageInfo px = new PageInfo(1, 850, 1100, PageInfo.Unit.PIXEL, 0);
        var a = n.normalize(rect(85, 110, 425, 220), px).box();
        var b = n.normalize(rect(0.85, 1.1, 4.25, 2.2), letterInches).box();
        assertTrue(a.approxEquals(b, 1e-9), a + " vs " + b);
    }

    @Test
    void alreadyNormalizedPassesThrough() {
        PageInfo norm = new PageInfo(1, 1, 1, PageInfo.Unit.NORMALIZED, 0);
        assertBox(n.normalize(rect(0.2, 0.3, 0.4, 0.1), norm).box(), 0.2, 0.3, 0.4, 0.1);
    }

    @Test
    void pixelsMislabelledAsNormalizedAreCaught() {
        PageInfo norm = new PageInfo(1, 1, 1, PageInfo.Unit.NORMALIZED, 0);
        assertReason(UNIT_MISMATCH, () -> n.normalize(rect(100, 100, 50, 50), norm));
    }

    @Test
    void multiplePageSizesNormalizeIndependently() {
        PageInfo a4Points = new PageInfo(1, 595.28, 841.89, PageInfo.Unit.POINT, 0);
        PageInfo a3Points = new PageInfo(2, 841.89, 1190.55, PageInfo.Unit.POINT, 0);
        var small = n.normalize(rect(0, 0, 595.28 / 2, 841.89 / 2), a4Points).box();
        var big = n.normalize(rect(0, 0, 841.89 / 2, 1190.55 / 2), a3Points).box();
        assertTrue(small.approxEquals(big, 1e-9), small + " vs " + big);
    }

    @Test
    void zeroWidthAndZeroHeightAreErrors() {
        assertReason(ZERO_AREA, () -> n.normalize(rect(1, 1, 0, 2), letterInches));
        assertReason(ZERO_AREA, () -> n.normalize(rect(1, 1, 2, 0), letterInches));
    }

    @Test
    void missingAndMalformedCoordinates() {
        assertReason(MISSING_COORDINATES, () -> n.normalize(null, letterInches));
        assertReason(MISSING_COORDINATES, () -> n.normalize(new double[0], letterInches));
        assertReason(MALFORMED_POLYGON, () -> n.normalize(new double[]{1, 2, 3}, letterInches));
        assertReason(MALFORMED_POLYGON, () -> n.normalize(new double[]{1, 2}, letterInches));
        assertReason(NON_FINITE_VALUE, () -> n.normalize(new double[]{1, 2, Double.NaN, 4}, letterInches));
        assertReason(NON_FINITE_VALUE, () -> n.normalize(new double[]{1, 2, Double.POSITIVE_INFINITY, 4}, letterInches));
    }

    @Test
    void slightOverflowIsClampedWithARecoveryNote() {
        var r = n.normalize(rect(-0.05, 0.0, 1.0, 1.0), letterInches);
        assertTrue(r.recovered());
        assertEquals(0.0, r.box().x(), E);
        assertTrue(r.recoveries().get(0).startsWith("clamped"));
    }

    @Test
    void realOverflowAndNegativeCoordinatesAreErrors() {
        assertReason(OUT_OF_PAGE, () -> n.normalize(rect(-2, 1, 1, 1), letterInches));
        assertReason(OUT_OF_PAGE, () -> n.normalize(rect(8, 10, 3, 3), letterInches));
    }

    @Test
    void rotationIsAppliedClockwise() {
        // A box in the top-left corner of the unrotated page.
        PageInfo r90 = new PageInfo(1, 8.5, 11, PageInfo.Unit.INCH, 90);
        PageInfo r180 = new PageInfo(1, 8.5, 11, PageInfo.Unit.INCH, 180);
        PageInfo r270 = new PageInfo(1, 8.5, 11, PageInfo.Unit.INCH, -90);
        double[] poly = rect(0, 0, 0.85, 2.2); // normalized (0,0,0.1,0.2)
        assertBox(n.normalize(poly, r90).box(), 0.8, 0.0, 0.2, 0.1);   // top-right
        assertBox(n.normalize(poly, r180).box(), 0.9, 0.8, 0.1, 0.2);  // bottom-right
        assertBox(n.normalize(poly, r270).box(), 0.0, 0.9, 0.2, 0.1);  // bottom-left
        assertTrue(r90.landscape(), "portrait page rotated 90 displays landscape");
    }

    @Test
    void fourRotationsReturnTheOriginalBox() {
        NormalizedBox b = new NormalizedBox(0.1, 0.2, 0.3, 0.4);
        assertBox(b.rotateClockwise(90).rotateClockwise(90).rotateClockwise(90).rotateClockwise(90), 0.1, 0.2, 0.3, 0.4);
    }

    @Test
    void missingOrInconsistentPageMetadata() {
        assertReason(MISSING_PAGE_METADATA, () -> new PageInfo(1, 8.5, 11, null, 0));
        assertReason(INVALID_PAGE_METADATA, () -> new PageInfo(1, 0, 11, PageInfo.Unit.INCH, 0));
        assertReason(INVALID_PAGE_METADATA, () -> new PageInfo(1, Double.NaN, 11, PageInfo.Unit.INCH, 0));
        assertReason(INVALID_PAGE_METADATA, () -> new PageInfo(1, 8.5, 11, PageInfo.Unit.INCH, 45));
        assertReason(INVALID_PAGE_METADATA, () -> PageInfo.Unit.fromAzure("cm"));
        assertReason(MISSING_PAGE_METADATA, () -> PageInfo.Unit.fromAzure(null));
        assertEquals(PageInfo.Unit.INCH, PageInfo.Unit.fromAzure("inch"));
    }

    @Test
    void toPointsConvertsAtTheBoundary() {
        double[] pt = new NormalizedBox(0.5, 0.5, 0.25, 0.25).toPoints(612, 792);
        assertArrayEquals(new double[]{306, 396, 153, 198}, pt, 1e-9);
    }

    @Test
    void sameInputGivesSameOutput() {
        double[] poly = rect(1.234, 5.678, 2.5, 1.25);
        assertEquals(n.normalize(poly, letterInches), n.normalize(poly.clone(), letterInches));
    }
}
