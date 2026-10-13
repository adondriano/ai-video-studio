# Production Workflow

This file is injected into every LLM call alongside `Mastery.md`. It defines the pipeline, the gates, and the non-negotiable rules.

## Stage 0 — Intake
- Ask for the **ad name** and the **project folder** (default: `projects/<slug>` next to the app).
- Everything the project produces (brief, package, prompts, assets, EDL) lives in that folder, mirrored in `project.json`.

## Stage 1 — Brief → Creative Package
Input: pasted script or ad brief + optional reference upload + style tag (UGC, Claymation, Pixar-like, Cinematic, Anime, Noir, Paper-craft, custom…).
Context injected: `Mastery.md` + `Workflow.md` + reference description.
Output — **one approval box** with sections:
1. **Storyboard** — scenes SC-01… with beat, visual, VO line, duration.
2. **Script & CTA Split** — VO per scene and the CTA block isolated (action + reason + urgency).
3. **Shot List** — shot size, lens, movement, notes per scene.
4. **Characters** — minted with stable IDs (`CHAR_X`) and mint prompts.
5. **Settings / Environments** — minted with stable IDs (`ENV_X`) and mint prompts.

Gate: each section has an Approve checkbox. Unchecked ⇒ revision comment required. All checked ⇒ Approve. Otherwise ⇒ Revise, and the loop repeats until 100% approved. Revision comments are applied as *targeted* changes — never regenerate sections that were already approved.

## Stage 2 — Image Generation
- LLM writes the image prompt per scene **from the approved package only**.
- Every generated asset gets a locked ID: `IMG-SC-##-rN`, recorded in the **Scene Marker** (`scene_marker.json` in the project folder) — IDs are never lost or renumbered.
- **When connected via MCP to Higgsfield: ALWAYS use `@elements` references** for every minted character/environment in every prompt (e.g. `@CHAR_MAYA @ENV_LOFT`). No exceptions.
- After generation, the LLM runs a QC pass per image (abnormalities, identity drift, text legibility) and attaches its verdict to the card.
- Each image is revisable (comment → refined prompt → new rev) and rerollable. Approved images are never regenerated.

## Stage 3 — Video Generation
- LLM writes the **motion prompt** per scene from the approved still + package.
- Generation runs in **batches of 4 scenes**. The next batch only starts after the current batch is 100% approved.
- Per clip: Approve checkbox, **Reroll**, and a revision box (comment → refined motion prompt → new rev `CLIP-SC-##-rN`).
- After a batch is approved: offer **Download clips (zip)**. After the final batch: ask who edits — the user (hand off zip + scene marker) or the AI.

## Stage 4 — Final Edit (AI)
- Prerequisite skill: **claude-remotion-skill** — check `skills/claude-remotion-skill/`; if missing, show the install command and block until installed (Demo mode may simulate the render).
- The edit must follow `Mastery.md` pacing/editing rules and use the **Scene Marker** as the single source of truth for asset mapping.
- Inputs to the editor: approved clips + Scene Marker + approved package (VO lines, CTA split, durations).
- Outputs into `edit/`: `edl.json` (edit decision list), `final_preview.*`, `FINAL_EDIT_NOTES.md` summarizing choices against Mastery rules.

## Stage 5 — Archive
- Project folder keeps: brief + package versions, prompts, assets by ID, scene marker, EDL, notes. Nothing is deleted; every revision bumps the rev counter.

## Global Rules
- Mastery.md is read before every creative call and updated after every analysis.
- IDs (`SC`, `IMG`, `CLIP`, `CHAR`, `ENV`) are immutable once minted.
- Revisions are surgical: touch only what a comment targets.
- In Demo mode all generation is local (placeholder painter/GIF renderer); in Live mode the same contracts call OpenAI/Anthropic, ElevenLabs, Higgsfield/HeyGen.
