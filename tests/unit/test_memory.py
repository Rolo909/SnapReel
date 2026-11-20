"""The video memory arbiter: chat server and generation engine on one graphics card."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pytestqt")

from test_advisor import machine
from test_chat_worker import stub_command

from tvorka.core.advisor import LlmPlan
from tvorka.core.catalog import ModelSpec
from tvorka.core.jobs import History, Job
from tvorka.core.memory import VideoMemory
from tvorka.core.settings import Settings
from tvorka.core.store import ModelStore
from tvorka.engines.base import Engine, register_engine
from tvorka.workers.chat import ChatWorker, Launch
from tvorka.workers.generation import GenerationWorker


class Owner:
    """A holder whose model is busy for ``busy_s`` after ``use()``."""

    def __init__(self, memory: VideoMemory, name: str) -> None:
        self.name, self.memory = name, memory
        self.busy = threading.Lock()
        self.unloads = 0
        memory.register(name, self.release)

    def release(self, cancelled) -> bool:
        while not self.busy.acquire(timeout=0.05):
            if cancelled():
                return False
        try:
            self.unloads += 1
        finally:
            self.busy.release()
        return True


def test_both_stay_when_they_fit_together() -> None:
    memory = VideoMemory(7.2)
    chat, image = Owner(memory, "chat"), Owner(memory, "generation")
    assert memory.claim("chat", "qwen", 3.0) and memory.claim("generation", "sd", 3.5)
    assert (chat.unloads, image.unloads) == (0, 0)
    assert memory.holders() == {"chat": ("qwen", 3.0), "generation": ("sd", 3.5)}


def test_the_other_model_makes_way() -> None:
    memory = VideoMemory(7.2)
    chat, image = Owner(memory, "chat"), Owner(memory, "generation")
    memory.claim("chat", "qwen", 5.0)
    memory.claim("generation", "sd", 3.5)
    assert chat.unloads == 1 and memory.holders() == {"generation": ("sd", 3.5)}
    memory.claim("generation", "sd", 3.5)  # same model again: nobody else to move
    memory.claim("chat", "qwen", 5.0)
    assert image.unloads == 1 and memory.holders() == {"chat": ("qwen", 5.0)}


def test_processor_models_and_machines_without_a_card_share_nothing() -> None:
    memory = VideoMemory(7.2)
    chat, _image = Owner(memory, "chat"), Owner(memory, "generation")
    memory.claim("chat", "qwen", 0.0)  # on the processor
    memory.claim("generation", "sd", 7.0)
    assert chat.unloads == 0
    no_card = VideoMemory(0.0)
    voice = Owner(no_card, "chat")
    no_card.claim("chat", "a", 5.0)
    no_card.claim("generation", "b", 9.0)
    assert voice.unloads == 0


def test_waiting_for_a_busy_owner_can_be_cancelled() -> None:
    memory = VideoMemory(7.2)
    chat, _image = Owner(memory, "chat"), Owner(memory, "generation")
    memory.claim("chat", "qwen", 5.0)
    chat.busy.acquire()  # an answer is being written
    stop = time.monotonic() + 0.2
    assert not memory.claim("generation", "sd", 4.0, lambda: time.monotonic() > stop)
    assert memory.holders() == {"chat": ("qwen", 5.0)}  # nothing changed
    chat.busy.release()
    assert memory.claim("generation", "sd", 4.0) and chat.unloads == 1


def test_claims_from_two_threads_do_not_deadlock() -> None:
    memory = VideoMemory(7.2)
    owners = {name: Owner(memory, name) for name in ("chat", "generation")}
    done = []

    def work(name: str) -> None:
        for _ in range(20):
            memory.claim(name, name, 5.0)  # claim first, then take the own lock — like the workers
            with owners[name].busy:
                time.sleep(0.005)
        done.append(name)

    threads = [threading.Thread(target=work, args=(n,)) for n in owners]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert sorted(done) == ["chat", "generation"]


# ------------------------------------------------------------------ the real workers on stand-ins
events: list[str] = []


class FakeGpuEngine(Engine):
    def load(self, ctx) -> None:
        events.append(f"load {self.spec.id}")

    def generate(self, job, ctx) -> list:
        return []

    def unload(self) -> None:
        events.append(f"unload {self.spec.id}")


register_engine("test_gpu", FakeGpuEngine)


@pytest.fixture
def workers(tmp_path: Path, qtbot):
    events.clear()
    settings = Settings(models_dir=str(tmp_path / "m"), output_dir=str(tmp_path / "o"))
    generation = GenerationWorker(settings, None, ModelStore(settings), History(tmp_path / "h.json"))
    chat = ChatWorker(tmp_path / "server.log", stub_command, ready_timeout_s=30)
    memory = VideoMemory(8.0 - 0.8)
    generation.attach_memory(memory)
    chat.attach_memory(memory)
    generation.set_hardware(machine(8))
    chat.model_changed.connect(lambda m: events.append(f"chat {m or '-'}"))
    generation.start()
    chat.start()
    yield generation, chat, memory
    chat.shutdown()
    chat.wait(10_000)
    generation.shutdown()


def image_model(vram: float) -> ModelSpec:
    return ModelSpec(id=f"test/image-{vram}", name="Image", kind="image", engine="test_gpu",
                     memory={"unet": vram}, act_gb=0.3, native=[512, 512])


def picture(generation: GenerationWorker, spec: ModelSpec, qtbot, monkeypatch) -> None:
    generation._catalog = type("C", (), {"get": staticmethod(lambda _id: spec)})()
    with qtbot.waitSignal(generation.job_finished, timeout=20_000):
        generation.submit(Job("image", spec.id, "a lighthouse"))


def answer(chat: ChatWorker, vram: float, qtbot) -> None:
    launch = Launch("test/chat", Path("llama-server"), Path("m.gguf"), LlmPlan("Q4_K_M", 8192, 32, True),
                    vram_gb=vram)
    with qtbot.waitSignal(chat.finished, timeout=20_000):
        chat.submit(launch, [{"role": "user", "content": "hi"}], {})


def test_chat_then_picture_then_chat(workers, qtbot, monkeypatch) -> None:
    generation, chat, memory = workers
    answer(chat, 5.0, qtbot)
    picture(generation, image_model(4.0), qtbot, monkeypatch)
    qtbot.waitUntil(lambda: "chat -" in events, timeout=5000)
    assert events.index("chat -") < events.index("load test/image-4.0")  # room first, then the model
    assert chat.loaded_model == "" and memory.holders()["generation"][0] == "test/image-4.0"
    answer(chat, 5.0, qtbot)  # the chat model comes back, the image model makes way
    assert events[-2:] == ["unload test/image-4.0", "chat test/chat"]
    assert generation.loaded_model == "" and set(memory.holders()) == {"chat"}


def test_no_reload_when_both_fit(workers, qtbot, monkeypatch) -> None:
    generation, chat, memory = workers
    answer(chat, 2.0, qtbot)
    picture(generation, image_model(2.0), qtbot, monkeypatch)
    answer(chat, 2.0, qtbot)
    assert events == ["chat test/chat", "load test/image-2.0"]  # loaded once each, nothing unloaded
    assert set(memory.holders()) == {"chat", "generation"}



def test_a_model_that_failed_to_load_holds_nothing(workers, qtbot) -> None:
    _generation, chat, memory = workers
    launch = Launch("test/chat", Path("llama-server"), Path("broken.gguf"), LlmPlan("Q4_K_M", 8192, 32, True),
                    vram_gb=5.0)
    with qtbot.waitSignal(chat.failed, timeout=20_000):
        chat.submit(launch, [{"role": "user", "content": "hi"}], {})
    assert memory.holders() == {}


def test_budget_leaves_other_programs_their_memory() -> None:
    from tvorka.core.hardware import GpuInfo, Hardware
    from tvorka.gui.services import memory_budget

    def card(total: float, free: float) -> Hardware:
        gpus = (GpuInfo("RTX", "nvidia", total, free),)
        return Hardware("OS", "CPU", 6, 12, 16, 10, 100, gpus, machine(8).torch)

    assert memory_budget(card(8.0, 6.1)) == pytest.approx(6.1)  # the desktop and a browser hold 1.9 GB
    assert memory_budget(card(8.0, 7.9)) == pytest.approx(7.2)  # never right to the edge
    assert memory_budget(machine(None)) == 0.0
