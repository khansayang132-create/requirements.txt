package com.taikatranslator.geometry;

/**
 * Page metadata as the extraction provider reported it.
 *
 * <p>Azure Document Intelligence reports {@code unit = "inch"} for PDF and TIFF
 * pages and {@code "pixel"} for images; width/height are in that unit. PDFBox
 * reports points (1/72 inch). Rotation is the PDF {@code /Rotate} value:
 * clockwise degrees the viewer applies when displaying the page.
 *
 * @param pageNumber 1-based
 * @param rotation   0, 90, 180 or 270 (other multiples of 90 are normalized)
 */
public record PageInfo(int pageNumber, double width, double height, Unit unit, int rotation) {

    public enum Unit {
        PIXEL, INCH, POINT,
        /** Already in [0,1] page space. */
        NORMALIZED;

        public static Unit fromAzure(String unit) {
            if (unit == null) throw new GeometryException(GeometryException.Reason.MISSING_PAGE_METADATA, "page unit is missing");
            return switch (unit.toLowerCase()) {
                case "pixel" -> PIXEL;
                case "inch" -> INCH;
                default -> throw new GeometryException(GeometryException.Reason.INVALID_PAGE_METADATA, "unknown page unit '" + unit + "'");
            };
        }
    }

    public PageInfo {
        if (unit == null)
            throw new GeometryException(GeometryException.Reason.MISSING_PAGE_METADATA, "page " + pageNumber + ": unit is missing");
        if (unit != Unit.NORMALIZED && (!(width > 0) || !(height > 0) || !Double.isFinite(width) || !Double.isFinite(height)))
            throw new GeometryException(GeometryException.Reason.INVALID_PAGE_METADATA,
                    "page " + pageNumber + ": width/height must be positive and finite, got " + width + "x" + height);
        if (rotation % 90 != 0)
            throw new GeometryException(GeometryException.Reason.INVALID_PAGE_METADATA,
                    "page " + pageNumber + ": rotation must be a multiple of 90, got " + rotation);
        rotation = Math.floorMod(rotation, 360);
    }

    public boolean landscape() {
        boolean wide = unit == Unit.NORMALIZED || width > height;
        return (rotation == 90 || rotation == 270) != wide;
    }
}
