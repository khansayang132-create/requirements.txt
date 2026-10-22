package com.taikatranslator.cli;

/**
 * Process exit codes. Document these in the README; scripts and CI depend on them.
 * 2 follows the Unix convention for bad usage; 130 is 128 + SIGINT.
 */
public enum ExitCode {
    OK(0),
    /** At least one stage finished with warnings (e.g. layout overflow) but outputs validated. */
    OK_WITH_WARNINGS(1),
    USAGE(2),
    INPUT_ERROR(3),
    CONFIG_ERROR(4),
    PROVIDER_ERROR(5),
    PROCESSING_ERROR(6),
    VALIDATION_FAILED(7),
    OUTPUT_EXISTS(8),
    INTERRUPTED(130);

    public final int code;

    ExitCode(int code) {
        this.code = code;
    }
}
