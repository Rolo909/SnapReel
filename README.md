# SnapReel 🎬

*🌍 [English](#english) | 🇷🇺 [Русский](#русский)*

---

<a name="english"></a>
## 🌍 English

SnapReel is a fully automated, local-first application for generating short-form videos (Reels, TikToks, Shorts) and high-quality images directly from your computer. It intelligently orchestrates a pipeline of local AI models to write scripts, generate voiceovers, create dynamic visuals, and assemble everything into a final polished video with subtitles. 

Everything runs completely locally (except for TTS) and keeps your data private.

### ✨ Features

- **Video Factory**: Enter a topic, and SnapReel will write a script using local LLMs (like Qwen 2.5), generate an edge-tts voiceover, create visuals, add subtitles, and stitch it all together.
- **Image Studio**: A standalone workspace for generating images and editing with IP-Adapter/ControlNet. Supports Diffusers and ComfyUI backends.
- **AI Video Clips**: Generate actual video clips (e.g., LTX-Video, Wan 2.1) using the headless ComfyUI engine, or fall back to static images with Ken Burns zoom effects.
- **Hardware Auto-Tuning**: Built-in hardware profiler automatically detects your CPU, RAM, and GPU/VRAM to apply memory optimizations (like CPU offloading and xformers) for machines with less than 8GB of VRAM.
- **Modern UI**: A user-friendly PySide6 interface with a dark theme, progress dashboard, and a settings panel for model management.

### 🚀 How to Download and Run

For Windows users, getting started is extremely easy. You do not need to install Python or know how to use the command line.

1. Go to the [Releases](https://github.com/Rolo909/SnapReel/releases) page.
2. Download the latest `SnapReel-Windows-Portable.zip`.
3. Extract the ZIP file to a folder on your computer (for example, `C:\SnapReel`).
4. Double-click **`SnapReel.exe`** to launch the application.

*Note: On your first launch, the built-in Setup Wizard will automatically detect missing models (like your local LLM, diffusion models, and whisper) and download them for you.*

### 💻 Running from Source

If you want to modify the code or run SnapReel from source, follow these steps:

**Prerequisites:**
- Python 3.10 - 3.14
- C++ Build Tools (required on Windows to compile `llama-cpp-python`)
- [FFmpeg](https://ffmpeg.org/) installed and added to your system `PATH`

**Setup:**
We recommend using a virtual environment:

```bash
# Clone the repository
git clone https://github.com/Rolo909/SnapReel.git
cd SnapReel

# Create and activate a virtual environment
# On Windows:
python -m venv .venv
.\.venv\Scripts\activate
# On Linux/macOS:
# python3 -m venv .venv
# source .venv/bin/activate

# Install the project and dependencies (including GPU support)
python -m pip install -e ".[gpu]"
```

**Launch:**
Make sure your virtual environment is activated, then run:
```bash
python -m snapreel
```

### 🛠️ Building the Executable

To build the portable ZIP yourself:
```bash
pip install nuitka
python scripts/build_release.py
```
This will compile the application and package it into `dist/SnapReel-Windows-Portable.zip`.

---

<a name="русский"></a>
## 🇷🇺 Русский

SnapReel — это полностью автоматизированное локальное приложение для создания коротких видеороликов (Reels, TikToks, Shorts) и высококачественных изображений прямо на вашем компьютере. Программа объединяет различные локальные ИИ-модели для написания сценариев, генерации озвучки, создания визуального ряда и автоматического монтажа готового видео с субтитрами.

Все вычисления происходят локально (за исключением генерации голоса), что гарантирует полную приватность ваших данных.

### ✨ Возможности

- **Фабрика видео (Video Factory)**: Просто введите тему, и SnapReel напишет сценарий с помощью локальной нейросети (например, Qwen 2.5), озвучит его, сгенерирует визуальный ряд, наложит субтитры и склеит всё в готовый ролик.
- **Студия изображений (Image Studio)**: Отдельный раздел для генерации картинок и работы с IP-Adapter/ControlNet. Поддерживает движки Diffusers и ComfyUI.
- **ИИ-Видео**: Создавайте полноценные видеофрагменты (например, с помощью моделей LTX-Video или Wan 2.1) через встроенный движок ComfyUI. Если железо не позволяет, программа автоматически использует статические картинки с эффектом Кена Бернса.
- **Автоматическая настройка железа**: Встроенный профилировщик автоматически определяет ваш процессор, оперативную память и объем видеопамяти (VRAM). Если у вас меньше 8 ГБ VRAM, SnapReel сам включит необходимые оптимизации (выгрузку в RAM, xformers и т.д.).
- **Современный интерфейс**: Удобный графический интерфейс на базе PySide6 с тёмной темой, дашбордом прогресса и панелью настроек.

### 🚀 Как скачать и запустить

Если вы пользуетесь Windows, начать работу невероятно просто. Вам не нужно устанавливать Python или разбираться в командной строке.

1. Перейдите на страницу [Releases](https://github.com/Rolo909/SnapReel/releases).
2. Скачайте свежий архив `SnapReel-Windows-Portable.zip`.
3. Распакуйте архив в любую удобную папку на вашем компьютере (например, `C:\SnapReel`).
4. Дважды кликните по файлу **`SnapReel.exe`**, чтобы запустить программу.

*Примечание: При первом запуске встроенный мастер настройки автоматически проверит наличие нужных ИИ-моделей (LLM, модели генерации картинок и Whisper) и предложит их скачать.*

### 💻 Запуск из исходного кода

Если вы хотите изменить код программы или просто запустить её из исходников:

**Требования:**
- Python 3.10 - 3.14
- Инструменты сборки C++ (нужны на Windows для компиляции `llama-cpp-python`)
- Установленный [FFmpeg](https://ffmpeg.org/), добавленный в системный `PATH`

**Установка:**
Крайне рекомендуется использовать виртуальное окружение:

```bash
# Клонируем репозиторий
git clone https://github.com/Rolo909/SnapReel.git
cd SnapReel

# Создаем и активируем виртуальное окружение
# На Windows:
python -m venv .venv
.\.venv\Scripts\activate
# На Linux/macOS:
# python3 -m venv .venv
# source .venv/bin/activate

# Устанавливаем проект и его зависимости (включая зависимости для GPU)
python -m pip install -e ".[gpu]"
```

**Запуск:**
Убедитесь, что виртуальное окружение активировано, затем выполните:
```bash
python -m snapreel
```

### 🛠️ Сборка собственного .exe

Чтобы собрать портативный ZIP-архив самостоятельно:
```bash
pip install nuitka
python scripts/build_release.py
```
Этот скрипт скомпилирует приложение и упакует его в `dist/SnapReel-Windows-Portable.zip`.

---

## 📄 License / Лицензия
MIT License
