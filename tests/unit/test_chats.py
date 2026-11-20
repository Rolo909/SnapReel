"""Conversations: storage, roles, what fits in the context."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tvorka.core import chats
from tvorka.core.chats import ChatStore, Conversation, Message


def test_conversation_survives_a_round_trip(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "chats")
    conv = Conversation(title="Маяк", model="m", role="translator", temperature=0.3, ctx=16384)
    conv.messages = [Message("user", "Привет"), Message("assistant", "Здравствуйте", "думаю…", "m",
                                                        {"predicted_per_second": 40.0}, stopped=True)]
    store.save(conv)
    [loaded] = store.all()
    assert loaded == conv
    assert not list((tmp_path / "chats").glob("*.tmp"))


def test_most_recent_first_and_delete(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    old, new = Conversation(title="old", updated=100.0), Conversation(title="new", updated=200.0)
    store.save(old)
    store.save(new)
    assert [c.title for c in store.all()] == ["new", "old"]
    store.delete(new.id)
    assert [c.title for c in store.all()] == ["old"]
    with pytest.raises(ValueError):
        store.delete("../settings")


def test_damaged_file_is_skipped(tmp_path: Path) -> None:
    store = ChatStore(tmp_path)
    store.save(Conversation(title="ok"))
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    assert [c.title for c in store.all()] == ["ok"]
    assert ChatStore(tmp_path / "missing").all() == []


def test_unknown_fields_are_ignored() -> None:
    data = {"id": "x-1", "title": "t", "future": 1, "messages": [{"role": "user", "content": "a", "new": 2}]}
    conv = Conversation.from_dict(json.loads(json.dumps(data)))
    assert conv.messages == [Message("user", "a")]


def test_instruction_comes_from_the_role_unless_written() -> None:
    conv = Conversation(role="translator")
    assert conv.instruction == chats.ROLES["translator"]
    conv.system = "  Отвечай стихами.  "
    assert conv.instruction == "Отвечай стихами."
    assert Conversation(role="gone").instruction == chats.ROLES["assistant"]


def test_old_messages_leave_the_context_first() -> None:
    conv = Conversation()
    conv.messages = [Message("user" if i % 2 == 0 else "assistant", f"{i} " + "слово " * 300)
                     for i in range(10)]
    sent, dropped = chats.context_messages(conv, 4096)
    assert sent[0] == {"role": "system", "content": conv.instruction}
    assert sent[-1]["content"].startswith("9 ")
    assert 0 < dropped < 10 and len(sent) == 1 + 10 - dropped
    used = sum(chats.estimate_tokens(m["content"]) for m in sent)
    assert used <= 4096 - 1024
    everything, none = chats.context_messages(conv, 131072)
    assert none == 0 and len(everything) == 11


def test_last_message_is_sent_even_when_it_is_too_long() -> None:
    conv = Conversation(messages=[Message("user", "x" * 100_000)])
    sent, dropped = chats.context_messages(conv, 4096)
    assert dropped == 0 and sent[-1]["content"] == "x" * 100_000  # the server explains the overflow


def test_request_leaves_unset_sampling_to_the_model() -> None:
    conv = Conversation()
    assert chats.request_params(conv, reasoning=False) == {}
    assert chats.request_params(conv, reasoning=True) == {"chat_template_kwargs": {"enable_thinking": False}}
    conv.temperature, conv.thinking = 0.0, True
    assert chats.request_params(conv, reasoning=True) == {"temperature": 0.0,
                                                          "chat_template_kwargs": {"enable_thinking": True}}


def test_titles() -> None:
    assert chats.default_title("  Напиши   сценарий\nролика ") == "Напиши сценарий ролика"
    assert chats.default_title("раз два три четыре пять шесть семь") == "раз два три четыре пять шесть…"
    assert len(chats.default_title("о" * 200)) == chats.TITLE_CHARS
    assert chats.clean_title('Заголовок: «Сценарий о маяке».\nвторая строка') == "Сценарий о маяке"
    assert chats.clean_title("**Lighthouse story**") == "Lighthouse story"
    assert chats.clean_title("") == "" and chats.clean_title("x" * 200) == ""


def test_attachments_travel_with_the_message(tmp_path: Path) -> None:
    from PIL import Image

    from tvorka.core.attachments import Attachment

    store = ChatStore(tmp_path / "chats")
    conv = Conversation()
    folder = store.files_dir(conv.id)
    folder.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(folder / "pic.jpg")
    picture = Attachment("pic.png", "image", ["pic.jpg"], tokens=700)
    note = Attachment("a.txt", "text", ["a.txt"], "файл", 30)
    conv.messages = [Message("user", "что на картинке?", attachments=[picture.to_dict(), note.to_dict()])]
    assert conv.messages[0].tokens() == chats.estimate_tokens("что на картинке?") + 730
    assert conv.messages[0].tokens(vision=False) == chats.estimate_tokens("что на картинке?") + 30

    sent, _ = chats.context_messages(conv, 8192, folder)
    assert [p["type"] for p in sent[-1]["content"]] == ["image_url", "text"]
    blind, _ = chats.context_messages(conv, 8192, folder, vision=False)
    assert isinstance(blind[-1]["content"], str) and "файл" in blind[-1]["content"]

    store.save(conv)
    assert store.all()[0].messages[0].files == [picture, note]
    store.delete(conv.id)
    assert not folder.exists() and store.all() == []


def test_pictures_count_against_the_memory() -> None:
    from tvorka.core.attachments import Attachment

    heavy = Attachment("big.png", "image", ["big.jpg"], tokens=3000).to_dict()
    conv = Conversation(messages=[Message("user", "старое", attachments=[heavy]), Message("assistant", "ок"),
                                  Message("user", "новое", attachments=[heavy])])
    sent, dropped = chats.context_messages(conv, 4096)
    assert dropped == 1 and sent[1]["content"] == "ок"  # the old picture does not fit next to the new one
    _sent, dropped = chats.context_messages(conv, 4096, vision=False)
    assert dropped == 0
