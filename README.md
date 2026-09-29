# SnapReel 🎬

SnapReel is a fully automated, local-first application for generating short-form videos (Reels, TikToks, Shorts) and high-quality images directly from your computer. It intelligently orchestrates a pipeline of local AI models to write scripts, generate voiceovers, create dynamic visuals, and assemble everything into a final polished video with subtitles. 

Everything runs completely locally (except for TTS) and keeps your data private.

## ✨ Features

- **Video Factory**: Enter a topic, and SnapReel will write a script using local LLMs (like Qwen 2.5), generate an edge-tts voiceover, create visuals, add subtitles, and stitch it all together.
- **Image Studio**: A standalone workspace for generating images and editing with IP-Adapter/ControlNet. Supports Diffusers and ComfyUI backends.
- **AI Video Clips**: Generate actual video clips (e.g., LTX-Video, Wan 2.1) using the headless ComfyUI engine, or fall back to static images with Ken Burns zoom effects.
- **Hardware Auto-Tuning**: Built-in hardware profiler automatically detects your CPU, RAM, and GPU/VRAM to apply memory optimizations (like CPU offloading and xformers) for machines with less than 8GB of VRAM.
- **Modern UI**: A user-friendly PySide6 interface with a dark theme, progress dashboard, and a settings panel for model management.

## 🚀 How to Download and Run

For Windows users, getting started is extremely easy. You do not need to install Python or know how to use the command line.

1. Go to the [Releases](https://github.com/Rolo909/SnapReel/releases) page.
2. Download the latest `SnapReel-Windows-Portable.zip`.
3. Extract the ZIP file to a folder on your computer (for example, `C:\SnapReel`).
4. Double-click **`SnapReel.exe`** to launch the application.

*Note: On your first launch, the built-in Setup Wizard will automatically detect missing models (like your local LLM, diffusion models, and whisper) and download them for you.*

## 💻 Running from Source

If you want to modify the code or run SnapReel from source, follow these steps:

### Prerequisites
- Python 3.10 - 3.14
- C++ Build Tools (required on Windows to compile `llama-cpp-python`)
- [FFmpeg](https://ffmpeg.org/) installed and added to your system `PATH`

### Setup
We recommend using [uv](https://github.com/astral-sh/uv) or standard `pip`:

```bash
# Clone the repository
git clone https://github.com/Rolo909/SnapReel.git
cd SnapReel

# Install dependencies (consider using a virtual environment)
pip install -e .
```

### Launch
```bash
python -m snapreel
```

## 🛠️ Building the Executable

To build the portable ZIP yourself:
```bash
pip install nuitka
python scripts/build_release.py
```
This will compile the application and package it into `dist/SnapReel-Windows-Portable.zip`.

## 📄 License
MIT License
