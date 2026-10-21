# Development workflow

- Use `dev` for changes between releases. Do not merge into `main`, move release tags, or publish releases unless the user explicitly requests it.
- Push/upload only when the user explicitly requests it. This applies to **all branches, including `dev`**; permission for one upload does not authorize future uploads.
- Local editing, testing, building, or committing does not imply permission to push.

# Maintenance boundaries

- Application identity/version: edit `src/app_metadata.py` only. CSV provenance re-exports these constants for compatibility; the build spec derives Windows version resources from them.
- Atomic file replacement: use `src/file_io.py`. Callers keep ownership of serialization, validation, cache schemas, backup rotation and error handling.
- Legacy-file migration is deliberately separate: `runtime_paths._migrate_file` must never overwrite an existing destination. Do not replace its exclusive-copy behavior with atomic replacement.
- Prefer removing duplicate definitions and clarifying interfaces over splitting files solely by size. Preserve search semantics and saved-data compatibility during maintenance refactors.
