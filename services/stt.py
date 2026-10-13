"""
stt.py — local speech-to-text helper for voiceover-first workflows.

Priority order:
1. If a sibling .txt/.md/.srt file exists, use it as the transcript.
2. If `whisper` is installed locally, run offline transcription.
3. Fallback: derive a readable placeholder transcript from the audio filename.

This keeps Demo mode dependency-light while still letting power users install a
real local STT engine later with no code changes.
"""

import os
import re


def _clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def _from_sidecar(audio_path):
    root, _ = os.path.splitext(audio_path)
    for ext in (".txt", ".md", ".srt"):
        p = root + ext
        if os.path.exists(p):
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return _clean(f.read()), f"sidecar:{os.path.basename(p)}"
    return "", ""


def _from_whisper(audio_path):
    try:
        import whisper  # type: ignore
    except Exception:
        return "", ""
    try:
        model = whisper.load_model("base")
        out = model.transcribe(audio_path, fp16=False)
        text = _clean(out.get("text", ""))
        return text, "whisper:base"
    except Exception:
        return "", ""


def _from_filename(audio_path):
    name = os.path.splitext(os.path.basename(audio_path))[0]
    name = re.sub(r"^\d+_", "", name)
    text = re.sub(r"[_\-]+", " ", name)
    text = _clean(text)
    if len(text) < 8:
        text = "Voiceover uploaded. Install whisper locally or place a .txt sidecar next to the audio file for exact captions."
    else:
        text = text[0].upper() + text[1:] + "."
    return text, "filename-fallback"


def transcribe_audio(audio_path):
    text, source = _from_sidecar(audio_path)
    if text:
        return text, source
    text, source = _from_whisper(audio_path)
    if text:
        return text, source
    return _from_filename(audio_path)
