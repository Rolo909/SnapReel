"""One message of a chat: the text (Markdown for answers), folded reasoning and actions."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontMetrics, QResizeEvent, QTextCharFormat, QTextCursor, QTextDocument, QTextFormat
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from tvorka.core.chats import Message
from tvorka.gui import theme
from tvorka.gui.widgets.basic import Disclosure, label, tool_button
from tvorka.gui.widgets.chat_attachments import AttachmentChip
from tvorka.i18n import tr


def markdown_html(text: str) -> str:
    """Markdown as HTML in the theme's colours: thin table borders, code in the mono font."""
    document = QTextDocument()
    document.setMarkdown(text)
    line, code_bg = theme.color("line"), theme.color("raised")
    block = document.begin()
    while block.isValid():
        table = QTextCursor(block).currentTable()
        if table is not None:
            fmt = table.format()
            if fmt.borderBrush().color() != line:
                fmt.setBorderBrush(line)
                fmt.setBorder(1)
                fmt.setBorderCollapse(True)
                fmt.setCellPadding(4)
                table.setFormat(fmt)
        if block.blockFormat().hasProperty(QTextFormat.Property.BlockCodeFence):
            cursor = QTextCursor(block)
            block_format = block.blockFormat()
            block_format.setBackground(code_bg)
            cursor.setBlockFormat(block_format)
            cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
            mono = QTextCharFormat()
            mono.setFontFamilies([theme.font_family("mono")])
            cursor.mergeCharFormat(mono)
        block = block.next()
    return document.toHtml()


def _text(role: str) -> QLabel:
    widget = label("", "chat", wrap=True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse
                                   | Qt.TextInteractionFlag.LinksAccessibleByMouse)
    widget.setOpenExternalLinks(True)
    # Answers are Markdown; what the user typed is shown exactly as typed.
    widget.setTextFormat(Qt.TextFormat.RichText if role == "assistant" else Qt.TextFormat.PlainText)
    return widget


class MessageView(QWidget):
    """``action`` carries ``copy``, ``edit`` or ``regenerate`` for the message at ``index``."""

    action = Signal(str, int)

    def __init__(self, message: Message, index: int, model_name: str = "", last: bool = False,
                 live: bool = False, folder: Path | None = None) -> None:
        super().__init__()
        self.index, self.role = index, message.role
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.bubble = QFrame()
        self.bubble.setObjectName("ChatBubble")
        self.bubble.setProperty("who", message.role)
        box = QVBoxLayout(self.bubble)
        if message.role == "user":
            box.setContentsMargins(14, 10, 14, 8)
        else:
            box.setContentsMargins(2, 4, 2, 4)
        box.setSpacing(6)
        if message.role == "user":
            outer.addStretch(1)  # the user's messages sit on the right, as wide as their text
            outer.addWidget(self.bubble)
        else:
            outer.addWidget(self.bubble)

        self.reasoning = Disclosure(tr("Reasoning"))
        self.reasoning_text = label("", "faint", wrap=True)
        self.reasoning_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.reasoning.body.addWidget(self.reasoning_text)
        box.addWidget(self.reasoning)
        self.body = _text(message.role)
        box.addWidget(self.body)
        if message.attachments:  # the files that went with the message
            files = QHBoxLayout()
            files.setSpacing(6)
            if message.role == "user":
                files.addStretch(1)
            for item in message.files:
                files.addWidget(AttachmentChip(item.name, item, folder, removable=False))
            if message.role != "user":
                files.addStretch(1)
            box.addLayout(files)
        self.note = label("", "faint", wrap=True)
        box.addWidget(self.note)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(2)
        if message.role == "user":
            row.addStretch(1)
        self.meta = label("", "faint")
        buttons = [("copy", "copy", tr("Copy"))]
        if message.role == "user":
            buttons.append(("edit", "edit", tr("Edit and send again")))
        else:
            buttons.append(("send", "link", tr("Send to… (draw it, make a video, read aloud)")))
            if last:
                buttons.append(("regenerate", "refresh", tr("Answer again")))
        self.buttons = []
        for name, glyph, tip in buttons:
            button = tool_button(glyph, tip)
            button.clicked.connect(lambda _=False, n=name: self.action.emit(n, self.index))
            row.addWidget(button)
            self.buttons.append(button)
        row.addWidget(self.meta)
        if message.role != "user":
            row.addStretch(1)
        self.actions = QWidget()
        self.actions.setLayout(row)
        box.addWidget(self.actions)
        self.model_name = model_name
        self.update_from(message, live)

    def resizeEvent(self, event: QResizeEvent) -> None:
        """A user's message is as wide as its text, at most three quarters of the conversation."""
        super().resizeEvent(event)
        if self.role != "user":
            return
        widest = int(self.width() * 0.75)
        metrics = QFontMetrics(self.body.font())
        text = max((metrics.horizontalAdvance(line) for line in self.body.text().splitlines()), default=0)
        inner = min(widest - 28, max(text + 4, 120))  # 28: the bubble's side padding
        if self.body.minimumWidth() != inner:
            self.body.setMinimumWidth(inner)
            self.bubble.setMaximumWidth(widest)

    def update_from(self, message: Message, live: bool = False) -> None:
        """Show ``message``; ``live`` while its answer is still being written."""
        self.reasoning.setVisible(bool(message.reasoning))
        self.reasoning.toggle.setText(tr("Thinking…") if live and not message.content else tr("Reasoning"))
        self.reasoning_text.setText(message.reasoning.strip())
        self.body.setText(markdown_html(message.content) if self.role == "assistant" else message.content)
        self.body.setVisible(bool(message.content))
        notes = []
        if message.stopped:
            notes.append(tr("The answer was cut short."))
        self.note.setText(" ".join(notes))
        self.note.setVisible(bool(notes))
        self.actions.setVisible(not live)
        meta = [self.model_name] if message.role == "assistant" and self.model_name else []
        speed = message.stats.get("predicted_per_second")
        if speed:
            meta.append(tr("{speed:.0f} tokens/s", speed=float(speed)))
        self.meta.setText("  ·  ".join(meta))

    def set_out_of_context(self, out: bool) -> None:
        """Older messages the model no longer sees are dimmed."""
        self.body.setProperty("role", "faint" if out else "chat")
        self.body.style().unpolish(self.body)
        self.body.style().polish(self.body)
        self.setToolTip(tr("The model no longer sees this message: the conversation is longer than "
                           "its memory.") if out else "")
