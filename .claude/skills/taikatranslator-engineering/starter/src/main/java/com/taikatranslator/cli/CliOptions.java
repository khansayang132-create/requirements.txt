package com.taikatranslator.cli;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;

/**
 * Parses and validates the command line before any expensive work starts.
 *
 * <pre>
 * java -jar taikatranslator.jar --input ./in/contract.pdf --output-dir ./out --target-lang ES
 *      [--source-lang EN] [--overwrite]
 * </pre>
 */
public record CliOptions(Path input, Path outputDir, Optional<String> sourceLang, String targetLang, boolean overwrite) {

    public static final String USAGE = String.join("\n",
            "Usage: taikatranslator --input <file> --output-dir <dir> --target-lang <CODE> [--source-lang <CODE>] [--overwrite]",
            "  --input        PDF, PNG, JPEG or TIFF to translate (paths with spaces must be quoted)",
            "  --output-dir   directory for the DOCX and the processing report (created if missing)",
            "  --target-lang  DeepL target code, e.g. ES, DE, FR, EN-US, EN-GB, PT-BR, PT-PT",
            "  --source-lang  optional DeepL source code, e.g. EN; detected when omitted",
            "  --overwrite    replace an existing result instead of refusing");

    public static final class CliException extends Exception {
        public final ExitCode exitCode;

        public CliException(ExitCode exitCode, String message) {
            super(message);
            this.exitCode = exitCode;
        }
    }

    private static final Set<String> EXTENSIONS = Set.of("pdf", "png", "jpg", "jpeg", "tif", "tiff");
    private static final Pattern LANG = Pattern.compile("[A-Z]{2}(-[A-Z]{2,4})?");
    /** DeepL deprecated bare EN and PT as targets; the variant must be explicit. */
    private static final Set<String> AMBIGUOUS_TARGETS = Set.of("EN", "PT");

    public static CliOptions parse(String[] args) throws CliException {
        Path input = null, outputDir = null;
        String source = null, target = null;
        boolean overwrite = false;
        List<String> rest = new ArrayList<>(Arrays.asList(args));
        while (!rest.isEmpty()) {
            String flag = rest.remove(0);
            switch (flag) {
                case "--overwrite" -> overwrite = true;
                case "--input" -> input = Path.of(value(flag, rest));
                case "--output-dir" -> outputDir = Path.of(value(flag, rest));
                case "--source-lang" -> source = value(flag, rest).toUpperCase(Locale.ROOT);
                case "--target-lang" -> target = value(flag, rest).toUpperCase(Locale.ROOT);
                case "-h", "--help" -> throw new CliException(ExitCode.USAGE, USAGE);
                default -> throw new CliException(ExitCode.USAGE, "unknown argument '" + flag + "'\n" + USAGE);
            }
        }
        if (input == null) throw new CliException(ExitCode.USAGE, "--input is required\n" + USAGE);
        if (outputDir == null) throw new CliException(ExitCode.USAGE, "--output-dir is required\n" + USAGE);
        if (target == null) throw new CliException(ExitCode.USAGE, "--target-lang is required\n" + USAGE);
        if (!LANG.matcher(target).matches())
            throw new CliException(ExitCode.USAGE, "invalid --target-lang '" + target + "'");
        if (AMBIGUOUS_TARGETS.contains(target))
            throw new CliException(ExitCode.USAGE, "--target-lang " + target + " is ambiguous; use " + target + "-" + (target.equals("EN") ? "US or EN-GB" : "BR or PT-PT"));
        if (source != null && !Pattern.matches("[A-Z]{2}", source))
            throw new CliException(ExitCode.USAGE, "invalid --source-lang '" + source + "' (source codes have no variant)");
        return new CliOptions(input, outputDir, Optional.ofNullable(source), target, overwrite);
    }

    private static String value(String flag, List<String> rest) throws CliException {
        if (rest.isEmpty() || rest.get(0).startsWith("--"))
            throw new CliException(ExitCode.USAGE, flag + " needs a value\n" + USAGE);
        return rest.remove(0);
    }

    /** Filesystem checks. Returns the DOCX path the run will write. */
    public Path validateFilesystem() throws CliException {
        if (!Files.exists(input)) throw new CliException(ExitCode.INPUT_ERROR, "input not found: " + input);
        if (!Files.isRegularFile(input)) throw new CliException(ExitCode.INPUT_ERROR, "input is not a file: " + input);
        if (!Files.isReadable(input)) throw new CliException(ExitCode.INPUT_ERROR, "input is not readable: " + input);
        String name = input.getFileName().toString();
        int dot = name.lastIndexOf('.');
        String ext = dot < 0 ? "" : name.substring(dot + 1).toLowerCase(Locale.ROOT);
        if (!EXTENSIONS.contains(ext))
            throw new CliException(ExitCode.INPUT_ERROR, "unsupported file type '." + ext + "'; expected one of " + EXTENSIONS);
        String sniffed = sniff(input);
        if (sniffed == null || !sameFamily(ext, sniffed))
            throw new CliException(ExitCode.INPUT_ERROR, "file content does not match its ." + ext + " extension");

        try {
            Files.createDirectories(outputDir);
        } catch (IOException e) {
            throw new CliException(ExitCode.INPUT_ERROR, "cannot create output directory: " + outputDir);
        }
        if (!Files.isDirectory(outputDir) || !Files.isWritable(outputDir))
            throw new CliException(ExitCode.INPUT_ERROR, "output directory is not writable: " + outputDir);

        String base = dot < 0 ? name : name.substring(0, dot);
        Path docx = outputDir.resolve(base + "." + targetLang + ".docx");
        if (Files.exists(docx) && !overwrite)
            throw new CliException(ExitCode.OUTPUT_EXISTS, "result already exists: " + docx + " (use --overwrite to replace it)");
        return docx;
    }

    static String sniff(Path file) throws CliException {
        byte[] h;
        try (InputStream in = Files.newInputStream(file)) {
            h = in.readNBytes(8);
        } catch (IOException e) {
            throw new CliException(ExitCode.INPUT_ERROR, "cannot read input: " + file);
        }
        if (h.length >= 5 && h[0] == '%' && h[1] == 'P' && h[2] == 'D' && h[3] == 'F' && h[4] == '-') return "pdf";
        if (h.length >= 8 && (h[0] & 0xFF) == 0x89 && h[1] == 'P' && h[2] == 'N' && h[3] == 'G') return "png";
        if (h.length >= 3 && (h[0] & 0xFF) == 0xFF && (h[1] & 0xFF) == 0xD8 && (h[2] & 0xFF) == 0xFF) return "jpeg";
        if (h.length >= 4 && ((h[0] == 'I' && h[1] == 'I' && h[2] == 42 && h[3] == 0) || (h[0] == 'M' && h[1] == 'M' && h[2] == 0 && h[3] == 42))) return "tiff";
        return null;
    }

    private static boolean sameFamily(String ext, String sniffed) {
        return switch (ext) {
            case "jpg", "jpeg" -> sniffed.equals("jpeg");
            case "tif", "tiff" -> sniffed.equals("tiff");
            default -> sniffed.equals(ext);
        };
    }
}
