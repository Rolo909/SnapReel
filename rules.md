# SnapReel — Coding Rules (`rules.md`)

## 1. Language & Runtime
- Python 3.11+ only. Use modern syntax: `match/case`, `type` aliases, `X | Y` unions.
- All code MUST pass `ruff check .` and `mypy --strict src/` with zero errors.
- UTF-8 everywhere. No BOM.

## 2. Code Style
- Line length: 100 characters max.
- Imports: sorted by `ruff` isort (first-party = `snapreel`).
- Docstrings: Google-style. Required for all public classes and functions.
- Type annotations: Required on ALL function signatures (params + return).
- No `Any` type unless explicitly justified with a `# type: ignore[<code>]` comment.
- f-strings preferred over `.format()` or `%`.

## 3. Architecture Invariants
- **Three-layer separation**: `core/` (domain logic) → `nodes/` (pipeline steps) → `gui/` (UI).
- `core/` and `nodes/` MUST NOT import from `gui/`. Ever.
- `gui/` MAY import from `core/` and `nodes/`.
- All pipeline nodes MUST inherit from `PipelineNode` ABC in `core/node_base.py`.
- Every node MUST implement `cleanup()` to free memory (models, tensors, caches).

## 4. Memory Safety
- After unloading any ML model: call `del model`, then `gc.collect()`.
- After GPU models: also call `torch.cuda.empty_cache()` if torch is available.
- NEVER load two ML models simultaneously unless `ExecutionProfile.name == "high"`.
- All file handles MUST use context managers (`with` statements).

## 5. Threading & Qt
- Heavy computation MUST run in `QThread` workers, never on the main thread.
- Cross-thread communication: Qt signals/slots only. No shared mutable state.
- Use `Qt.ConnectionType.QueuedConnection` for signals between threads.
- GUI updates MUST happen on the main thread only.

## 6. FFmpeg
- Call FFmpeg via `subprocess.run()` with explicit argument lists (no shell=True).
- Always check `returncode != 0` and raise `FFmpegError` with stderr.
- Use `-y` flag to overwrite output files.
- Log the full FFmpeg command at DEBUG level before execution.

## 7. Error Handling
- Use domain exceptions from `core/exceptions.py`.
- Never catch bare `Exception` unless re-raising.
- All node `execute()` methods must wrap errors in `NodeExecutionError`.
- User-facing error messages: bilingual (RU + EN) via i18n system.

## 8. Testing
- Unit tests: `tests/unit/test_<module>.py`. Minimum coverage target: 80%.
- Integration tests: `tests/integration/`. May be slow, marked with `@pytest.mark.slow`.
- GUI tests: use `pytest-qt` fixtures (`qtbot`).
- Mock external dependencies (FFmpeg, edge-tts network calls) in unit tests.

## 9. File Operations
- Use `pathlib.Path` exclusively. No `os.path`.
- All generated artifacts (images, audio, video) go to a temp project directory.
- Clean up intermediate files in `AssemblyNode.cleanup()`.

## 10. Logging
- Use `structlog` with bound loggers.
- Log levels: DEBUG (FFmpeg commands, model params), INFO (pipeline progress), WARNING (fallbacks), ERROR (failures).
- Every node logs entry/exit with timing.

## 11. Git & Task Plan
- After completing each implementation step, mark it as `[x]` in `TASK_PLAN.md`.
- Commits should be atomic — one logical change per commit.
- Commit message format: `feat(node): description` / `fix(gui): description` / `chore: description`.

## 12. Dependencies
- All deps declared in `pyproject.toml`. No inline `pip install`.
- Heavy optional deps (torch, diffusers) go in `[project.optional-dependencies.gpu]`.
- Pin minimum versions only (>=), let `uv.lock` handle exact resolution.
