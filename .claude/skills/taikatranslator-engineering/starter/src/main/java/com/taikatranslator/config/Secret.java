package com.taikatranslator.config;

import java.util.Objects;

/**
 * A credential that can't be logged by accident: toString() never shows the
 * value, and equals/hashCode are identity-based so it never ends up in a
 * config hash or a map key by value.
 */
public final class Secret {
    private final String value;

    private Secret(String value) {
        this.value = value;
    }

    public static Secret of(String value) {
        Objects.requireNonNull(value, "secret value");
        if (value.isBlank()) throw new IllegalArgumentException("secret is blank");
        return new Secret(value);
    }

    /** The only way to read the value. Call it at the HTTP header, nowhere else. */
    public String reveal() {
        return value;
    }

    @Override
    public String toString() {
        return "[REDACTED]";
    }
}
