package com.taikatranslator.geometry;

/** Invalid geometry is reported, never turned into a made-up position. */
public class GeometryException extends RuntimeException {

    public enum Reason {
        MISSING_COORDINATES,
        MALFORMED_POLYGON,
        NON_FINITE_VALUE,
        ZERO_AREA,
        OUT_OF_PAGE,
        UNIT_MISMATCH,
        MISSING_PAGE_METADATA,
        INVALID_PAGE_METADATA
    }

    private final Reason reason;

    public GeometryException(Reason reason, String message) {
        super(reason + ": " + message);
        this.reason = reason;
    }

    public Reason reason() {
        return reason;
    }
}
