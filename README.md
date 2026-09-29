# SnapReel 🎬

SnapReel is a fully automated, local-first application for generating short-form videos (Reels, TikToks, Shorts) from a simple text prompt. It orchestrates a pipeline of local AI models to write scripts, generate voiceovers, create visuals, and assemble everything into a final polished video with subtitles.

## ✨ Features
- **Local Script Generation**: Uses `llama-cpp-python` (e.g. Qwen 2.5) to write structured scenes and narration.
- **Dynamic Voiceovers**: Uses `edge-tts` to generate high-quality text-to-speech.
- **Visuals & Animations**: Uses `diffusers` (SDXL Turbo) for fast image generation and `FFmpeg` for Ken Burns zoom effects.
- **Automatic Subtitles**: Uses `faster-whisper` for precise transcription and `FFmpeg` for burning stylized ASS subtitles.
- **Modern Qt UI**: User-friendly PySide6 interface with dark theme, progress tracking, and i18n support.
- **Local & Private**: All heavy lifting (except TTS) happens directly on your machine.

## 🚀 Installation

### Prerequisites
- **Python 3.10 - 3.12**
- **C++ Build Tools** (Required on Windows for compiling `llama-cpp-python`)
- **FFmpeg** installed and added to your system `PATH`.

### Setup
We recommend using [uv](https://github.com/astral-sh/uv) or `pip` to install dependencies.

```bash
# Clone the repository
git clone https://github.com/Rolo909/SnapReel.git
cd SnapReel

# Create a virtual environment and install dependencies
pip install -e .
```

## 🧠 Model Configuration

SnapReel requires several AI models to function. When you first launch the application, the built-in **Model Setup Wizard** will automatically detect missing models and offer to download them to the `models/` directory.

Models used:
- **LLM**: `Qwen2.5-7B-Instruct-Q4_K_M.gguf` (Placed in `models/llm/`)
- **Whisper**: `large-v3` (Downloaded automatically by faster-whisper)
- **Diffusion**: `stabilityai/sdxl-turbo` (Downloaded automatically via HuggingFace hub)

You can customize the models used by editing the `.env` file or tweaking the settings in the UI.

## 🎮 Usage

Launch the application using Python:

```bash
python -m snapreel
```

1. **New Project**: Click "New Project" in the UI.
2. **Setup**: Enter your topic (e.g., "Facts about space"), choose a visual style, set the number of scenes, and optionally select background music.
3. **Generate**: Click "Generate Video".
4. **Progress**: The dashboard will show you the real-time progress of scenario generation, audio synthesis, visual rendering, and final assembly.
5. **Result**: Once finished, the video will be saved to the `output/` folder and can be previewed directly in the app.

## 🛠️ Building Executables

You can build a standalone executable for Windows so you don't need to run it via Python.

**For Development (PyInstaller):**
```bash
pip install pyinstaller
python scripts/build_dev.py
# The output will be in dist/snapreel/snapreel.exe
```

**For Release (Nuitka):**
```bash
pip install nuitka
python scripts/build_release.py
# The output will be in dist/__main__.dist/__main__.exe
```

*(Note: The models directory is intentionally excluded from the binary build to keep the executable size manageable. The app will download or expect models next to the executable).*

## 📄 License
MIT License
