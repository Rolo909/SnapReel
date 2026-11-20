"""Video page: prompt, optional first frame, duration in seconds; a looping player for results."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from tvorka.core import advisor
from tvorka.core.catalog import ModelSpec
from tvorka.core.jobs import Job
from tvorka.engines.media import VIDEO_FORMATS
from tvorka.gui import icons
from tvorka.gui.pages.base import Page
from tvorka.gui.pages.gallery import show_in_folder
from tvorka.gui.services import Services
from tvorka.gui.widgets.aspect import AspectPicker
from tvorka.gui.widgets.basic import (
    Card,
    Disclosure,
    Field,
    SeedField,
    Segmented,
    SliderField,
    label,
    tool_button,
)
from tvorka.gui.widgets.canvas import Canvas, FilmStrip
from tvorka.gui.widgets.dropzone import DropZone
from tvorka.gui.widgets.feedback import ToastHost
from tvorka.gui.widgets.fit import FitBanner
from tvorka.gui.widgets.mic import mic_bar
from tvorka.gui.widgets.model_card import size_text
from tvorka.i18n import language, messages, tr


class VideoPage(Page):
    key = "video"
    icon = "video"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._spec: ModelSpec | None = None
        self._jobs: set[int] = set()
        self._player: Any = None
        self._current = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_results(), 1)

        worker = services.worker
        worker.job_started.connect(self._on_started)
        worker.job_progress.connect(self._on_progress)
        worker.job_finished.connect(self._on_finished)
        worker.job_failed.connect(self._on_failed)
        worker.job_cancelled.connect(self._on_cancelled)
        services.hardware_ready.connect(self._on_hardware)
        services.models_changed.connect(self._fill_models)
        services.downloads.progress.connect(self._on_download)
        services.downloads.failed.connect(self._on_download_failed)
        services.downloads.cancelled.connect(self._on_download)
        self._fill_models()
        self._restore()

    def title(self) -> str:
        return tr("Video")

    # ============================================================ layout
    def _build_controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(24, 22, 16, 18)
        column.setSpacing(14)
        column.addWidget(label(tr("Video"), "title"))
        column.addWidget(label(tr("Describe a scene and its motion — or bring it to life from a picture."),
                               "subtitle", wrap=True))
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("PromptEdit")
        self.prompt.setPlaceholderText(tr("A paper boat floating on a calm lake at sunset, gentle ripples, "
                                          "slow camera pan…"))
        self.prompt.setFixedHeight(128)
        self.prompt.setAccessibleName(tr("Prompt"))
        self.prompt.textChanged.connect(self._update_action)
        column.addWidget(self.prompt)
        column.addWidget(mic_bar(self, self.prompt))
        column.addWidget(label(tr("Tip: most models understand English best."), "faint"))

        model_card = Card(tr("Model"))
        self.model_box = QComboBox()
        self.model_box.setAccessibleName(tr("Model"))
        self.model_box.currentIndexChanged.connect(self._model_selected)
        self.model_summary = label("", "muted", wrap=True)
        self.fit_banner = FitBanner()
        for widget in (self.model_box, self.model_summary, self.fit_banner):
            model_card.body.addWidget(widget)
        column.addWidget(model_card)

        self.frame_card = Card(tr("First frame (optional)"))
        self.dropzone = DropZone(tr("Drop a picture to bring it to life, click to choose or press Ctrl+V"))
        self.dropzone.changed.connect(lambda _p: self._refresh_fit())
        self.frame_hint = label("", "warn", wrap=True)
        self.frame_card.body.addWidget(self.dropzone)
        self.frame_card.body.addWidget(self.frame_hint)
        column.addWidget(self.frame_card)

        format_card = Card(tr("Format"))
        self.aspect = AspectPicker()
        self.aspect.changed.connect(lambda *_: self._size_changed())
        self.aspect_field = Field(tr("Proportions"), self.aspect)
        self.scale = Segmented([("1", tr("Native")), ("1.5", "×1.5"), ("2", "×2")])
        self.scale.changed.connect(lambda _v: self._size_changed())
        self.size_info = label("", "mono", wrap=True)
        self.seconds = SliderField(1, 10, 0.5, 1, " " + tr("s"))
        self.seconds.changed.connect(lambda _v: self._size_changed())
        self.frames_info = label("", "faint", wrap=True)
        self.fps = Segmented([("model", tr("As the model")), ("24", "24 fps"), ("30", "30 fps")])
        self.file_format = Segmented([(f, f.upper()) for f in VIDEO_FORMATS])
        format_card.body.addWidget(self.aspect_field)
        format_card.body.addWidget(Field(tr("Size"), self.scale))
        format_card.body.addWidget(self.size_info)
        format_card.body.addWidget(Field(tr("Duration"), self.seconds))
        format_card.body.addWidget(self.frames_info)
        format_card.body.addWidget(Field(tr("Frame rate"), self.fps))
        format_card.body.addWidget(Field(tr("File"), self.file_format))
        column.addWidget(format_card)

        advanced = Disclosure(tr("Advanced"))
        self.negative = QPlainTextEdit()
        self.negative.setPlaceholderText(tr("What to avoid (optional)"))
        self.negative.setFixedHeight(56)
        self.negative_field = Field(tr("Negative prompt"), self.negative)
        self.steps = SliderField(1, 80)
        self.guidance = SliderField(0, 15, 0.5, 1)
        self.seed = SeedField()
        advanced.body.addWidget(self.negative_field)
        advanced.body.addWidget(Field(tr("Steps"), self.steps, tr("More steps — more detail, but slower.")))
        advanced.body.addWidget(Field(tr("Prompt strength"), self.guidance,
                                      tr("How strictly the model follows the prompt.")))
        advanced.body.addWidget(Field(tr("Seed"), self.seed))
        column.addWidget(advanced)
        column.addStretch(1)
        scroll.setWidget(inner)

        holder = QWidget()
        holder.setFixedWidth(440)
        outer = QVBoxLayout(holder)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 12, 16, 18)
        bar_layout.setSpacing(8)
        self.action = QPushButton()
        self.action.setProperty("role", "primary")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.setToolTip(tr("Create (Ctrl+Enter)"))
        self.action.clicked.connect(self._action_clicked)
        self.stop = tool_button("stop", tr("Cancel (Esc)"), role="")
        self.stop.setVisible(False)
        self.stop.clicked.connect(self.cancel)
        bar_layout.addWidget(self.action, 1)
        bar_layout.addWidget(self.stop)
        outer.addWidget(bar)
        return holder

    def _build_results(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 18, 22, 18)
        layout.setSpacing(12)
        stage = QFrame()
        stage.setObjectName("Stage")
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(1, 1, 1, 1)
        self.view = QStackedWidget()
        self.canvas = Canvas()
        self.canvas.set_empty_text(tr("Your video will play here. Describe a scene on the left and press "
                                      "“Create”."))
        self.view.addWidget(self.canvas)
        self.video_holder = QWidget()
        self.view.addWidget(self.video_holder)
        stage_layout.addWidget(self.view)
        layout.addWidget(stage, 1)

        controls = QHBoxLayout()
        controls.setSpacing(4)
        self.play = tool_button("pause", tr("Pause"))
        self.play.clicked.connect(self._toggle_play)
        self.back = tool_button("chevron", tr("Previous frame"))
        self.back.setIcon(self._rotated(90))
        self.back.clicked.connect(lambda: self._step(-1))
        self.forward = tool_button("chevron", tr("Next frame"))
        self.forward.setIcon(self._rotated(-90))
        self.forward.clicked.connect(lambda: self._step(1))
        self.position = QSlider(Qt.Orientation.Horizontal)
        self.position.sliderMoved.connect(self._seek)
        self.save = tool_button("download", tr("Save as…"))
        self.save.clicked.connect(self._save_as)
        self.folder = tool_button("folder", tr("Show in folder"))
        self.folder.clicked.connect(lambda: self._current and show_in_folder(self._current))
        for widget in (self.play, self.back, self.forward):
            controls.addWidget(widget)
        controls.addWidget(self.position, 1)
        self.info = label("", "mono")
        controls.addWidget(self.info)
        controls.addWidget(self.save)
        controls.addWidget(self.folder)
        self.controls = QWidget()
        self.controls.setLayout(controls)
        self.controls.setEnabled(False)
        layout.addWidget(self.controls)
        self.strip = FilmStrip()
        self.strip.picked.connect(self._show_video)
        layout.addWidget(self.strip)
        return panel

    @staticmethod
    def _rotated(angle: float) -> Any:
        from PySide6.QtGui import QIcon

        return QIcon(icons.pixmap("chevron", 18, "muted", rotate=angle))

    # ============================================================ models
    def _fill_models(self) -> None:
        current = self._spec.id if self._spec else self.services.settings.recall("video", "model")
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for spec in self.services.catalog.all("video"):
            name = spec.name
            if not self.services.installed(spec):
                name += "  ·  " + size_text(spec.download_gb)
            self.model_box.addItem(name, spec.id)
        self.model_box.setCurrentIndex(max(0, self.model_box.findData(current)))
        self.model_box.blockSignals(False)
        self._model_selected(self.model_box.currentIndex())

    def select_model(self, model_id: str) -> None:
        index = self.model_box.findData(model_id)
        if index >= 0:
            self.model_box.setCurrentIndex(index)

    def set_first_frame(self, path: str) -> None:
        """Image page: "Send to Video as the first frame"."""
        self.dropzone.set_path(path)

    def _model_selected(self, _index: int) -> None:
        spec = self.services.catalog.get(self.model_box.currentData() or "")
        if spec is None:
            return
        changed = self._spec is None or self._spec.id != spec.id
        self._spec = spec
        self.model_summary.setText(spec.text(language()))
        takes_frame = bool(spec.reference) or spec.requires_reference
        self.frame_card.setVisible(takes_frame)
        self.frame_hint.setText(tr("This model needs a first frame: it animates a picture.")
                                if spec.requires_reference else "")
        self.frame_hint.setVisible(spec.requires_reference)
        self.aspect_field.setVisible(not spec.fixed_size)
        self.negative_field.setVisible(bool(spec.default("negative", True)))
        fps = int(spec.default("fps", 16))
        # n frames span (n - 1) / fps seconds of motion: 49 frames at 8 fps = 6 s.
        longest = (int(spec.default("max_frames", 49)) - 1) / fps
        self.seconds.set_range(max(0.5, 1 / fps * (spec.frame_rule + 1)), round(longest, 1))
        if changed:
            self.steps.set_value(int(spec.default("steps", 30)))
            self.guidance.set_value(float(spec.default("guidance", 5.0)))
            self.seconds.set_value(round((int(spec.default("frames", 49)) - 1) / fps, 1))
        self._size_changed()

    # ============================================================ derived state
    def _target(self) -> tuple[int, int]:
        assert self._spec is not None
        w, h = advisor.size_for_aspect(self._spec, *self.aspect.value())
        factor = float(self.scale.value() or 1)
        return round(w * factor / 2) * 2, round(h * factor / 2) * 2

    def _size_changed(self) -> None:
        spec = self._spec
        if spec is None:
            return
        width, height = self._target()
        gen_w, gen_h, _route = advisor.resolution_route(spec, width, height)
        frames, capped = advisor.video_frames(spec, seconds=self.seconds.value())
        fps = int(spec.default("fps", 16))
        if (gen_w, gen_h) != (width, height):
            self.size_info.setText(tr("{w} × {h} px — the model films {gw} × {gh}, then frames are enlarged",
                                      w=width, h=height, gw=gen_w, gh=gen_h))
        else:
            self.size_info.setText(tr("{w} × {h} px", w=width, h=height))
        text = tr("{frames} frames at {fps} fps · {seconds:.1f} s", frames=frames, fps=fps,
                  seconds=frames / fps)
        if capped:
            text += " · " + tr("this is the model's limit")
        self.frames_info.setText(text)
        self._refresh_fit()

    def _refresh_fit(self) -> None:
        if self._spec is None:
            return
        width, height = self._target()
        gen_w, gen_h, _ = advisor.resolution_route(self._spec, width, height)
        frames, _ = advisor.video_frames(self._spec, seconds=self.seconds.value())
        self.fit_banner.set_fit(self.services.fit(self._spec, advisor.work_scale(self._spec, gen_w, gen_h,
                                                                                  frames)))
        self._update_action()

    def _on_hardware(self, _hw: object) -> None:
        self._refresh_fit()

    def _update_action(self) -> None:
        spec = self._spec
        self.stop.setVisible(bool(self._jobs))
        if spec is None:
            self.action.setEnabled(False)
            return
        if self.services.downloads.is_active(spec.id):
            state = self.services.downloads.state(spec.id)
            percent = f" {round(state[0] / state[1] * 100)} %" if state and state[1] else ""
            self.action.setText(tr("Downloading") + percent)
            self.action.setEnabled(False)
            self.stop.setVisible(True)
            return
        if not self.services.installed(spec):
            self.action.setText(tr("Download ({size})", size=size_text(spec.download_gb)))
            fit = self.services.fit(spec)
            self.action.setEnabled(fit is None or fit.ok)
            return
        fit = self.services.fit(spec)
        ready = bool(self.prompt.toPlainText().strip()) and (fit is None or fit.ok)
        if spec.requires_reference and not self.dropzone.path():
            ready = False
        self.action.setText(tr("Add to queue") if self._jobs else tr("Create"))
        self.action.setEnabled(ready)

    # ============================================================ actions
    def _action_clicked(self) -> None:
        if self._spec is None:
            return
        if not self.services.installed(self._spec):
            self.services.downloads.start(self._spec)
            self._update_action()
            return
        self.generate()

    def generate(self) -> None:
        spec = self._spec
        if spec is None or not self.action.isEnabled() or not self.services.installed(spec):
            return
        width, height = self._target()
        fps = self.fps.value()
        params: dict[str, Any] = {
            "width": width, "height": height, "seconds": self.seconds.value(),
            "steps": int(self.steps.value()), "guidance": self.guidance.value(), "seed": self.seed.value(),
            "format": self.file_format.value(),
        }
        if fps != "model":
            params["fps"] = int(fps)
        if not self.negative_field.isHidden():
            params["negative"] = self.negative.toPlainText().strip()
        if self.dropzone.path() and not self.frame_card.isHidden():
            params["reference"] = self.dropzone.path()
        job = Job("video", spec.id, self.prompt.toPlainText().strip(), params)
        self._jobs.add(job.id)
        self._remember()
        self._pause()
        self.view.setCurrentIndex(0)
        self.canvas.set_progress(0.0, tr("Waiting in the queue…"))
        self.services.worker.submit(job)
        self._update_action()

    def cancel(self) -> None:
        if self._spec is not None and self.services.downloads.is_active(self._spec.id):
            self.services.downloads.cancel(self._spec.id)
        for job_id in list(self._jobs):
            self.services.worker.cancel(job_id)

    # ============================================================ worker events
    def _on_started(self, job_id: int) -> None:
        if job_id in self._jobs:
            self.canvas.set_progress(0.0, messages.stage("import"))

    def _on_progress(self, job_id: int, fraction: float, stage: str) -> None:
        if job_id in self._jobs:
            self.canvas.set_progress(fraction, messages.stage(stage))

    def _on_finished(self, job_id: int, results: list) -> None:
        if job_id not in self._jobs:
            return
        self._jobs.discard(job_id)
        for result in results:
            self.strip.add(result["path"], result.get("thumb") or None)
            self.seed.remember(int(result["params"].get("seed", 0)))
        if results:
            self._show_video(results[-1]["path"])
        self._done()

    def _on_failed(self, job_id: int, code: str, detail: str) -> None:
        if job_id not in self._jobs:
            return
        self._jobs.discard(job_id)
        self._done()
        if self.toasts is not None:
            self.toasts.show(messages.engine_error(code, detail), "bad")

    def _on_cancelled(self, job_id: int) -> None:
        if job_id in self._jobs:
            self._jobs.discard(job_id)
            self._done()

    def _done(self) -> None:
        if not self._jobs:
            self.canvas.set_progress(None)
            if self._current:
                self.view.setCurrentIndex(1)
        self._update_action()

    def _on_download(self, model_id: str, *_args: object) -> None:
        if self._spec is not None and model_id == self._spec.id:
            self._update_action()

    def _on_download_failed(self, model_id: str, code: str, _message: str) -> None:
        self._on_download(model_id)
        if self._spec is not None and model_id == self._spec.id and self.toasts is not None:
            self.toasts.show(messages.hub_error(code), "bad")

    # ============================================================ player
    def _ensure_player(self) -> Any:
        if self._player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            video = QVideoWidget()
            box = QVBoxLayout(self.video_holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.addWidget(video)
            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.setVideoOutput(video)
            self._player.setLoops(QMediaPlayer.Loops.Infinite)
            self._player.durationChanged.connect(lambda d: self.position.setRange(0, d))
            self._player.positionChanged.connect(self._on_position)
            self._player.playbackStateChanged.connect(self._on_state)
        return self._player

    def _show_video(self, path: str) -> None:
        self._current = path
        player = self._ensure_player()
        player.setSource(QUrl.fromLocalFile(path))
        self.view.setCurrentIndex(1)
        self.controls.setEnabled(True)
        self.info.setText(Path(path).name)
        player.play()

    def _toggle_play(self) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        player = self._ensure_player()
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
        else:
            player.play()

    def _pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def _step(self, frames: int) -> None:
        player = self._ensure_player()
        player.pause()
        fps = int(self.fps.value()) if self.fps.value().isdigit() else int(
            self._spec.default("fps", 16) if self._spec else 16)
        player.setPosition(max(0, player.position() + round(frames * 1000 / fps)))

    def _seek(self, position: int) -> None:
        if self._player is not None:
            self._player.setPosition(position)

    def _on_position(self, position: int) -> None:
        if not self.position.isSliderDown():
            self.position.setValue(position)

    def _on_state(self, state: Any) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setIcon(icons.icon("pause" if playing else "play"))
        self.play.setToolTip(tr("Pause") if playing else tr("Play"))

    def _save_as(self) -> None:
        if not self._current:
            return
        target, _ = QFileDialog.getSaveFileName(self, tr("Save as"), Path(self._current).name)
        if target:
            shutil.copyfile(self._current, target)

    # ============================================================ persistence
    def save_state(self) -> None:
        self._remember()

    def _remember(self) -> None:
        self.services.settings.remember(
            "video", model=self._spec.id if self._spec else "", prompt=self.prompt.toPlainText(),
            aspect=list(self.aspect.value()), scale=self.scale.value(), seconds=self.seconds.value(),
            fps=self.fps.value(), format=self.file_format.value())

    def _restore(self) -> None:
        recall = self.services.settings.recall
        self.prompt.setPlainText(recall("video", "prompt", ""))
        aspect = recall("video", "aspect")
        if aspect:
            self.aspect.set_value(*aspect)
        self.scale.set_value(recall("video", "scale", "1"))
        self.fps.set_value(recall("video", "fps", "model"))
        self.file_format.set_value(recall("video", "format", self.services.settings.video_format))
        if recall("video", "seconds"):
            self.seconds.set_value(float(recall("video", "seconds")))
        self._size_changed()
