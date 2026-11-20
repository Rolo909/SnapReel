"""Attachments: what the model gets from each kind of file."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from tvorka.core import attachments
from tvorka.core.attachments import Attachment, AttachmentError


def pdf_with_text(path: Path, text: str) -> Path:
    """A one-page PDF written by hand: the smallest file pypdf can read text from."""
    stream = f"BT /F1 18 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(out)
    return path


def test_kinds() -> None:
    names = {"a.PNG": "image", "b.py": "text", "c.pdf": "document", "d.docx": "document", "e.mp4": "video",
             "f.mp3": "audio", "g.exe": "", "h": ""}
    assert {n: attachments.kind_of(Path(n)) for n in names} == names


def test_big_image_is_scaled_down(tmp_path: Path) -> None:
    source = tmp_path / "photo.png"
    Image.new("RGB", (3000, 1500), (200, 40, 40)).save(source)
    item = attachments.prepare(source, tmp_path / "files")
    assert (item.kind, item.name, item.files) == ("image", "photo.png", ["photo.jpg"])
    with Image.open(tmp_path / "files" / "photo.jpg") as stored:
        assert stored.size == (1024, 512)
    assert item.tokens == attachments.image_tokens(1024, 512) and 600 < item.tokens < 800
    again = attachments.prepare(source, tmp_path / "files")  # same name twice: both kept
    assert again.files == ["photo-2.jpg"]


def test_text_in_any_usual_encoding(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    utf8 = tmp_path / "notes.md"
    utf8.write_text("# Заметки\nпривет", encoding="utf-8-sig")
    cp1251 = tmp_path / "old.txt"
    cp1251.write_bytes("старый текст".encode("cp1251"))
    utf16 = tmp_path / "wide.csv"
    utf16.write_text("a;b\nя;ты", encoding="utf-16")
    assert attachments.prepare(utf8, folder).text == "# Заметки\nпривет"
    assert attachments.prepare(cp1251, folder).text == "старый текст"
    assert attachments.prepare(utf16, folder).text == "a;b\nя;ты"
    assert (folder / "notes.md").read_text(encoding="utf-8-sig") == "# Заметки\nпривет"  # a copy is kept


def test_long_text_is_cut(tmp_path: Path) -> None:
    source = tmp_path / "book.txt"
    source.write_text("слово " * 20_000, encoding="utf-8")
    item = attachments.prepare(source, tmp_path / "files")
    assert item.truncated and len(item.text) == attachments.MAX_TEXT_TOKENS * attachments.CHARS_PER_TOKEN
    assert item.tokens <= attachments.MAX_TEXT_TOKENS + 20


@pytest.mark.parametrize(("name", "data", "code"), [
    ("program.exe", b"MZ", "unsupported"),
    ("data.txt", b"\x00\x01binary\x00" * 10, "unsupported"),
    ("voice.mp3", b"ID3", "audio"),
    ("empty.txt", b"   \n", "empty"),
    ("broken.png", b"not an image", "unreadable"),
    ("broken.pdf", b"%PDF-1.4 garbage", "unreadable"),
])
def test_files_that_cannot_be_attached(tmp_path: Path, name: str, data: bytes, code: str) -> None:
    source = tmp_path / name
    source.write_bytes(data)
    with pytest.raises(AttachmentError) as error:
        attachments.prepare(source, tmp_path / "files")
    assert error.value.code == code


def test_pdf_and_word(tmp_path: Path) -> None:
    pdf = attachments.prepare(pdf_with_text(tmp_path / "report.pdf", "Hello PDF"), tmp_path / "files")
    assert pdf.kind == "document" and "Hello PDF" in pdf.text and "[page 1]" in pdf.text
    import docx

    document = docx.Document()
    document.add_paragraph("Сценарий ролика")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text, table.rows[0].cells[1].text = "Кадр 1", "маяк"
    document.save(tmp_path / "plan.docx")
    word = attachments.prepare(tmp_path / "plan.docx", tmp_path / "files")
    assert word.text == "Сценарий ролика\nКадр 1 | маяк"


def test_documents_without_the_optional_packages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import fails
    monkeypatch.setitem(sys.modules, "docx", None)
    for name in ("a.pdf", "b.docx"):
        (tmp_path / name).write_bytes(b"x")
        with pytest.raises(AttachmentError) as error:
            attachments.prepare(tmp_path / name, tmp_path / "files")
        assert error.value.code == "needs_docs"


def test_video_gives_evenly_spaced_frames(tmp_path: Path) -> None:
    import av

    source = tmp_path / "clip.mp4"
    with av.open(str(source), "w") as container:
        stream = container.add_stream("libx264", rate=10)
        stream.width, stream.height, stream.pix_fmt = 64, 48, "yuv420p"
        for i in range(60):  # 6 seconds, brightness grows frame by frame
            frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), i * 4, np.uint8), format="rgb24")
            container.mux(stream.encode(frame))
        container.mux(stream.encode())
    item = attachments.prepare(source, tmp_path / "files")
    assert item.kind == "video" and len(item.files) == attachments.VIDEO_FRAMES
    levels = [np.asarray(Image.open(tmp_path / "files" / f)).mean() for f in item.files]
    assert levels == sorted(levels) and levels[-1] - levels[0] > 120  # from the start to the end


def test_message_content(tmp_path: Path) -> None:
    folder = tmp_path / "files"
    folder.mkdir()
    Image.new("RGB", (8, 8)).save(folder / "pic.jpg")
    note = Attachment("notes.txt", "text", ["notes.txt"], "текст файла", 10)
    picture = Attachment("pic.png", "image", ["pic.jpg"], tokens=10)
    assert attachments.message_content("вопрос", [], folder) == "вопрос"
    text_only = attachments.message_content("вопрос", [note], folder)
    assert text_only == "File “notes.txt”:\n```\nтекст файла\n```\n\nвопрос"
    parts = attachments.message_content("что здесь?", [picture, note], folder)
    assert [p["type"] for p in parts] == ["image_url", "text"]
    url = parts[0]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == (folder / "pic.jpg").read_bytes()
    assert parts[1]["text"].endswith("что здесь?") and "текст файла" in parts[1]["text"]
    assert isinstance(attachments.message_content("x", [picture], folder, with_images=False), str)
