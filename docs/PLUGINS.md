# Плагины движков Tvorka

Плагин добавляет в Tvorka новый **движок** — код, который загружает модель и создаёт результат.
Так можно подключить модель, которую встроенные движки (diffusers, Silero, transformers-TTS, Edge) не умеют запускать.

## Где лежат

`<папка данных>/plugins/*.py` — на Windows `%APPDATA%\Tvorka\plugins\`.
Каждый файл импортируется при запуске приложения. Файлы, начинающиеся с `_`, пропускаются.

> Плагин — обычный Python-код с правами приложения. Tvorka загружает плагины **только** из этой папки
> и никогда — из удалённого каталога или интернета. Кладите сюда только код, которому доверяете.

## Минимальный пример

`plugins/sine_tone.py` — «модель речи», которая вместо речи выдаёт тон, длина которого зависит от длины текста:

```python
import time

import numpy as np

from tvorka.core.jobs import Job, Result, output_file
from tvorka.engines import media
from tvorka.engines.base import Context, Engine, EngineError, register_engine


class SineToneEngine(Engine):
    def load(self, ctx: Context) -> None:
        # Тяжёлые импорты (torch и т. п.) делайте здесь, а не на уровне модуля.
        ctx.progress(1.0, "ready")

    def generate(self, job: Job, ctx: Context) -> list[Result]:
        if not job.prompt.strip():
            raise EngineError("empty_text")
        started = time.perf_counter()
        rate = 24000
        seconds = min(10.0, 0.06 * len(job.prompt))
        t = np.arange(int(rate * seconds)) / rate
        samples = 0.3 * np.sin(2 * np.pi * 440 * t)
        ctx.check()  # бросает Cancelled, если пользователь нажал «Отмена»
        path = output_file(ctx.settings.output_path(), "speech", job.get("format", "wav"))
        media.write_audio(samples, rate, path)
        return [Result.make(job, path, self.spec.name, time.perf_counter() - started,
                            duration=round(seconds, 2), sample_rate=rate)]


register_engine("sine_tone", SineToneEngine)
```

Чтобы движком можно было пользоваться, нужна модель, которая на него ссылается: добавьте запись
в `<папка данных>/user_models.json` (это список):

```json
[{"id": "me/sine", "name": "Sine tone", "kind": "speech", "engine": "sine_tone",
  "source": "online", "memory": {}, "license": "MIT"}]
```

`source: "online"` означает «ничего не скачивать». Для движка с весами на диске укажите
`"source": "local", "path": "D:/models/my-model"` — путь вернёт `ModelStore.location()` / `Engine.model_path(ctx)`.

## Контракт движка

| Что | Где | Обязанности |
|---|---|---|
| `__init__(spec, plan)` | наследуется | `self.spec` — `ModelSpec`, `self.plan` — план памяти советника (`device`, `mode`, `dtype`) |
| `load(ctx)` | обязателен | загрузить модель по плану; сообщать прогресс `ctx.progress(0..1, "load")` |
| `generate(job, ctx)` | обязателен | выполнить `Job`, сохранить файлы через `output_file`, вернуть список `Result` |
| `unload()` | по желанию | освободить память (по умолчанию — сборка мусора и очистка кэша CUDA) |

- Прогресс: `ctx.progress(доля, код_стадии)`; коды стадий — `import`, `load`, `ready`, `steps`, `save`, `speech`, `encode`.
- Отмена: регулярно вызывайте `ctx.check()` (или проверяйте `ctx.cancelled`).
- Ошибки для пользователя: `EngineError(код, подробности)`; коды — в `Task_plan.md`, раздел 3.2.
  Любое другое исключение покажется как «непредвиденная ошибка», а нехватка памяти — как `out_of_memory`.
- Модель остаётся загруженной между задачами; `load` вызывается заново только при смене модели или плана.

Если плагин не загрузился (ошибка в коде или `register_engine` не вызван), приложение продолжает работу,
а причина видна в журнале `<папка данных>/logs/tvorka.log`.
