# Local helper programs

## Voiceover speech-to-text

```bash
python local_programs/transcribe_voiceover.py path/to/voiceover.mp3
```

The app already uses this logic internally during **Brief → Process** when you
upload a voiceover file.

### For real offline transcription
Install Whisper locally:

```bash
pip install openai-whisper
```

Then the same helper automatically switches from filename fallback to local STT.

### Zero-install fallback
If you don't want Whisper yet, drop a sidecar text file beside the audio:

```text
voiceover.mp3
voiceover.txt
```

The app will use the text file as the transcript for captions and package generation.
