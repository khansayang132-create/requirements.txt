package com.taikatranslator.validation;

import java.io.IOException;
import java.nio.file.AtomicMoveNotSupportedException;
import java.nio.file.FileAlreadyExistsException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;

/**
 * Write to a temp file next to the destination, validate, then move into place.
 *
 * <p>The temp file lives in the destination directory so the move is a rename
 * on the same filesystem, which POSIX and NTFS make atomic. Readers never see a
 * half-written DOCX. An existing result is never overwritten unless asked.
 */
public final class AtomicPublisher {

    public enum Mode { ATOMIC, NON_ATOMIC_FALLBACK }

    /** Creates a temp file in the target's directory. Caller writes, validates, then calls {@link #publish}. */
    public Path stage(Path target) throws IOException {
        Path dir = target.toAbsolutePath().getParent();
        Files.createDirectories(dir);
        return Files.createTempFile(dir, "." + target.getFileName() + ".", ".part");
    }

    public Mode publish(Path staged, Path target, boolean overwrite) throws IOException {
        if (!overwrite) return publishNoClobber(staged, target);
        try {
            Files.move(staged, target, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
            return Mode.ATOMIC;
        } catch (AtomicMoveNotSupportedException e) {
            Files.move(staged, target, StandardCopyOption.REPLACE_EXISTING);
            return Mode.NON_ATOMIC_FALLBACK;
        }
    }

    /**
     * An atomic rename silently replaces an existing target on POSIX, so a
     * check-then-move has a race. A hard link fails if the target exists,
     * which makes "create only if absent" atomic where links are supported.
     */
    private Mode publishNoClobber(Path staged, Path target) throws IOException {
        if (Files.exists(target))
            throw new FileAlreadyExistsException(target.toString(), null, "refusing to overwrite an existing result");
        try {
            Files.createLink(target, staged);
        } catch (FileAlreadyExistsException e) {
            throw new FileAlreadyExistsException(target.toString(), null, "refusing to overwrite an existing result");
        } catch (UnsupportedOperationException | IOException e) {
            if (Files.exists(target)) throw new FileAlreadyExistsException(target.toString(), null, "refusing to overwrite an existing result");
            Files.move(staged, target);
            return Mode.NON_ATOMIC_FALLBACK;
        }
        Files.delete(staged);
        return Mode.ATOMIC;
    }

    /** Removes a staged file after a failed validation; keeps it if {@code keepForDiagnostics}. */
    public void discard(Path staged, boolean keepForDiagnostics) throws IOException {
        if (keepForDiagnostics) {
            Path kept = staged.resolveSibling(staged.getFileName().toString().replace(".part", ".failed"));
            Files.move(staged, kept, StandardCopyOption.REPLACE_EXISTING);
        } else {
            Files.deleteIfExists(staged);
        }
    }
}
