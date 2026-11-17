"""Voice page: text in, speech out; results as waveforms with playback and export."""

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
    QVBoxLayout,
    QWidget,
)

from tvorka.core.catalog import ModelSpec
from tvorka.core.jobs import Job
from tvorka.engines.media import AUDIO_FORMATS
from tvorka.gui import icons
from tvorka.gui.pages.base import Page
from tvorka.gui.pages.gallery import show_in_folder
from tvorka.gui.services import Services
from tvorka.gui.widgets.basic import Card, Field, Segmented, SliderField, label, tool_button
from tvorka.gui.widgets.feedback import ToastHost
from tvorka.gui.widgets.fit import FitBanner
from tvorka.gui.widgets.model_card import size_text
from tvorka.gui.widgets.waveform import WaveformView
from tvorka.i18n import language, messages, tr

CHARS_PER_SECOND = 14.0  # typical narration pace, Russian and English alike
RECENT = 30


class AudioRow(QFrame):
    """One finished voice-over: play / pause, waveform, text excerpt and export."""

    def __init__(self, page: SpeechPage, result: dict[str, Any]) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.page = page
        self.path = result["path"]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.play = tool_button("play", tr("Play"), role="")
        self.play.clicked.connect(lambda: page.toggle_play(self))
        self.wave = WaveformView()
        self.wave.load(self.path)
        self.wave.seek.connect(lambda f: page.seek(self, f))
        top.addWidget(self.play)
        top.addWidget(self.wave, 1)
        layout.addLayout(top)
        text = result.get("prompt", "")
        excerpt = label(text if len(text) < 140 else text[:137] + "…", "", wrap=True)
        layout.addWidget(excerpt)
        bottom = QHBoxLayout()
        params = result.get("params", {})
        meta = [result.get("model_name", "")]
        if params.get("voice"):
            meta.append(page.voice_name(result.get("model_id", ""), str(params["voice"])))
        if params.get("duration"):
            meta.append(tr("{seconds} s", seconds=params["duration"]))
        bottom.addWidget(label("  ·  ".join(m for m in meta if m), "faint"), 1)
        save = tool_button("download", tr("Save as…"))
        save.clicked.connect(self._save_as)
        folder = tool_button("folder", tr("Show in folder"))
        folder.clicked.connect(lambda: show_in_folder(self.path))
        bottom.addWidget(save)
        bottom.addWidget(folder)
        layout.addLayout(bottom)

    def set_playing(self, playing: bool) -> None:
        self.play.setIcon(icons.icon("pause" if playing else "play"))
        self.play.setToolTip(tr("Pause") if playing else tr("Play"))

    def _save_as(self) -> None:
        target, _ = QFileDialog.getSaveFileName(self, tr("Save as"), Path(self.path).name)
        if target:
            shutil.copyfile(self.path, target)


class SpeechPage(Page):
    key = "speech"
    icon = "voice"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._spec: ModelSpec | None = None
        self._jobs: set[int] = set()
        self._previews: set[int] = set()
        self._player: Any = None
        self._playing: AudioRow | None = None
        self._rows: list[AudioRow] = []

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_controls())
        layout.addWidget(self._build_results(), 1)

        worker = services.worker
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
        self._load_history()

    def title(self) -> str:
        return tr("Voice")

    # ============================================================ layout
    def _build_controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(24, 22, 16, 18)
        column.setSpacing(14)
        column.addWidget(label(tr("Voice"), "title"))
        column.addWidget(label(tr("Type or paste text — a local model reads it aloud."), "subtitle",
                               wrap=True))
        self.text = QPlainTextEdit()
        self.text.setObjectName("PromptEdit")
        self.text.setPlaceholderText(tr("Hello! This is how your text will sound. Numbers like 2026 are read "
                                        "as words."))
        self.text.setMinimumHeight(200)
        self.text.setAccessibleName(tr("Text"))
        self.text.textChanged.connect(self._text_changed)
        column.addWidget(self.text)
        self.counter = label("", "faint")
        column.addWidget(self.counter)

        model_card = Card(tr("Model"))
        self.model_box = QComboBox()
        self.model_box.setAccessibleName(tr("Model"))
        self.model_box.currentIndexChanged.connect(self._model_selected)
        self.model_summary = label("", "muted", wrap=True)
        self.online_note = label(tr("This voice works over the internet: your text is sent to Microsoft."),
                                 "warn", wrap=True)
        self.fit_banner = FitBanner()
        for widget in (self.model_box, self.model_summary, self.online_note, self.fit_banner):
            model_card.body.addWidget(widget)
        column.addWidget(model_card)

        voice_card = Card(tr("Voice and sound"))
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.voice = QComboBox()
        self.voice.setAccessibleName(tr("Speaker"))
        self.sample = QPushButton(tr("Listen"))
        self.sample.setIcon(icons.icon("play"))
        self.sample.setToolTip(tr("Hear a short sample of this voice"))
        self.sample.clicked.connect(self._play_sample)
        row.addWidget(self.voice, 1)
        row.addWidget(self.sample)
        voice_holder = QWidget()
        voice_holder.setLayout(row)
        self.voice_field = Field(tr("Speaker"), voice_holder)
        self.speed = SliderField(0.5, 2.0, 0.05, 2, "×")
        self.speed.changed.connect(self._speed_changed)
        self.file_format = Segmented([(f, f.upper()) for f in AUDIO_FORMATS])
        voice_card.body.addWidget(self.voice_field)
        voice_card.body.addWidget(Field(tr("Speed"), self.speed))
        voice_card.body.addWidget(Field(tr("File"), self.file_format))
        column.addWidget(voice_card)
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
        self.action.setToolTip(tr("Read aloud (Ctrl+Enter)"))
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
        layout.setContentsMargins(4, 22, 22, 18)
        layout.setSpacing(12)
        head = QHBoxLayout()
        head.addWidget(label(tr("Your voice-overs"), "heading"), 1)
        self.status = label("", "muted")
        head.addWidget(self.status)
        layout.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(10)
        self.list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.empty = label(tr("Your voice-overs will appear here. Write a few sentences on the left and "
                              "press “Read aloud”."), "faint", wrap=True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.list.addWidget(self.empty)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)
        return panel

    # ============================================================ models and voices
    def _fill_models(self) -> None:
        current = self._spec.id if self._spec else self.services.settings.recall("speech", "model")
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for spec in self.services.catalog.all("speech"):
            name = spec.name
            if not self.services.installed(spec):
                name += "  ·  " + size_text(spec.download_gb)
            self.model_box.addItem(name, spec.id)
        self.model_box.setCurrentIndex(max(0, self.model_box.findData(current)))
        self.model_box.blockSignals(False)
        self._model_selected(self.model_box.currentIndex())

    def voice_name(self, model_id: str, voice_id: str) -> str:
        spec = self.services.catalog.get(model_id)
        voices = {v["id"]: v.get("name", v["id"]) for v in (spec.voices if spec else [])}
        return voices.get(voice_id, voice_id)

    def select_model(self, model_id: str) -> None:
        index = self.model_box.findData(model_id)
        if index >= 0:
            self.model_box.setCurrentIndex(index)

    def _model_selected(self, _index: int) -> None:
        spec = self.services.catalog.get(self.model_box.currentData() or "")
        if spec is None:
            return
        self._spec = spec
        self.model_summary.setText(spec.text(language()))
        self.online_note.setVisible(spec.source == "online")
        remembered = self.services.settings.recall("speech", "voice")
        self.voice.clear()
        for voice in spec.voices:
            self.voice.addItem(voice.get("name", voice["id"]), voice["id"])
        if not spec.voices:
            self.voice.addItem(tr("Default voice"), "")
        self.voice.setCurrentIndex(max(0, self.voice.findData(remembered)))
        self.voice.setEnabled(bool(spec.voices))
        self._on_hardware(None)

    def _on_hardware(self, _hw: object) -> None:
        if self._spec is not None:
            self.fit_banner.set_fit(self.services.fit(self._spec))
        self._update_action()

    # ============================================================ state
    def _text_changed(self) -> None:
        text = self.text.toPlainText().strip()
        seconds = len(text) / CHARS_PER_SECOND / max(0.5, self.speed.value() or 1.0)
        self.counter.setText(tr("{chars} characters · about {seconds:.0f} s of speech", chars=len(text),
                                seconds=seconds) if text else "")
        self.counter.setVisible(bool(text))
        self._update_action()

    def _speed_changed(self, _value: float) -> None:
        self._text_changed()

    def _update_action(self) -> None:
        spec = self._spec
        self.stop.setVisible(bool(self._jobs))
        if spec is None:
            self.action.setEnabled(False)
            return
        installed = self.services.installed(spec)
        self.sample.setEnabled(installed)
        if self.services.downloads.is_active(spec.id):
            state = self.services.downloads.state(spec.id)
            percent = f" {round(state[0] / state[1] * 100)} %" if state and state[1] else ""
            self.action.setText(tr("Downloading") + percent)
            self.action.setEnabled(False)
            self.stop.setVisible(True)
            return
        if not installed:
            self.action.setText(tr("Download ({size})", size=size_text(spec.download_gb)))
            self.action.setEnabled(True)
            return
        fit = self.services.fit(spec)
        self.action.setText(tr("Add to queue") if self._jobs else tr("Read aloud"))
        self.action.setEnabled(bool(self.text.toPlainText().strip()) and (fit is None or fit.ok))

    # ============================================================ actions
    def _action_clicked(self) -> None:
        if self._spec is None:
            return
        if not self.services.installed(self._spec):
            self.services.downloads.start(self._spec)
            self._update_action()
            return
        self.generate()

    def _job(self, text: str, preview: bool = False) -> Job:
        assert self._spec is not None
        return Job("speech", self._spec.id, text, {
            "voice": self.voice.currentData() or None, "speed": self.speed.value(),
            "format": "wav" if preview else self.file_format.value(), "preview": preview,
        })

    def generate(self) -> None:
        if self._spec is None or not self.action.isEnabled() or not self.services.installed(self._spec):
            return
        job = self._job(self.text.toPlainText().strip())
        self._jobs.add(job.id)
        self._remember()
        self.services.worker.submit(job)
        self.status.setText(tr("Waiting in the queue…"))
        self._update_action()

    def _play_sample(self) -> None:
        if self._spec is None or not self.services.installed(self._spec):
            return
        sample = (tr("Hello! This is how this voice sounds.") if self._spec.languages != ["en"]
                  else "Hello! This is how this voice sounds.")
        job = self._job(sample, preview=True)
        self._previews.add(job.id)
        self.sample.setEnabled(False)
        self.services.worker.submit(job)

    def cancel(self) -> None:
        if self._spec is not None and self.services.downloads.is_active(self._spec.id):
            self.services.downloads.cancel(self._spec.id)
        for job_id in list(self._jobs):
            self.services.worker.cancel(job_id)

    # ============================================================ worker events
    def _on_progress(self, job_id: int, fraction: float, stage: str) -> None:
        if job_id in self._jobs:
            self.status.setText(f"{messages.stage(stage)}  {round(fraction * 100)} %")

    def _on_finished(self, job_id: int, results: list) -> None:
        if job_id in self._previews:
            self._previews.discard(job_id)
            self.sample.setEnabled(True)
            if results:
                self._play_file(results[0]["path"])
            return
        if job_id not in self._jobs:
            return
        self._jobs.discard(job_id)
        for result in results:
            row = self._add_row(result, top=True)
            self.toggle_play(row)
        self._done()

    def _on_failed(self, job_id: int, code: str, detail: str) -> None:
        if job_id in self._previews:
            self._previews.discard(job_id)
            self.sample.setEnabled(True)
        elif job_id in self._jobs:
            self._jobs.discard(job_id)
            self._done()
        else:
            return
        if self.toasts is not None:
            self.toasts.show(messages.engine_error(code, detail), "bad")

    def _on_cancelled(self, job_id: int) -> None:
        self._previews.discard(job_id)
        if job_id in self._jobs:
            self._jobs.discard(job_id)
            self._done()

    def _done(self) -> None:
        if not self._jobs:
            self.status.setText("")
        self._update_action()

    def _on_download(self, model_id: str, *_args: object) -> None:
        if self._spec is not None and model_id == self._spec.id:
            self._update_action()

    def _on_download_failed(self, model_id: str, code: str, _message: str) -> None:
        self._on_download(model_id)
        if self._spec is not None and model_id == self._spec.id and self.toasts is not None:
            self.toasts.show(messages.hub_error(code), "bad")

    # ============================================================ results and playback
    def _load_history(self) -> None:
        from dataclasses import asdict

        for result in self.services.history.items("speech")[:RECENT]:
            self._add_row(asdict(result))

    def _add_row(self, result: dict[str, Any], top: bool = False) -> AudioRow:
        self.empty.setVisible(False)
        row = AudioRow(self, result)
        self._rows.insert(0 if top else len(self._rows), row)
        self.list.insertWidget(1 if top else self.list.count(), row)  # index 0 is the empty label
        return row

    def _ensure_player(self) -> Any:
        if self._player is None:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._player = QMediaPlayer(self)
            self._audio = QAudioOutput(self)
            self._player.setAudioOutput(self._audio)
            self._player.positionChanged.connect(self._on_position)
            self._player.playbackStateChanged.connect(self._on_state)
        return self._player

    def _play_file(self, path: str) -> None:
        player = self._ensure_player()
        if self._playing is not None:
            self._playing.set_playing(False)
            self._playing = None
        player.setSource(QUrl.fromLocalFile(path))
        player.play()

    def toggle_play(self, row: AudioRow) -> None:
        player = self._ensure_player()
        from PySide6.QtMultimedia import QMediaPlayer

        if self._playing is row and player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
            return
        if self._playing is not row:
            if self._playing is not None:
                self._playing.set_playing(False)
                self._playing.wave.set_position(0)
            self._playing = row
            player.setSource(QUrl.fromLocalFile(row.path))
        player.play()

    def seek(self, row: AudioRow, fraction: float) -> None:
        if self._playing is not row:
            self.toggle_play(row)
        player = self._ensure_player()
        if player.duration() > 0:
            player.setPosition(int(player.duration() * fraction))

    def _on_position(self, position: int) -> None:
        player = self._player
        if self._playing is not None and player is not None and player.duration() > 0:
            self._playing.wave.set_position(position / player.duration())

    def _on_state(self, state: Any) -> None:
        from PySide6.QtMultimedia import QMediaPlayer

        if self._playing is not None:
            self._playing.set_playing(state == QMediaPlayer.PlaybackState.PlayingState)

    # ============================================================ persistence
    def save_state(self) -> None:
        self._remember()

    def _remember(self) -> None:
        self.services.settings.remember("speech", model=self._spec.id if self._spec else "",
                                        voice=self.voice.currentData() or "", speed=self.speed.value(),
                                        format=self.file_format.value(), text=self.text.toPlainText())

    def _restore(self) -> None:
        recall = self.services.settings.recall
        self.text.setPlainText(recall("speech", "text", ""))
        self.speed.set_value(float(recall("speech", "speed", 1.0)))
        self.file_format.set_value(recall("speech", "format", self.services.settings.audio_format))
        self._text_changed()
