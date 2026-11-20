"""User-facing texts for the machine codes used by the core (Task_plan.md, section 3.2).

Every error text says what happened and what to do about it.
"""

from __future__ import annotations

from typing import Any

from tvorka.i18n import tr


def _unknown() -> str:
    return tr("Something went wrong. Details are in the log (Settings → Open log).")


def engine_error(code: str, detail: str = "") -> str:
    texts = {
        "not_installed": tr("The model is not downloaded yet. Download it on the Models page."),
        "load_failed": tr("The model could not be loaded. Its files may be damaged — "
                          "delete it on the Models page and download it again."),
        "cuda_unavailable": tr("The graphics card is not available to PyTorch. Check the diagnostics in "
                               "Settings → This computer, or switch to the CPU-only mode."),
        "reference_unsupported": tr("This model cannot use a reference in this mode. "
                                    "Choose another reference mode or remove the reference."),
        "reference_unreadable": tr("The reference image could not be opened. Use a PNG, JPG or WebP file."),
        "needs_reference": tr("This model needs a reference image as the first frame. "
                              "Add one and try again."),
        "ip_adapter_failed": tr("The style adapter could not be loaded. Check the internet connection — "
                                "it is downloaded on first use."),
        "lora_unsupported": tr("This model does not support LoRA. Remove the LoRA or pick another model."),
        "lora_failed": tr("The LoRA could not be attached. Make sure it was made for this model family."),
        "empty_text": tr("There is nothing to read aloud. Enter some text."),
        "unsupported": tr("This model type is not supported yet."),
        "edge_missing": tr("The online voice component is not installed. Reinstall Tvorka "
                           "or choose a local voice model."),
        "network": tr("No connection to the service. Check the internet connection and try again."),
        "model_missing": tr("The model is no longer in the list. Pick another model."),
        "does_not_fit": tr("This computer cannot run the model. The reason is shown under the model name."),
        "out_of_memory": tr("Not enough video memory. Lower the resolution or choose the "
                            "“Low memory” mode in Settings."),
        "no_sound": tr("There is no sound in this file."),
        "unreadable": tr("The sound could not be read. The file may be damaged."),
        "failed": _unknown(),
    }
    return texts.get(code, _unknown())


def llm_error(code: str) -> str:
    """Why a chat answer failed (``LlmError`` codes, ``ChatWorker``)."""
    texts = {
        "out_of_memory": tr("Not enough memory for this chat model. Close other programs, choose a shorter "
                            "conversation memory or a smaller model."),
        "load_failed": tr("The chat model could not be loaded. Its file may be damaged — delete it on the "
                          "Models page and download it again."),
        "unsupported": tr("This version of the chat engine cannot run this model."),
        "timeout": tr("The chat model took too long to load. Try again or choose a smaller model."),
        "crashed": tr("The chat engine stopped unexpectedly. Send the message again — it will restart. "
                      "Details are in the log."),
        "not_running": tr("The chat engine stopped unexpectedly. Send the message again — it will restart. "
                          "Details are in the log."),
        "connection": tr("The chat engine stopped unexpectedly. Send the message again — it will restart. "
                         "Details are in the log."),
        "context_overflow": tr("The conversation no longer fits in the model's memory. Start a new chat or "
                               "choose a longer memory in the chat settings."),
    }
    return texts.get(code, _unknown())


def attachment_error(code: str, name: str = "") -> str:
    """Why a file could not be attached (``AttachmentError`` codes)."""
    texts = {
        "unsupported": tr("“{name}” cannot be attached. Pictures, text and code, PDF, Word and video "
                          "files are supported."),
        "unreadable": tr("“{name}” could not be read. The file may be damaged."),
        "empty": tr("There is no text in “{name}”. If it is a scan, attach it as a picture."),
        "needs_docs": tr("Reading PDF and Word files needs a component Tvorka does not have yet. "
                         "Reinstall Tvorka from the latest release, or copy the text into the message."),
        "audio": tr("To understand “{name}”, Tvorka needs a speech recognition model. Download Whisper "
                    "on the Models page (Speech recognition)."),
        "silent": tr("No speech was found in “{name}”."),
    }
    return texts.get(code, _unknown()).format(name=name)


def stage(code: str) -> str:
    texts = {
        "import": tr("Starting the engine…"),
        "load": tr("Loading the model…"),
        "place": tr("Placing the model in memory…"),
        "ready": tr("Model ready"),
        "steps": tr("Generating…"),
        "save": tr("Saving…"),
        "encode": tr("Encoding the video…"),
        "upscale": tr("Enlarging the image…"),
        "speech": tr("Synthesizing speech…"),
        "download_extra": tr("Downloading additional files…"),
        "retry_low_memory": tr("Not enough memory — retrying in a leaner mode…"),
    }
    return texts.get(code, "")


def verdict(code: str) -> str:
    texts = {
        "great": tr("Runs great"),
        "good": tr("Runs well"),
        "slow": tr("Slow"),
        "very_slow": tr("Very slow"),
        "no": tr("Will not run"),
    }
    return texts.get(code, code)


def advisor_note(code: str, params: dict[str, Any]) -> str:
    p = dict(params)
    if "parts" in p:  # component names are technical: show what they are
        names = {"text_encoder": tr("text encoder"), "text_encoder_2": tr("second text encoder"),
                 "transformer": tr("main network"), "unet": tr("main network"), "vae": tr("image decoder")}
        p["parts"] = ", ".join(names.get(part.strip(), part.strip()) for part in str(p["parts"]).split(","))
    texts = {
        "online": tr("Works over the internet: the text is sent to Microsoft."),
        "torch_cpu_build": tr("PyTorch without graphics card support is installed. "
                              "Install the GPU build in Settings → This computer."),
        "gpu_unsupported": tr("{gpu} is not supported yet; the model will run on the processor."),
        "disk": tr("Not enough disk space: {need:.1f} GB needed, {have:.1f} GB free."),
        "cpu_only": tr("Runs on the processor — expect minutes instead of seconds."),
        "ram": tr("Needs about {need:.0f} GB of RAM, this computer has {have:.0f} GB."),
        "ram_swap": tr("Needs about {need:.0f} GB of RAM out of {have:.0f} GB — "
                       "Windows will use the page file, which is much slower."),
        "vram": tr("Needs at least {need:.1f} GB of video memory, the graphics card has {have:.1f} GB."),
        "hybrid": tr("Part of the model ({parts}) is streamed from RAM to fit the graphics card."),
        "stream": tr("The model is streamed into video memory piece by piece: it fits, but slowly."),
        "offload": tr("Model parts take turns on the graphics card: a little slower, much less memory."),
        "forced_risky": tr("The selected performance mode needs more video memory than available; "
                           "generation may be very slow."),
        "above_native": tr("The resolution is above what the model was trained on; "
                           "details may repeat."),
        "vram_busy": tr("Other programs occupy video memory ({free:.1f} GB free) — "
                        "close them for full speed."),
        "llm_partial": tr("{share} % of the model fits on the graphics card, the rest runs on the "
                          "processor — answers come slower."),
        "llm_cpu": tr("Answers are written by the processor: a few words per second."),
        "llm_moe": tr("The experts of {layers} of {total} layers stay in RAM, the rest is on the graphics "
                      "card: each word needs only a few experts."),
    }
    text = texts.get(code, "")
    try:
        return text.format(**p) if p else text
    except (KeyError, ValueError):
        return text


def hub_error(code: str) -> str:
    texts = {
        "gated": tr("Access to this model is restricted. Accept its license on the Hugging Face page "
                    "and enter your token in Settings."),
        "not_found": tr("The model was not found. Check the name or the link."),
        "network": tr("No connection to Hugging Face. Check the internet connection and try again."),
        "bad_id": tr("Enter the model as “author/name” or paste a link to its Hugging Face page."),
        "addon": tr("This is an add-on (LoRA, adapter or ControlNet), not a standalone model."),
        "unsupported": tr("Tvorka cannot run this kind of model yet."),
        "projector": tr("This file only lets a chat model see images (mmproj). "
                        "Choose the model file itself."),
        "checksum": tr("The downloaded file is damaged. Try downloading it again."),
        "disk": tr("Not enough disk space for the download. Free some space or choose another "
                   "models folder in Settings."),
        "failed": _unknown(),
    }
    return texts.get(code, _unknown())
