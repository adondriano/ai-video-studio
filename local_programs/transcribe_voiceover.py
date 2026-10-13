#!/usr/bin/env python3
"""
Standalone local python program for voiceover transcription.

Usage:
  python local_programs/transcribe_voiceover.py path/to/voice.mp3

Output:
  {"text": "...", "source": "whisper:base|sidecar:...|filename-fallback"}

Tips:
- For real local transcription, install Whisper:
    pip install openai-whisper
- Or place a text file beside the audio with the same filename:
    my-voice.mp3 + my-voice.txt
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.stt import transcribe_audio


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "audio path required"}))
        raise SystemExit(1)
    text, source = transcribe_audio(sys.argv[1])
    print(json.dumps({"text": text, "source": source}))


if __name__ == "__main__":
    main()
