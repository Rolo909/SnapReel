"""Conversations with a chat model: messages, roles, what fits in the context, storage.

One JSON file per conversation in ``<data>/chats/``. Texts the model sees (role
instructions) are English; the model answers in the language the user writes in.
"""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import time
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from tvorka.core.attachments import Attachment, message_content

log = logging.getLogger(__name__)

_SAME_LANGUAGE = " Always answer in the language the user writes in."
# Role presets: key -> instruction. Their names are shown by the interface.
ROLES: dict[str, str] = {
    "assistant": "You are a helpful, friendly assistant. Answer clearly and to the point." + _SAME_LANGUAGE,
    "image_prompts": (
        "You write prompts for image generation models such as Stable Diffusion and FLUX. Turn the user's "
        "idea into one detailed English prompt: subject, setting, composition, lighting, style, camera or "
        "medium. Reply with the prompt first, then at most two short alternatives. Explain only if asked."
    ),
    "video_director": (
        "You are a video director. Turn the user's idea into short English prompts for a text-to-video "
        "model: one prompt per shot, 1–2 sentences each, with the camera movement, the action and the "
        "lighting. Keep every shot achievable in 3–5 seconds." + _SAME_LANGUAGE
    ),
    "screenwriter": (
        "You are a screenwriter. Help with ideas, plots, scripts and dialogue for short videos. "
        "Be concrete and vivid, keep the structure clear: hook, development, ending." + _SAME_LANGUAGE
    ),
    "translator": (
        "You are a translator. Translate the user's text: Russian into English, any other language into "
        "Russian, unless the user names the target language. Keep the meaning, tone and formatting. "
        "Reply with the translation only."
    ),
    "voice_editor": (
        "You prepare text to be read aloud by a speech synthesizer. Fix spelling and punctuation, write "
        "numbers, dates, units and abbreviations out in words, split long sentences, remove what cannot "
        "be pronounced (markup, emoji, links). Keep the language of the text. Reply with the text only."
    ),
}
DEFAULT_ROLE = "assistant"
CHARS_PER_TOKEN = 3.0  # rough: a token is 3–4 characters of Russian or English text
TITLE_WORDS, TITLE_CHARS = 6, 48


@dataclass
class Message:
    role: str  # user | assistant
    content: str = ""
    reasoning: str = ""
    model: str = ""  # model id that wrote an answer
    stats: dict[str, Any] = field(default_factory=dict)  # tokens per second, token counts
    stopped: bool = False  # the answer was cut short (stopped by the user or an error)
    attachments: list[dict[str, Any]] = field(default_factory=list)  # ``Attachment.to_dict()``

    @property
    def files(self) -> list[Attachment]:
        return [Attachment.from_dict(a) for a in self.attachments if isinstance(a, dict)]

    def tokens(self, vision: bool = True) -> int:
        """About how much of the model's memory the message takes, with its attachments."""
        extra = sum(a.tokens for a in self.files if vision or not a.images)
        return estimate_tokens(self.content) + extra

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Conversation:
    id: str = ""
    title: str = ""
    model: str = ""
    role: str = DEFAULT_ROLE
    system: str = ""  # own instruction for this chat; empty: the role's
    temperature: float | None = None  # None: what the model's authors recommend (stored in the GGUF)
    thinking: bool = False  # let a reasoning model think before answering: better, but much slower
    ctx: int = 0  # tokens the model keeps in mind; 0: the advisor's choice
    created: float = 0.0
    updated: float = 0.0
    messages: list[Message] = field(default_factory=list)

    def __post_init__(self) -> None:
        now = time.time()
        self.id = self.id or time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        self.created = self.created or now
        self.updated = self.updated or now

    @property
    def instruction(self) -> str:
        return self.system.strip() or ROLES.get(self.role, ROLES[DEFAULT_ROLE])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Conversation:
        if not isinstance(data, dict):
            raise TypeError("a conversation is a JSON object")
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known and k != "messages"}
        conv = cls(**clean)
        conv.messages = [Message.from_dict(m) for m in data.get("messages", []) if isinstance(m, dict)]
        return conv


def request_params(conv: Conversation, reasoning: bool) -> dict[str, Any]:
    """Sampling settings for the server; whatever is not set stays as the model recommends."""
    params: dict[str, Any] = {}
    if conv.temperature is not None:
        params["temperature"] = conv.temperature
    if reasoning:  # models that think by default, like Qwen3.5, are told whether to
        params["chat_template_kwargs"] = {"enable_thinking": conv.thinking}
    return params


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 4  # + the role markers around every message


def context_messages(conv: Conversation, ctx: int, folder: Path | None = None,
                     vision: bool = True) -> tuple[list[dict[str, Any]], int]:
    """What is sent to the model, and how many of the oldest messages no longer fit.

    The instruction and the last message (with its attachments) always go; older messages
    are dropped first. Room is left for the answer (a quarter of the context, at most 2048
    tokens). ``folder`` holds the chat's files; pictures go only to a model that sees them.
    """
    budget = ctx - min(2048, ctx // 4) - estimate_tokens(conv.instruction)
    kept: list[dict[str, Any]] = []
    for message in reversed(conv.messages):
        cost = message.tokens(vision)
        if kept and cost > budget:
            break
        content: Any = message.content
        if message.attachments and folder is not None:
            content = message_content(message.content, message.files, folder, with_images=vision)
        kept.append({"role": message.role, "content": content})
        budget -= cost
    kept.reverse()
    dropped = len(conv.messages) - len(kept)
    return [{"role": "system", "content": conv.instruction}, *kept], dropped


def default_title(text: str) -> str:
    """The first words of the first message, until the model suggests a better title."""
    words = " ".join(text.split()).split(" ")
    title = " ".join(words[:TITLE_WORDS])
    if len(title) > TITLE_CHARS:
        title = title[: TITLE_CHARS - 1].rstrip() + "…"
    elif len(words) > TITLE_WORDS:
        title += "…"
    return title


def clean_title(text: str) -> str:
    """A title the model wrote: one line, no quotes, no closing period."""
    line = next((s for s in text.strip().splitlines() if s.strip()), "")
    line = re.sub(r"^(title|заголовок)\s*:\s*", "", line.strip(), flags=re.IGNORECASE)
    line = line.strip().rstrip(".").strip(" \"'«»“”*#").rstrip(".")
    return line if 0 < len(line) <= 80 else ""


class ChatStore:
    """Conversations on disk; a damaged file is skipped, never fatal."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _file(self, conv_id: str) -> Path:
        if not re.fullmatch(r"[\w-]+", conv_id):
            raise ValueError(f"bad conversation id: {conv_id!r}")
        return self.folder / f"{conv_id}.json"

    def all(self) -> list[Conversation]:
        """Every conversation, the most recent first."""
        out = []
        for file in self.folder.glob("*.json") if self.folder.is_dir() else []:
            try:
                out.append(Conversation.from_dict(json.loads(file.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError) as exc:
                log.warning("skipping damaged chat %s: %s", file.name, exc)
        return sorted(out, key=lambda c: c.updated, reverse=True)

    def save(self, conv: Conversation) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        target = self._file(conv.id)
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(conv.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, target)  # a crash mid-write leaves the previous version intact

    def files_dir(self, conv_id: str) -> Path:
        """Where the conversation's attachments are kept."""
        return self._file(conv_id).with_suffix("")

    def delete(self, conv_id: str) -> None:
        self._file(conv_id).unlink(missing_ok=True)
        shutil.rmtree(self.files_dir(conv_id), ignore_errors=True)
