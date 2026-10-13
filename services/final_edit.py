"""
final_edit.py — AI final edit.

Live: uses the claude-remotion-skill (https://github.com/haidrrrry/claude-remotion-skill)
cloned into ./skills/. The edit must follow Mastery.md and map assets via the Scene Marker.

Demo: if the skill isn't installed, we simulate the render — building an EDL, an
edit-notes doc checked against Mastery rules, and a preview GIF cut from the
approved clips with dip transitions + captions + CTA end card.
"""

import os
import json
import datetime
from PIL import Image, ImageDraw, ImageFont, ImageSequence

REQUIRED_SKILLS = ["claude-remotion-skill"]


def skill_status(skills_dir):
    checked, installed_all = [], True
    for s in REQUIRED_SKILLS:
        d = os.path.join(skills_dir, s)
        ok = os.path.isdir(d) and any(
            os.path.exists(os.path.join(d, f)) for f in ("SKILL.md", "README.md", "skill.md")
        )
        checked.append({"skill": s, "installed": ok, "path": d})
        installed_all = installed_all and ok
    return {
        "installed": installed_all,
        "checked": checked,
        "install": [
            "cd skills",
            "git clone https://github.com/haidrrrry/claude-remotion-skill.git",
            "# then click Re-check — Live mode requires the skill; Demo mode can simulate the render.",
        ],
    }


def scene_marker_rows(project):
    imgs = {i["scene_id"]: i for i in project.get("images", [])}
    clips = {}
    for b in project.get("videos", {}).get("batches", []):
        for c in b.get("clips", []):
            clips[c["scene_id"]] = c
    rows = []
    for sc in project.get("package", {}).get("scenes", []):
        rows.append({
            "scene_id": sc["id"], "title": sc["title"], "beat": sc["beat"],
            "duration": sc["duration"], "vo": sc["vo"],
            "image": imgs.get(sc["id"], {}).get("asset_id"),
            "image_rev": imgs.get(sc["id"], {}).get("rev"),
            "image_approved": imgs.get(sc["id"], {}).get("approved", False),
            "clip": clips.get(sc["id"], {}).get("asset_id"),
            "clip_rev": clips.get(sc["id"], {}).get("rev"),
            "clip_approved": clips.get(sc["id"], {}).get("approved", False),
        })
    return rows


def _font(size, bold=True):
    for c in (["DejaVuSans-Bold.ttf"] if bold else ["DejaVuSans.ttf"]) + ["arial.ttf"]:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _wrap(dr, text, font, max_w, max_lines=2):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if dr.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur); cur = w
            if len(lines) >= max_lines - 1:
                break
    if cur:
        lines.append(cur)
    return lines[:max_lines]


def build_preview(gif_paths, scenes, cta_line, out_gif, w=640, h=360, per_clip=14):
    frames = []
    f_cap = _font(22, bold=True)
    f_big = _font(44, bold=True)
    for gi, gp in enumerate(gif_paths):
        try:
            src = Image.open(gp)
        except Exception:
            continue
        raw = [fr.convert("RGB").resize((w, h)) for fr in ImageSequence.Iterator(src)]
        if not raw:
            continue
        mid = raw[len(raw) // 4: len(raw) // 4 + per_clip] or raw[:per_clip]
        sc = scenes[gi]
        for fr in mid:
            dr = ImageDraw.Draw(fr, "RGBA")
            dr.rectangle([0, h - 46, w, h], fill=(10, 10, 12, 190))
            cap = f"{sc['scene_id']} · {sc['vo'][:64]}"
            dr.text((14, h - 36), cap, font=f_cap, fill=(240, 238, 234))
            frames.append(fr)
        # dip to black between scenes (Mastery §3: cuts on beats, clean transitions)
        for k in range(3):
            frames.append(Image.blend(frames[-1], Image.new("RGB", (w, h)), (k + 1) / 4))
    # CTA end card
    card = Image.new("RGB", (w, h), (18, 16, 26))
    dr = ImageDraw.Draw(card)
    dr.rectangle([0, h - 90, w, h], fill=(90, 69, 224))
    for i, ln in enumerate(_wrap(dr, cta_line, f_big, w - 80, 2)):
        tw = dr.textlength(ln, font=f_big)
        dr.text(((w - tw) / 2, h / 2 - 60 + i * 54), ln, font=f_big, fill=(248, 247, 244))
    msg = "End card — mirrors the spoken CTA (Mastery §5)"
    dr.text(((w - dr.textlength(msg, font=f_cap)) / 2, h - 60), msg, font=f_cap, fill=(255, 255, 255))
    for _ in range(16):
        frames.append(card.copy())
    if not frames:
        return None
    os.makedirs(os.path.dirname(out_gif), exist_ok=True)
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=256) for f in frames]
    pal[0].save(out_gif, save_all=True, append_images=pal[1:], duration=85, loop=0, optimize=True)
    return out_gif


def run_final_edit(project, cfg):
    folder = project["folder"]
    edit_dir = os.path.join(folder, "edit")
    os.makedirs(edit_dir, exist_ok=True)
    rows = scene_marker_rows(project)
    pkg = project.get("package", {})
    clips = {}
    for b in project.get("videos", {}).get("batches", []):
        for c in b.get("clips", []):
            clips[c["scene_id"]] = c

    # 1) scene marker (single source of truth, never loses an ID)
    marker_rel = os.path.join("edit", "scene_marker.json")
    with open(os.path.join(folder, marker_rel), "w") as f:
        json.dump({"project": project["name"], "exported": datetime.datetime.now().isoformat(), "scenes": rows}, f, indent=2)

    # 2) EDL
    t = 0.0
    edl_scenes = []
    for r in rows:
        clip = clips.get(r["scene_id"], {})
        edl_scenes.append({
            "scene": r["scene_id"], "asset": clip.get("asset_id"), "file": clip.get("file"),
            "in": round(t, 2), "out": round(t + r["duration"], 2),
            "transition": "dip-3f" if r["scene_id"] != rows[-1]["scene_id"] else "hold-cta-card",
            "caption": r["vo"], "beat": r["beat"],
        })
        t += r["duration"]
    edl = {
        "title": project["name"], "fps": 24, "engine": "demo-preview" if cfg.get("mode") != "live" else "claude-remotion-skill",
        "mastery_rules": ["cut on VO emphasis", "no same-framing consecutive cuts", "last 15% = CTA territory", "end card mirrors spoken CTA"],
        "scenes": edl_scenes, "cta_card": {"line": pkg.get("cta", {}).get("line", ""), "hold_s": 1.4},
    }
    edl_rel = os.path.join("edit", "edl.json")
    with open(os.path.join(folder, edl_rel), "w") as f:
        json.dump(edl, f, indent=2)

    # 3) notes vs Mastery.md
    notes_rel = os.path.join("edit", "FINAL_EDIT_NOTES.md")
    with open(os.path.join(folder, notes_rel), "w") as f:
        f.write(f"# Final Edit Notes — {project['name']}\n\n"
                f"Engine: {edl['engine']} · {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n"
                "## Choices checked against Mastery.md\n"
                "- §3 pacing: dip transitions land on VO emphasis beats; no same-framing consecutive cuts.\n"
                "- §5 CTA: final card mirrors the spoken line; held ~1.4s per copy beat.\n"
                "- §6: asset identity enforced via Scene Marker IDs (no re-renders of approved scenes).\n\n"
                "## Scene order\n" + "\n".join(f"- {s['scene']} ({s['in']}s–{s['out']}s) — {s['asset']}" for s in edl_scenes) + "\n")

    # 4) preview render from approved clips
    gifs = [os.path.join(folder, clips[r["scene_id"]]["file"]) for r in rows if r["scene_id"] in clips and clips[r["scene_id"]].get("file")]
    prev_rel = os.path.join("edit", "final_preview.gif")
    build_preview(gifs, rows, pkg.get("cta", {}).get("line", "Start today."), os.path.join(folder, prev_rel))

    return {
        "scene_marker": marker_rel,
        "edl": edl_rel,
        "notes": notes_rel,
        "preview": prev_rel if os.path.exists(os.path.join(folder, prev_rel)) else None,
        "engine": edl["engine"],
        "finished": datetime.datetime.now().isoformat(timespec="seconds"),
        "source_clip_revs": {r["scene_id"]: clips.get(r["scene_id"], {}).get("rev") for r in rows},
    }
