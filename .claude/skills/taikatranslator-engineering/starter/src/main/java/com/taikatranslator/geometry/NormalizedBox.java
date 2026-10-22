package com.taikatranslator.geometry;

/**
 * The canonical coordinate system.
 *
 * <p>Axis-aligned box in displayed-page space: origin top-left, x right, y down,
 * all values in [0,1] of the displayed page width/height, after the page's
 * rotation is applied. Convert to points/twips/EMU only at output boundaries
 * ({@link #toPoints}).
 */
public record NormalizedBox(double x, double y, double width, double height) {

    private static final double EPS = 1e-9;

    public NormalizedBox {
        for (double v : new double[]{x, y, width, height})
            if (!Double.isFinite(v))
                throw new GeometryException(GeometryException.Reason.NON_FINITE_VALUE, "box has a non-finite value");
        if (x < -EPS || y < -EPS || x + width > 1 + EPS || y + height > 1 + EPS)
            throw new GeometryException(GeometryException.Reason.OUT_OF_PAGE,
                    String.format("box (%.4f, %.4f, %.4f, %.4f) leaves the page", x, y, width, height));
        if (width <= 0 || height <= 0)
            throw new GeometryException(GeometryException.Reason.ZERO_AREA, "box has zero width or height");
    }

    /**
     * Geometry comparisons must use a tolerance: the same region computed from
     * pixels and from inches differs in the last bits. Never use equals() for that.
     */
    public boolean approxEquals(NormalizedBox o, double eps) {
        return Math.abs(x - o.x) <= eps && Math.abs(y - o.y) <= eps
                && Math.abs(width - o.width) <= eps && Math.abs(height - o.height) <= eps;
    }

    public double right() { return x + width; }
    public double bottom() { return y + height; }

    /** Rotates clockwise by a multiple of 90 degrees around the page centre. */
    public NormalizedBox rotateClockwise(int degrees) {
        return switch (Math.floorMod(degrees, 360)) {
            case 0 -> this;
            case 90 -> new NormalizedBox(1 - bottom(), x, height, width);
            case 180 -> new NormalizedBox(1 - right(), 1 - bottom(), width, height);
            case 270 -> new NormalizedBox(y, 1 - right(), height, width);
            default -> throw new IllegalArgumentException("rotation must be a multiple of 90: " + degrees);
        };
    }

    /** Converts to points for a displayed page of the given size in points. */
    public double[] toPoints(double pageWidthPt, double pageHeightPt) {
        return new double[]{x * pageWidthPt, y * pageHeightPt, width * pageWidthPt, height * pageHeightPt};
    }
}
