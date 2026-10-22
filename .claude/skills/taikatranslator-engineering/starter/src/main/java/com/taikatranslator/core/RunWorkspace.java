package com.taikatranslator.core;

import java.io.IOException;
import java.nio.file.FileSystems;
import java.nio.file.FileVisitResult;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.attribute.BasicFileAttributes;
import java.nio.file.attribute.PosixFilePermissions;

/**
 * TSK-6.6. One private temp directory per run.
 *
 * <ul>
 *   <li>Unpredictable name ({@code taika-<runId>-<random>}), owner-only (rwx------) on POSIX.</li>
 *   <li>{@link #finish} deletes it after success; after failure, or with keepTemp, it is
 *       kept and its path goes in the report so diagnostics can be inspected.</li>
 *   <li>Deletion never follows symlinks out of the workspace.</li>
 * </ul>
 */
public final class RunWorkspace {

    public enum Disposition { DELETED, KEPT_FOR_DIAGNOSTICS, KEPT_ON_REQUEST }

    private final Path dir;

    private RunWorkspace(Path dir) {
        this.dir = dir;
    }

    public static RunWorkspace create(Path parent, String runId) throws IOException {
        if (!runId.matches("[A-Za-z0-9_-]{1,64}")) throw new IllegalArgumentException("runId must be [A-Za-z0-9_-]{1,64}");
        Files.createDirectories(parent);
        Path dir;
        if (FileSystems.getDefault().supportedFileAttributeViews().contains("posix")) {
            dir = Files.createTempDirectory(parent, "taika-" + runId + "-",
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        } else {
            dir = Files.createTempDirectory(parent, "taika-" + runId + "-");
        }
        return new RunWorkspace(dir);
    }

    public Path dir() {
        return dir;
    }

    /** A path inside the workspace; rejects names that would escape it. */
    public Path resolve(String name) {
        Path p = dir.resolve(name).normalize();
        if (!p.startsWith(dir)) throw new IllegalArgumentException("path escapes the workspace: " + name);
        return p;
    }

    public Disposition finish(boolean success, boolean keepTemp) throws IOException {
        if (keepTemp) return Disposition.KEPT_ON_REQUEST;
        if (!success) return Disposition.KEPT_FOR_DIAGNOSTICS;
        deleteTree(dir);
        return Disposition.DELETED;
    }

    static void deleteTree(Path root) throws IOException {
        if (!Files.exists(root)) return;
        Files.walkFileTree(root, new SimpleFileVisitor<>() {
            @Override
            public FileVisitResult visitFile(Path file, BasicFileAttributes attrs) throws IOException {
                Files.delete(file); // a symlink is deleted itself, never its target
                return FileVisitResult.CONTINUE;
            }

            @Override
            public FileVisitResult postVisitDirectory(Path d, IOException e) throws IOException {
                if (e != null) throw e;
                Files.delete(d);
                return FileVisitResult.CONTINUE;
            }
        });
    }
}
