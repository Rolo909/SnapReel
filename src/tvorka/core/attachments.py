"""Files attached to a chat message: what the model gets from each of them.

Images are scaled down and sent as pictures (the model needs a projector, ``mmproj``);
text, code, PDF and Word files are sent as text; a video gives a few evenly spaced
frames and, with a speech recognition model, what is said in it; a sound file is sent
as what is said in it. Everything is copied next to the conversation, so a chat keeps working after
the original file is moved or deleted. File contents are data for the model, never
instructions to the app.
"""

from __future__ import annotations

import base64
import itertools
import logging
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini",
            ".cfg", ".log", ".xml", ".html", ".htm", ".css", ".py", ".js", ".ts", ".tsx", ".jsx", ".java",
            ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".sql", ".sh",
            ".bat", ".ps1", ".lua", ".r", ".tex", ".srt", ".vtt"}
DOC_EXT = {".pdf", ".docx"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
AUDIO_EXT = {".wav", ".mp3", ".ogg", ".m4a", ".flac", ".opus"}

MAX_SIDE = 1024  # pixels; enough to read text in a screenshot, ~1000 tokens for a vision model
VIDEO_FRAMES = 6
MAX_TEXT_TOKENS = 6000  # one file may not take the whole conversation memory
CHARS_PER_TOKEN = 3.0
PATCH = 28  # vision encoders cut an image into patches of about this size; one patch ≈ one token


class AttachmentError(Exception):
    """``code``: unsupported, unreadable, needs_docs, audio (no recognition model), empty, silent."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


@dataclass
class Attachment:
    name: str  # the original file name
    kind: str  # image | text | document | video | audio
    files: list[str] = field(default_factory=list)  # stored copies (names inside the chat's folder)
    text: str = ""  # what the model reads (text, code, documents)
    tokens: int = 0  # about how much of the model's memory it takes
    truncated: bool = False  # the text was too long and was cut

    @property
    def images(self) -> list[str]:
        return self.files if self.kind in ("image", "video") else []

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Attachment:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


def kind_of(path: Path) -> str:
    """image | text | document | video | audio | "" (not supported)."""
    suffix = path.suffix.lower()
    for kind, extensions in (("image", IMAGE_EXT), ("text", TEXT_EXT), ("document", DOC_EXT),
                             ("video", VIDEO_EXT), ("audio", AUDIO_EXT)):
        if suffix in extensions:
            return kind
    return ""


def image_tokens(width: int, height: int) -> int:
    return max(1, round(width / PATCH)) * max(1, round(height / PATCH)) + 8


Transcriber = Callable[[Path], "str | None"]  # the words in a sound file; None: no recognition model


def prepare(source: Path, folder: Path, transcribe: Transcriber | None = None) -> Attachment:
    """Read ``source`` and store what the model needs in ``folder`` (the chat's files).

    ``transcribe`` turns speech into text (blocking; called from a worker thread).
    """
    kind = kind_of(source)
    if not kind:
        raise AttachmentError("unsupported", source.name)
    if not source.is_file():
        raise AttachmentError("unreadable", source.name)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if kind == "image":
            from PIL import Image

            with Image.open(source) as image:
                return _store_images(source.name, "image", [image.copy()], folder)
        if kind == "video":
            item = _store_images(source.name, "video", _video_frames(source), folder)
            item.text = _speech(source, transcribe, required=False)
            item.tokens += int(len(item.text) / CHARS_PER_TOKEN)
            return item
        if kind == "audio":
            text = _speech(source, transcribe, required=True)
        else:
            text = read_text(source) if kind == "text" else _document_text(source)
    except AttachmentError:
        raise
    except Exception as exc:  # a damaged file is the user's to replace, not a crash
        log.info("cannot read %s: %s", source, exc)
        raise AttachmentError("unreadable", f"{source.name}: {exc}") from exc
    if not text.strip():
        raise AttachmentError("empty", source.name)
    text, truncated = _cut(text)
    stored = _unique(folder, source.name)
    shutil.copyfile(source, stored)
    tokens = int(len(text) / CHARS_PER_TOKEN) + 20
    return Attachment(source.name, kind, [stored.name], text, tokens, truncated)


def image_attachment(image: Any, folder: Path, name: str = "image.png") -> Attachment:
    """A picture that is not a file (pasted from the clipboard): a ``PIL.Image``."""
    folder.mkdir(parents=True, exist_ok=True)
    return _store_images(name, "image", [image], folder)


def read_text(path: Path) -> str:
    """A text file in UTF-8 (with or without BOM), UTF-16, or else the Windows Cyrillic code page."""
    raw = path.read_bytes()
    if b"\x00" in raw[:4096] and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise AttachmentError("unsupported", f"{path.name}: binary file")
    wide = raw.startswith((b"\xff\xfe", b"\xfe\xff"))
    try:
        text = raw.decode("utf-16" if wide else "utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251", errors="replace")
    return text.replace("\r\n", "\n")


def _document_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise AttachmentError("needs_docs", path.name) from exc
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        return "\n\n".join(f"[page {i}]\n{text}" for i, text in enumerate(pages, 1) if text)
    try:
        import docx
    except ImportError as exc:
        raise AttachmentError("needs_docs", path.name) from exc
    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs if p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


def _speech(path: Path, transcribe: Transcriber | None, required: bool) -> str:
    """What is said in a sound file or a video. A video may be silent; a sound file may not."""
    from tvorka.engines.base import EngineError

    try:
        text = transcribe(path) if transcribe is not None else None
    except EngineError as exc:
        if required:
            raise AttachmentError("unreadable" if exc.code != "no_sound" else "silent", path.name) from exc
        return ""  # frames alone still tell a lot
    if text is None and required:
        raise AttachmentError("audio", path.name)
    if not text and required:
        raise AttachmentError("silent", path.name)
    return text or ""


def _video_frames(path: Path) -> list[Any]:
    """Evenly spaced frames: what happens in the video, for a model that sees images.

    Each frame is found by seeking, so a long video is never decoded whole.
    """
    import av

    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        if stream.duration and stream.time_base:
            duration = float(stream.duration * stream.time_base)
        else:
            duration = (container.duration or 0) / 1_000_000
        images = []
        for i in range(VIDEO_FRAMES if duration > 0 else 0):
            target = duration * (i + 0.5) / VIDEO_FRAMES
            container.seek(int(target / stream.time_base), stream=stream)  # the key frame before it
            for frame in container.decode(stream):
                if frame.time is None or frame.time >= target - 0.001:
                    images.append(frame.to_image())
                    break
        if not images:  # no duration in the file: sample the beginning
            container.seek(0)
            frames = [f.to_image() for f in itertools.islice(container.decode(stream), VIDEO_FRAMES * 30)]
            images = frames[:: max(1, len(frames) // VIDEO_FRAMES)][:VIDEO_FRAMES]
    if not images:
        raise AttachmentError("unreadable", f"{path.name}: no frames")
    return images


def _store_images(name: str, kind: str, images: list[Any], folder: Path) -> Attachment:
    stored, tokens = [], 0
    stem = Path(name).stem or "image"
    for index, image in enumerate(images):
        picture = image.convert("RGB")
        picture.thumbnail((MAX_SIDE, MAX_SIDE))
        target = _unique(folder, f"{stem}-{index + 1}.jpg" if kind == "video" else f"{stem}.jpg")
        picture.save(target, "JPEG", quality=90)
        stored.append(target.name)
        tokens += image_tokens(*picture.size)
    return Attachment(name, kind, stored, "", tokens)


def _cut(text: str) -> tuple[str, bool]:
    limit = int(MAX_TEXT_TOKENS * CHARS_PER_TOKEN)
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _unique(folder: Path, name: str) -> Path:
    target = folder / Path(name).name
    stem, suffix, n = target.stem, target.suffix, 2
    while target.exists():
        target = folder / f"{stem}-{n}{suffix}"
        n += 1
    return target


def message_content(text: str, attachments: list[Attachment], folder: Path,
                    with_images: bool = True) -> str | list[dict[str, Any]]:
    """The message as the server expects it: plain text, or text and pictures (OpenAI format)."""
    parts = []
    for item in attachments:
        if item.text and item.kind in ("audio", "video"):
            parts.append(f"What is said in “{item.name}” (speech recognition):\n{item.text}")
        elif item.text:
            note = " (cut: the file is longer)" if item.truncated else ""
            parts.append(f"File “{item.name}”{note}:\n```\n{item.text}\n```")
    body = "\n\n".join([*parts, text] if text else parts)
    images = [folder / f for item in attachments for f in item.images] if with_images else []
    if not images:
        return body
    content: list[dict[str, Any]] = []
    for item in attachments:
        if item.kind == "video" and with_images:
            content.append({"type": "text", "text": f"Frames from the video “{item.name}”, in order:"})
        for name in item.images if with_images else []:
            data = base64.b64encode((folder / name).read_bytes()).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
    content.append({"type": "text", "text": body or "?"})
    return content
