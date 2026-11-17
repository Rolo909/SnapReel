"""Image page: prompt, optional reference, any output size; results on a light table."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QImage
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from tvorka.core import advisor
from tvorka.core.catalog import ModelSpec
from tvorka.core.jobs import Job
from tvorka.engines.media import IMAGE_FORMATS
from tvorka.gui.pages.base import Page
from tvorka.gui.services import Services
from tvorka.gui.widgets.aspect import AspectPicker, SizeField
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
from tvorka.i18n import messages, tr

GB = 1024**3


def reference_label(mode: str) -> str:
    if mode == "img2img":
        return tr("Structure")
    if mode.startswith("ip_adapter"):
        return tr("Style")
    if mode == "native":
        return tr("Edit")
    return mode


def reference_hint(mode: str) -> str:
    if mode == "img2img":
        return tr("Keeps the composition of the reference; strength sets how much is redrawn.")
    if mode.startswith("ip_adapter"):
        return tr("Borrows the look of the reference; strength sets how closely it is followed.")
    return tr("The model edits the reference according to the prompt.")


class ImagePage(Page):
    key = "image"
    icon = "image"

    def __init__(self, services: Services, toasts: ToastHost | None) -> None:
        super().__init__(services, toasts)
        self._spec: ModelSpec | None = None
        self._jobs: set[int] = set()
        self._last_result: dict[str, Any] | None = None

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
        # Bound methods only: the window can be rebuilt (language / theme change) while these
        # long-lived services stay, and Qt drops bound-method connections of deleted pages.
        services.hardware_ready.connect(self._on_hardware)
        services.models_changed.connect(self._fill_models)
        services.downloads.progress.connect(self._on_download_progress)
        services.downloads.failed.connect(self._on_download_failed)
        services.downloads.cancelled.connect(self._on_download_cancelled)

        self._fill_models()
        self._restore()

    def title(self) -> str:
        return tr("Image")

    # =================================================================== layout
    def _build_controls(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        column = QVBoxLayout(inner)
        column.setContentsMargins(24, 22, 16, 18)
        column.setSpacing(14)
        column.addWidget(label(tr("Image"), "title"))
        column.addWidget(label(tr("Describe an idea — the model draws it right on your computer."),
                               "subtitle", wrap=True))

        # prompt — the main control, first and largest
        self.prompt = QPlainTextEdit()
        self.prompt.setObjectName("PromptEdit")
        self.prompt.setPlaceholderText(tr("A lighthouse on a cliff at dusk, warm light, film photo…"))
        self.prompt.setFixedHeight(128)
        self.prompt.setAccessibleName(tr("Prompt"))
        self.prompt.textChanged.connect(self._update_action)
        column.addWidget(self.prompt)
        column.addWidget(label(tr("Tip: most models understand English best."), "faint"))

        # model
        model_card = Card(tr("Model"))
        self.model_box = QComboBox()
        self.model_box.setAccessibleName(tr("Model"))
        self.model_box.currentIndexChanged.connect(self._model_selected)
        self.model_summary = label("", "muted", wrap=True)
        self.fit_banner = FitBanner()
        model_card.body.addWidget(self.model_box)
        model_card.body.addWidget(self.model_summary)
        model_card.body.addWidget(self.fit_banner)
        column.addWidget(model_card)

        # reference
        self.reference_card = Card(tr("Reference (optional)"))
        self.dropzone = DropZone()
        self.dropzone.changed.connect(lambda _p: self._reference_changed())
        self.reference_mode = Segmented([])
        self.reference_mode.changed.connect(lambda _m: self._reference_changed())
        self.reference_hint = label("", "faint", wrap=True)
        self.strength = SliderField(0.05, 1.0, 0.05, 2)
        self.reference_options = QWidget()
        options = QVBoxLayout(self.reference_options)
        options.setContentsMargins(0, 0, 0, 0)
        options.setSpacing(8)
        options.addWidget(self.reference_mode)
        options.addWidget(self.reference_hint)
        options.addWidget(Field(tr("Strength"), self.strength))
        self.reference_card.body.addWidget(self.dropzone)
        self.reference_card.body.addWidget(self.reference_options)
        column.addWidget(self.reference_card)

        # format
        format_card = Card(tr("Format"))
        self.size_mode = Segmented([("aspect", tr("Proportions")), ("exact", tr("Exact size"))])
        self.size_mode.changed.connect(self._size_mode_changed)
        aspect_panel = QWidget()
        aspect_layout = QVBoxLayout(aspect_panel)
        aspect_layout.setContentsMargins(0, 0, 0, 0)
        aspect_layout.setSpacing(8)
        self.aspect = AspectPicker()
        self.aspect.changed.connect(lambda *_: self._size_changed())
        self.scale = Segmented([("1", tr("Native")), ("2", "×2"), ("4", "×4")])
        self.scale.changed.connect(lambda _v: self._size_changed())
        aspect_layout.addWidget(self.aspect)
        aspect_layout.addWidget(Field(tr("Size"), self.scale))
        self.exact = SizeField()
        self.exact.changed.connect(lambda *_: self._size_changed())
        self.aspect_panel = aspect_panel
        self.size_info = label("", "mono", wrap=True)
        self.upscale_mode = Segmented([("quality", tr("Quality (Real-ESRGAN)")), ("fast", tr("Fast"))])
        self.upscale_field = Field(tr("Enlarging"), self.upscale_mode)
        self.file_format = Segmented([(f, f.upper()) for f in IMAGE_FORMATS])
        format_card.body.addWidget(self.size_mode)
        format_card.body.addWidget(self.aspect_panel)
        format_card.body.addWidget(self.exact)
        format_card.body.addWidget(self.size_info)
        format_card.body.addWidget(self.upscale_field)
        format_card.body.addWidget(Field(tr("File"), self.file_format))
        column.addWidget(format_card)

        # rarely changed settings fold away
        advanced = Disclosure(tr("Advanced"))
        self.steps = SliderField(1, 60)
        self.guidance = SliderField(0, 15, 0.5, 1)
        self.seed = SeedField()
        self.negative = QPlainTextEdit()
        self.negative.setPlaceholderText(tr("What to avoid (optional)"))
        self.negative.setFixedHeight(56)
        self.negative_field = Field(tr("Negative prompt"), self.negative)
        self.steps_field = Field(tr("Steps"), self.steps, tr("More steps — more detail, but slower."))
        self.guidance_field = Field(tr("Prompt strength"), self.guidance,
                                    tr("How strictly the model follows the prompt."))
        advanced.body.addWidget(self.negative_field)
        advanced.body.addWidget(self.steps_field)
        advanced.body.addWidget(self.guidance_field)
        advanced.body.addWidget(Field(tr("Seed"), self.seed,
                                      tr("The same seed and settings repeat a picture.")))
        column.addWidget(advanced)
        column.addStretch(1)
        scroll.setWidget(inner)

        # the action bar stays visible below the scrolling column
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
        self.count = QSpinBox()
        self.count.setRange(1, 8)
        self.count.setPrefix("× ")
        self.count.setFixedWidth(64)
        self.count.setAccessibleName(tr("Number of images"))
        self.count.setToolTip(tr("How many images to create"))
        self.action = QPushButton()
        self.action.setProperty("role", "primary")
        self.action.setCursor(Qt.CursorShape.PointingHandCursor)
        self.action.setToolTip(tr("Create (Ctrl+Enter)"))
        self.action.clicked.connect(self._action_clicked)
        self.stop = tool_button("stop", tr("Cancel (Esc)"), role="")
        self.stop.setVisible(False)
        self.stop.clicked.connect(self.cancel)
        bar_layout.addWidget(self.count)
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
        grid = QGridLayout(stage)
        grid.setContentsMargins(1, 1, 1, 1)
        self.canvas = Canvas()
        self.canvas.set_empty_text("")  # the ideas panel invites to start instead
        grid.addWidget(self.canvas, 0, 0)
        grid.addWidget(self._build_ideas(), 0, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(stage, 1)
        actions = QHBoxLayout()
        actions.setSpacing(2)
        self.result_actions = []
        for icon, tip, handler in (
            ("download", tr("Save as…"), self._save_as),
            ("folder", tr("Show in folder"), self._open_folder),
            ("copy", tr("Copy to clipboard"), self._copy),
            ("image", tr("Use as reference"), self._use_as_reference),
            ("refresh", tr("Repeat with this seed"), self._repeat_seed),
            ("video", tr("Send to Video as the first frame"), self._to_video),
        ):
            button = tool_button(icon, tip)
            button.clicked.connect(handler)
            button.setEnabled(False)
            actions.addWidget(button)
            self.result_actions.append(button)
        actions.addStretch(1)
        self.result_info = label("", "mono")
        actions.addWidget(self.result_info)
        layout.addLayout(actions)
        self.strip = FilmStrip()
        self.strip.picked.connect(self._show_result_path)
        layout.addWidget(self.strip)
        return panel

    def _build_ideas(self) -> QWidget:
        """Empty-stage invitation: clickable example prompts to start from."""
        self.ideas = QWidget()
        self.ideas.setMaximumWidth(400)
        box = QVBoxLayout(self.ideas)
        box.setSpacing(10)
        heading = label(tr("What shall we create?"), "title")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(heading)
        hint = label(tr("Pick an idea to start from, or write your own on the left."), "subtitle", wrap=True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(hint)
        box.addSpacing(6)
        # The label is translated; the prompt stays English — most models understand it best.
        for title, prompt in (
            (tr("Cozy reading nook by a rainy window"),
             "A cozy reading nook by a rainy window, warm lamp light, photo"),
            (tr("Tiny island with a lighthouse, 3D"),
             "Isometric tiny island with a lighthouse, soft pastel colors, 3D render"),
            (tr("Portrait of an old sailor in oil"),
             "Portrait of an old sailor, dramatic side light, oil painting"),
            (tr("Night street food stall in the rain"),
             "Neon-lit street food stall at night, rain reflections, cinematic"),
        ):
            chip = QPushButton(title)
            chip.setProperty("role", "chip")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip(prompt)
            chip.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)  # may narrow
            chip.clicked.connect(lambda _checked=False, text=prompt: self._use_idea(text))
            box.addWidget(chip)
        return self.ideas

    def _use_idea(self, text: str) -> None:
        self.prompt.setPlainText(text)
        self.prompt.setFocus()

    # ============================================================ model choice
    def _fill_models(self) -> None:
        current = self._spec.id if self._spec else self.services.settings.recall("image", "model")
        self.model_box.blockSignals(True)
        self.model_box.clear()
        for spec in self.services.catalog.all("image"):
            name = spec.name
            if not self.services.installed(spec):
                name += f"  ·  {spec.download_gb:.1f} GB"
            self.model_box.addItem(name, spec.id)
        index = max(0, self.model_box.findData(current))
        self.model_box.setCurrentIndex(index)
        self.model_box.blockSignals(False)
        self._model_selected(index)

    def apply_result(self, result: dict[str, Any]) -> None:
        """Gallery "Repeat these settings": fill the form from a finished work."""
        params = result.get("params", {})
        self.select_model(result.get("model_id", ""))
        self.prompt.setPlainText(result.get("prompt", ""))
        self.negative.setPlainText(params.get("negative", "") or "")
        if params.get("width") and params.get("height"):
            self.size_mode.set_value("exact")
            self._show_size_panel("exact")
            self.exact.set_value(int(params["width"]), int(params["height"]))
        if params.get("steps"):
            self.steps.set_value(int(params["steps"]))
        if params.get("guidance") is not None:
            self.guidance.set_value(float(params["guidance"]))
        self.seed.set_value(params.get("seed"))
        self.count.setValue(1)
        if params.get("format") in IMAGE_FORMATS:
            self.file_format.set_value(params["format"])
        self._size_changed()

    def select_model(self, model_id: str) -> None:
        """Called from the Models page ("Use")."""
        index = self.model_box.findData(model_id)
        if index >= 0:
            self.model_box.setCurrentIndex(index)

    def _model_selected(self, _index: int) -> None:
        spec = self.services.catalog.get(self.model_box.currentData() or "")
        if spec is None:
            return
        changed = self._spec is None or self._spec.id != spec.id
        self._spec = spec
        self.model_summary.setText(spec.text(self._lang()))
        uses_negative = bool(spec.default("negative", True))
        self.negative_field.setVisible(uses_negative)
        max_steps = int(spec.default("max_steps", 60))
        self.steps.set_range(1, max_steps)
        uses_guidance = float(spec.default("guidance", 1.0)) > 0
        self.guidance_field.setVisible(uses_guidance)
        if changed:
            self.steps.set_value(int(spec.default("steps", 20)))
            self.guidance.set_value(float(spec.default("guidance", 0.0)))
            native = spec.native
            self.exact.set_value(*native)
        modes = [(m, reference_label(m)) for m in spec.reference]
        self.reference_card.setVisible(bool(modes))
        self.reference_mode.set_options(modes)
        self.reference_mode.setVisible(len(modes) > 1)
        self._reference_changed()
        self._size_changed()
        self._update_action()

    # ============================================================ derived state
    def _target_size(self) -> tuple[int, int]:
        spec = self._spec
        assert spec is not None
        if self.size_mode.value() == "exact":
            return self.exact.value()
        w, h = advisor.size_for_aspect(spec, *self.aspect.value())
        factor = int(self.scale.value() or 1)
        return w * factor, h * factor

    def _size_changed(self) -> None:
        if self._spec is None:
            return
        width, height = self._target_size()
        gen_w, gen_h, route = advisor.resolution_route(self._spec, width, height)
        if route == "upscale":
            self.size_info.setText(tr("{w} × {h} px — the model draws {gw} × {gh}, then it is enlarged",
                                      w=width, h=height, gw=gen_w, gh=gen_h))
        else:
            self.size_info.setText(tr("{w} × {h} px", w=width, h=height))
        self.upscale_field.setVisible(route == "upscale")
        self._refresh_fit()

    def _show_size_panel(self, mode: str) -> None:
        self.aspect_panel.setVisible(mode != "exact")
        self.exact.setVisible(mode == "exact")

    def _size_mode_changed(self, mode: str) -> None:
        if mode == "exact":
            self.exact.set_value(*self._target_size())
        self._show_size_panel(mode)
        self._size_changed()

    def _reference_changed(self) -> None:
        mode = self.reference_mode.value()
        has_ref = bool(self.dropzone.path())
        self.reference_options.setVisible(has_ref and bool(mode))
        self.reference_hint.setText(reference_hint(mode) if mode else "")
        if mode.startswith("ip_adapter") or (mode == "img2img" and self.strength.value() < 0.3):
            self.strength.set_value(0.6)
        self._refresh_fit()

    def _refresh_fit(self) -> None:
        if self._spec is None:
            return
        width, height = self._target_size()
        gen_w, gen_h, _route = advisor.resolution_route(self._spec, width, height)
        reference = self.reference_mode.value() if self.dropzone.path() else ""
        fit = self.services.fit(self._spec, advisor.work_scale(self._spec, gen_w, gen_h), reference)
        self.fit_banner.set_fit(fit)
        self._update_action()

    def _update_action(self) -> None:
        spec = self._spec
        busy = bool(self._jobs)
        self.stop.setVisible(busy)
        if spec is None:
            self.action.setEnabled(False)
            return
        if self.services.downloads.is_active(spec.id):
            self.stop.setVisible(True)
            state = self.services.downloads.state(spec.id)
            done, total = (state[0], state[1]) if state else (0, 0)
            percent = f" {round(done / total * 100)} %" if total else ""
            self.action.setText(tr("Downloading") + percent)
            self.action.setEnabled(False)
            return
        if not self.services.installed(spec):
            self.action.setText(tr("Download ({size:.1f} GB)", size=spec.download_gb))
            fit = self.services.fit(spec)
            self.action.setEnabled(fit is None or fit.ok)
            return
        fit = self.services.fit(spec)
        self.action.setText(tr("Add to queue") if busy else tr("Create"))
        self.action.setEnabled(bool(self.prompt.toPlainText().strip()) and (fit is None or fit.ok))

    def _lang(self) -> str:
        from tvorka.i18n import language

        return language()

    # ============================================================ actions
    def _action_clicked(self) -> None:
        spec = self._spec
        if spec is None:
            return
        if not self.services.installed(spec):
            self.services.downloads.start(spec)
            self._update_action()
            return
        self.generate()

    def generate(self) -> None:
        spec = self._spec
        if spec is None or not self.action.isEnabled() or not self.services.installed(spec):
            return
        width, height = self._target_size()
        params: dict[str, Any] = {
            "width": width, "height": height, "steps": int(self.steps.value()),
            "guidance": self.guidance.value() if self.guidance_field.isVisible() else 0.0,
            "count": self.count.value(), "format": self.file_format.value(),
            "upscale_mode": self.upscale_mode.value(), "seed": self.seed.value(),
        }
        if self.negative_field.isVisible():
            params["negative"] = self.negative.toPlainText().strip()
        if self.dropzone.path() and self.reference_mode.value():
            params.update(reference=self.dropzone.path(), reference_mode=self.reference_mode.value(),
                          strength=self.strength.value())
        job = Job("image", spec.id, self.prompt.toPlainText().strip(), params)
        self._jobs.add(job.id)
        self._remember()
        self.services.worker.submit(job)
        self.ideas.setVisible(False)
        self.canvas.set_progress(0.0, tr("Waiting in the queue…"))
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
            self.strip.add(result["path"])
        if results:
            self._show_result(results[-1])  # the strip selects the newest one too
            self.seed.remember(int(results[-1]["params"].get("seed", 0)))
        self._job_done()

    def _on_failed(self, job_id: int, code: str, detail: str) -> None:
        if job_id not in self._jobs:
            return
        self._jobs.discard(job_id)
        self._job_done()
        if self.toasts is not None:
            self.toasts.show(messages.engine_error(code, detail), "bad")

    def _on_cancelled(self, job_id: int) -> None:
        if job_id in self._jobs:
            self._jobs.discard(job_id)
            self._job_done()

    def _job_done(self) -> None:
        if not self._jobs:
            self.canvas.set_progress(None)
        self._update_action()

    def _on_hardware(self, _hw: object) -> None:
        self._refresh_fit()

    def _on_download_cancelled(self, _model_id: str) -> None:
        self._update_action()

    def _on_download_progress(self, model_id: str, *_args: object) -> None:
        if self._spec is not None and model_id == self._spec.id:
            self._update_action()

    def _on_download_failed(self, model_id: str, code: str, _message: str) -> None:
        if self._spec is not None and model_id == self._spec.id:
            self._update_action()
            if self.toasts is not None:
                self.toasts.show(messages.hub_error(code), "bad")

    # ============================================================ results
    def _show_result(self, result: dict[str, Any]) -> None:
        self._last_result = result
        params = result["params"]
        self.canvas.set_image(result["path"])
        self.ideas.setVisible(False)
        self.result_info.setText(f"{params.get('width')} × {params.get('height')}  ·  "
                                 f"{tr('seed')} {params.get('seed')}  ·  {result['seconds']:.1f} s")
        for button in self.result_actions:
            button.setEnabled(True)

    def _show_result_path(self, path: str) -> None:
        item = next((r for r in self.services.history.items("image") if r.path == path), None)
        if item is not None:
            from dataclasses import asdict

            self._show_result(asdict(item))

    def _current_path(self) -> str:
        return self._last_result["path"] if self._last_result else ""

    def _save_as(self) -> None:
        source = self._current_path()
        if not source:
            return
        target, _ = QFileDialog.getSaveFileName(self, tr("Save as"), Path(source).name)
        if target:
            shutil.copyfile(source, target)

    def _open_folder(self) -> None:
        source = self._current_path()
        if not source:
            return
        if os.name == "nt":
            import subprocess

            subprocess.Popen(["explorer", "/select,", os.path.normpath(source)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(source).parent)))

    def _copy(self) -> None:
        source = self._current_path()
        if source:
            QGuiApplication.clipboard().setImage(QImage(source))
            if self.toasts is not None:
                self.toasts.show(tr("Image copied"), "ok", timeout_ms=1800)

    def _use_as_reference(self) -> None:
        if self._current_path():
            self.dropzone.set_path(self._current_path())

    def _repeat_seed(self) -> None:
        if self._last_result:
            self.seed.set_value(int(self._last_result["params"].get("seed", 0)))

    def _to_video(self) -> None:
        window = self.window()
        page = getattr(window, "page", lambda _k: None)("video")
        if page is not None and hasattr(page, "set_first_frame"):
            page.set_first_frame(self._current_path())
            window.open_page(window.pages.index(page))
        elif self.toasts is not None:
            self.toasts.show(tr("The Video page is not available yet."), "info")

    # ============================================================ persistence
    def save_state(self) -> None:
        self._remember()

    def _remember(self) -> None:
        self.services.settings.remember(
            "image", model=self._spec.id if self._spec else "", prompt=self.prompt.toPlainText(),
            negative=self.negative.toPlainText(), aspect=list(self.aspect.value()),
            scale=self.scale.value(), size_mode=self.size_mode.value(), exact=list(self.exact.value()),
            format=self.file_format.value(), count=self.count.value(), upscale=self.upscale_mode.value())

    def _restore(self) -> None:
        recall = self.services.settings.recall
        self.prompt.setPlainText(recall("image", "prompt", ""))
        self.negative.setPlainText(recall("image", "negative", ""))
        aspect = recall("image", "aspect")
        if aspect:
            self.aspect.set_value(*aspect)
        self.scale.set_value(recall("image", "scale", "1"))
        self.file_format.set_value(recall("image", "format", self.services.settings.image_format))
        self.count.setValue(int(recall("image", "count", 1)))
        self.upscale_mode.set_value(recall("image", "upscale", "quality"))
        mode = recall("image", "size_mode", "aspect")
        self.size_mode.set_value(mode)
        exact = recall("image", "exact")
        if exact:
            self.exact.set_value(*exact)
        self._show_size_panel(mode)
        self._size_changed()
