# SnapReel — Task Plan (TASK_PLAN.md)

## Phase A: Project Scaffolding & Infrastructure

- [ ] **A1** — Project skeleton: `pyproject.toml`, directory structure, `__init__.py` files, `__main__.py` entry point.
  - Files: `pyproject.toml`, `src/snapreel/__init__.py`, `src/snapreel/__main__.py`, all `__init__.py` files.
  - Verify: `uv sync --dev` succeeds, `python -m snapreel --help` prints version.

- [ ] **A2** — Core domain: `PipelineContext`, `PipelineNode` ABC, domain exceptions, `AppConfig`.
  - Files: `src/snapreel/core/context.py`, `core/node_base.py`, `core/exceptions.py`, `core/config.py`.
  - Verify: `ruff check src/` and `mypy --strict src/snapreel/core/` pass.

- [ ] **A3** — Infrastructure: `HardwareProfiler` (detect CPU, RAM, GPU/VRAM), `ExecutionProfile` dataclass.
  - Files: `src/snapreel/infra/hardware.py`.
  - Verify: `pytest tests/unit/test_hardware_profiler.py` passes, `ruff check .`.

- [ ] **A4** — Infrastructure: `ModelDownloader` with `huggingface_hub`, progress callback, SHA256 check, resume support.
  - Files: `src/snapreel/infra/downloader.py`.
  - Verify: `pytest tests/unit/test_downloader.py` passes (mocked downloads).

- [ ] **A5** — Infrastructure: `FFmpegManager` — locate/download ffmpeg binary, command builder helper.
  - Files: `src/snapreel/infra/ffmpeg.py`.
  - Verify: `pytest tests/unit/test_ffmpeg.py` passes.

- [ ] **A6** — Utilities: structured logging (`structlog`), path resolver, input validators.
  - Files: `src/snapreel/utils/logging.py`, `utils/paths.py`, `utils/validators.py`.
  - Verify: `ruff check .` and `mypy --strict src/snapreel/utils/` pass.

- [ ] **A7** — Infrastructure: `ComfyUIClient` — headless launcher, health check, workflow submission via REST API, result polling.
  - Files: `src/snapreel/infra/comfyui_client.py`.
  - Verify: `pytest tests/unit/test_comfyui_client.py` passes (mocked HTTP).

## Phase B: Pipeline Nodes

- [ ] **B1** — ScenarioNode: llama-cpp-python integration, GBNF grammar file, system prompt template, JSON parsing.
  - Files: `src/snapreel/nodes/scenario.py`, `grammars/scenario.gbnf`, `prompts/scenario_system.txt`.
  - Verify: `pytest tests/unit/test_scenario_node.py` passes (mocked LLM).

- [ ] **B2** — AudioNode: edge-tts async wrapper, per-scene WAV generation, SSML breaks, voice selection.
  - Files: `src/snapreel/nodes/audio_tts.py`.
  - Verify: `pytest tests/unit/test_audio_node.py` passes (mocked edge-tts).

- [ ] **B3** — VisualStaticNode (Path A): diffusers SDXL-Turbo loader, image generation, Pillow crop to 9:16, Ken Burns FFmpeg command.
  - Files: `src/snapreel/nodes/visual_static.py`.
  - Verify: `pytest tests/unit/test_visual_static.py` passes (mocked diffusers).

- [ ] **B3.1** — VisualVideoNode (Path B): ComfyUI workflow builder, headless server lifecycle management, LTX-Video / Wan 2.1 3-sec clip generation, result download, upscale via Real-ESRGAN.
  - Files: `src/snapreel/nodes/visual_video.py`.
  - Verify: `pytest tests/unit/test_visual_video.py` passes (mocked ComfyUI API).

- [ ] **B4** — SubtitleNode: faster-whisper word timestamps, .ass file generation with karaoke styling.
  - Files: `src/snapreel/nodes/subtitle.py`.
  - Verify: `pytest tests/unit/test_subtitle_node.py` passes (mocked whisper).

- [ ] **B5** — AssemblyNode: FFmpeg master command builder — concat segments, mix audio with ducking, burn subtitles.
  - Files: `src/snapreel/nodes/assembly.py`.
  - Verify: `pytest tests/unit/test_assembly_node.py` passes (mocked subprocess).

## Phase C: Pipeline Orchestrator

- [ ] **C1** — `PipelineOrchestrator` QThread worker: sequential node execution, progress signals, error handling, cancellation support.
  - Files: `src/snapreel/core/orchestrator.py`.
  - Verify: `pytest tests/unit/test_orchestrator.py` passes.

## Phase D: GUI

- [ ] **D1** — App bootstrap: `QApplication`, dark theme QSS, font loading, `MainWindow` skeleton with tab bar.
  - Files: `src/snapreel/app.py`, `src/snapreel/gui/main_window.py`, `src/snapreel/gui/styles/dark_theme.qss`.
  - Verify: `python -m snapreel` launches window without errors.

- [ ] **D2** — ProjectWizard widget: topic input, style selector, voice picker, visual mode toggle, scene count, music file browser.
  - Files: `src/snapreel/gui/widgets/project_wizard.py`.
  - Verify: Manual visual check + `pytest tests/unit/test_gui.py` (pytest-qt).

- [ ] **D3** — PipelineControl & ProgressDashboard: start/stop buttons, per-node progress bars, status labels.
  - Files: `src/snapreel/gui/widgets/pipeline_control.py`, `gui/widgets/progress_dashboard.py`.
  - Verify: Widget renders correctly, signals connected.

- [ ] **D4** — SettingsPanel: hardware profile display, manual overrides, paths config, language selector (RU/EN).
  - Files: `src/snapreel/gui/widgets/settings_panel.py`.
  - Verify: Settings persist to disk (JSON config file).

- [ ] **D5** — PreviewPlayer: `QMediaPlayer` + `QVideoWidget` for playing generated .mp4.
  - Files: `src/snapreel/gui/widgets/preview_player.py`.
  - Verify: Plays a test .mp4 file.

- [ ] **D6** — LogViewer: `QPlainTextEdit` with real-time log streaming from structlog.
  - Files: `src/snapreel/gui/widgets/log_viewer.py`.
  - Verify: Logs appear in real-time during pipeline execution.

## Phase E: Integration & Wiring

- [ ] **E1** — Wire GUI → Orchestrator: ProjectWizard emits config → Orchestrator runs pipeline → ProgressDashboard updates.
  - Files: `src/snapreel/gui/main_window.py` (update), `src/snapreel/app.py` (update).
  - Verify: Full pipeline runs from GUI click to generated .mp4.

- [ ] **E2** — Model setup wizard: first-launch detection, model download UI with progress bars, verification.
  - Files: `src/snapreel/gui/widgets/model_setup_wizard.py`, update `app.py`.
  - Verify: First-launch flow works end-to-end.

## Phase F: Polish & Distribution

- [ ] **F1** — i18n: Extract strings, create RU/EN translation files, integrate Qt Linguist.
  - Files: `src/snapreel/i18n/`, translation `.ts` files.
  - Verify: UI switches between RU and EN.

- [ ] **F2** — Assets: bundle default SFX files, placeholder music, app icon.
  - Files: `assets/icons/`, `assets/sfx/`, `assets/fonts/`.
  - Verify: All assets load correctly.

- [ ] **F3** — Build script: PyInstaller spec file for development builds.
  - Files: `scripts/build.py`, `snapreel.spec`.
  - Verify: `pyinstaller snapreel.spec` produces working .exe.

- [ ] **F4** — Integration tests: full pipeline E2E test with tiny mock models.
  - Files: `tests/integration/test_pipeline_e2e.py`.
  - Verify: `pytest tests/integration/ -m "not slow"` passes.

- [ ] **F5** — README.md with installation instructions, screenshots, usage guide.
  - Files: `README.md`.
  - Verify: Markdown renders correctly.
