# Framecraft — AI Video Production Studio

A local-first AI ad-production studio. It learns from winning ads you feed it
(written into a living **Mastery.md**), then uses that mastery to build ads
end-to-end: brief → storyboard/shot-list/character & environment minting →
image generation (with locked scene IDs) → batched video generation (4 at a time)
→ final edit (Remotion skill) — with approval gates and revision loops at every step.

**Zero API keys needed to try it.** Demo mode runs on built-in local python
generators. Live mode (OpenAI/Anthropic, ElevenLabs, Higgsfield/HeyGen) unlocks
in Settings once keys are saved.

## Quickstart (≈30 seconds)

```bash
# macOS / Linux
./run.sh
# Windows
run.bat

# — or manually —
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** — you land in Demo mode. The **Demo | Live**
switch is in the header; Live stays disabled until API keys are set.

## The tabs

- **Studio** — the production pipeline:
  1. **Brief** — name the ad, pick the project folder, paste a script/ad brief,
     set a style (UGC, Claymation, Pixar, Noir…), optionally upload a reference,
     and optionally upload a **voiceover/mp3**. *Process* hands brief + transcript
     + reference + **Mastery.md** + **Workflow.md** to the LLM and returns one
     **For Approval** box: Storyboard, Script & CTA split, Shot list, Character
     minting, Setting/Environment minting. The local STT helper lives at
     `local_programs/transcribe_voiceover.py`; if Whisper is installed locally it
     uses that, otherwise it falls back to a sidecar `.txt` or filename-derived transcript.
  2. **Approval** — each section has an Approve checkbox. Unchecked ⇒ revision
     comment box. All checked ⇒ *Approve All* (images then auto-generate);
     otherwise *Send Revisions* and the LLM surgically edits only those
     sections. Loop until 100%.
  3. **Images** — LLM writes image prompts and generates every scene. IDs are
     locked in the **Scene Marker** (`IMG-SC-01-r1`…). Every image gets an LLM
     QC review, Approve checkbox, **Reroll**, and a revision box. With
     Higgsfield connected via MCP, prompts always include **@elements** refs.
  4. **Videos** — motion prompts from approved stills, generated **4 scenes at
     a time**. Approve / reroll / revise per clip. After each batch: download
     the clips and approve the batch to fire the next 4. After the last batch:
     download everything, choose **self-edit** or **AI final edit**.
  5. **Final Edit** — checks `skills/claude-remotion-skill` (shows install
     command if missing), then *Begin Final Edit* sends the Scene Marker +
     Mastery.md to the editor. Demo simulates the render (EDL + preview + notes);
     Live requires the cloned skill.
- **Learn** — upload winning ads (stored in `./uploads`), hit **Process**: the
  LLM analyzes *why it worked* and *how to reuse it*, then consolidates the
  learnings into **Mastery.md** (old versions archived in `knowledge/history/`).
- **Knowledge** — read Mastery.md / Workflow.md; Mastery is versioned.
- **Settings** — Demo/Live prerequisites, providers per stage
  (LLM / Image / Video / Voice), API keys (stored only in `config.json`), and
  per-provider **local python** install notes + custom-script mode
  (contract: JSON in on stdin, `{"text": …}` out on stdout).

## Project folder layout

Every project lives in the folder you chose at creation:

```
project.json          # full state (stage, approvals, revisions, asset IDs)
reference/            # optional reference upload
images/SC-01.png …    # one still per scene (rev-encoded via IDs in project.json)
clips/SC-01.gif …     # demo preview clips (mp4s in Live mode)
edit/scene_marker.json# the single source of truth: SC ↔ IMG ↔ CLIP mapping
edit/edl.json         # edit decision list
edit/FINAL_EDIT_NOTES.md
edit/final_preview.gif
```

## Wiring Live providers

Text stages are fully implemented for **OpenAI** (`gpt-4o` default) and
**Anthropic** — save keys in Settings and flip to Live. Image/video/voice calls
have clean, documented stubs at `services/images.py:generate_live()`,
`services/video.py:generate_live()` — drop in the Higgsfield/HeyGen/ElevenLabs
HTTP calls there and the whole pipeline (batching, approvals, scene-marker,
@elements) keeps working unchanged.

## Install notes

```bash
python -m venv .venv && source .venv/bin/activate   # optional but nice
pip install -r requirements.txt                     # Flask, Pillow, requests
```

For the AI final edit (Live): `cd skills && git clone https://github.com/haidrrrry/claude-remotion-skill.git`
