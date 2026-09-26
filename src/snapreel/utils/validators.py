"""Input validators for user-provided data."""

from __future__ import annotations

import re

# Known edge-tts voice patterns
_VOICE_PATTERN = re.compile(r"^[a-z]{2}-[A-Z]{2}-\w+Neural$")

# Supported visual modes
VALID_VISUAL_MODES = frozenset({"static", "video"})

# Supported styles
VALID_STYLES = frozenset({
    "motivational",
    "educational",
    "storytelling",
    "news",
    "comedy",
    "dramatic",
    "documentary",
})


def validate_topic(topic: str) -> str:
    """Validate and clean a video topic.

    Args:
        topic: Raw topic string from user.

    Returns:
        Cleaned topic string.

    Raises:
        ValueError: If topic is empty or too long.
    """
    cleaned = topic.strip()
    if not cleaned:
        raise ValueError("Topic cannot be empty")
    if len(cleaned) > 500:
        raise ValueError(f"Topic too long ({len(cleaned)} chars, max 500)")
    return cleaned


def validate_scene_count(count: int) -> int:
    """Validate scene count.

    Args:
        count: Number of scenes.

    Returns:
        Validated scene count.

    Raises:
        ValueError: If count is out of range.
    """
    if not 1 <= count <= 20:
        raise ValueError(f"Scene count must be 1-20, got {count}")
    return count


def validate_voice(voice: str) -> str:
    """Validate an edge-tts voice identifier.

    Args:
        voice: Voice identifier (e.g., 'ru-RU-DmitryNeural').

    Returns:
        Validated voice string.

    Raises:
        ValueError: If voice format is invalid.
    """
    if not _VOICE_PATTERN.match(voice):
        raise ValueError(f"Invalid voice format: '{voice}'. Expected pattern: xx-XX-NameNeural")
    return voice


def validate_visual_mode(mode: str) -> str:
    """Validate the visual generation mode.

    Args:
        mode: Visual mode ('static' or 'video').

    Returns:
        Validated mode string.

    Raises:
        ValueError: If mode is not supported.
    """
    if mode not in VALID_VISUAL_MODES:
        raise ValueError(f"Invalid visual mode: '{mode}'. Must be one of {VALID_VISUAL_MODES}")
    return mode
