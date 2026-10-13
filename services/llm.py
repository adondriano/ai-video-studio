"""
llm.py — the "brain" layer.

Demo mode ships with a built-in **local python brain** (no API keys) that produces
structured, deterministic-but-seeded output: creative packages, revisions, image
prompts, QC reviews, motion prompts and Learn-tab analyses.

Live mode routes the same calls to OpenAI / Anthropic (text) or to a user-provided
local python script (contract: reads JSON on stdin, writes JSON on stdout).
"""

import os
import re
import json
import hashlib
import datetime
import subprocess

# ----------------------------------------------------------------------------- utils

def _ts():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _seed(*parts):
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest(), 16)


def _pick(rng_list_seed, options):
    return options[rng_list_seed % len(options)]


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def _detect_duration(text, default=30):
    m = re.search(r"(\d+)\s*(s|sec|secs|second|seconds)\b", text or "", re.I)
    if m:
        v = int(m.group(1))
        if 5 <= v <= 180:
            return v
    return default


def _extract_names(text):
    names = re.findall(r"(?:[Mm]eet|[Ii]ntroducing|[Tt]his is)\s+([A-Z][a-z]{2,})", text or "")
    pool = ["Maya", "Leo", "Nina", "Theo"]
    out, i = [], 0
    for n in names:
        if n not in out:
            out.append(n)
    while len(out) < 2:
        out.append(pool[i % len(pool)])
        i += 1
        out = list(dict.fromkeys(out))
    return out[:3]


# ----------------------------------------------------------------------------- live text calls

class LiveError(Exception):
    pass


def text_complete(system, user, cfg):
    """Route a text completion to the configured provider."""
    prov = cfg["providers"]["llm"]
    kind = prov.get("kind", "local")
    if kind == "openai":
        return _openai(system, user, prov)
    if kind == "anthropic":
        return _anthropic(system, user, prov)
    if kind == "gemini":
        return _gemini(system, user, prov)
    if kind == "opencode":
        return _opencode(system, user, prov)
    if kind == "script":
        out = run_local_script(prov.get("local_script", ""), {"system": system, "user": user})
        return out.get("text", "") if isinstance(out, dict) else str(out)
    raise LiveError("LLM provider is set to built-in local brain.")


def _openai(system, user, prov):
    import requests
    key = prov.get("api_key", "")
    if not key:
        raise LiveError("OpenAI API key missing (Settings).")
    r = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": prov.get("model") or "gpt-4o",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise LiveError(f"OpenAI {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def _anthropic(system, user, prov):
    import requests
    key = prov.get("api_key", "")
    if not key:
        raise LiveError("Anthropic API key missing (Settings).")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
        json={
            "model": prov.get("model") or "claude-sonnet-4-5",
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise LiveError(f"Anthropic {r.status_code}: {r.text[:300]}")
    return "".join(b.get("text", "") for b in r.json().get("content", []))


def _gemini(system, user, prov):
    import requests
    key = prov.get("api_key", "")
    if not key:
        raise LiveError("Gemini API key missing (Settings).")
    model = prov.get("model") or "gemini-2.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"parts": [{"text": user}]}]
    }
    r = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=90)
    if r.status_code != 200:
        raise LiveError(f"Gemini {r.status_code}: {r.text[:300]}")
    try:
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        raise LiveError(f"Gemini unexpected response: {r.text[:300]}")


def _opencode(system, user, prov):
    import requests
    base_url = prov.get("base_url", "").rstrip("/")
    if not base_url:
        raise LiveError("OpenCode / Custom base_url missing (Settings).")
    key = prov.get("api_key", "dummy")  # some local custom endpoints don't need real keys
    url = f"{base_url}/chat/completions"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": prov.get("model") or "default",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.7,
        },
        timeout=90,
    )
    if r.status_code != 200:
        raise LiveError(f"OpenCode {r.status_code}: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]


def run_local_script(path, payload):
    """Custom local python counterpart: `python script.py` — JSON in via stdin, JSON out via stdout."""
    if not path or not os.path.exists(path):
        raise LiveError(f"Local script not found: {path!r} (see Settings → install notes)")
    proc = subprocess.run(
        ["python", path], input=json.dumps(payload), capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise LiveError(f"Local script failed: {proc.stderr[:400]}")
    return json.loads(proc.stdout or "{}")


def _live_or_none(cfg, fn):
    """Try a live LLM call; return None on failure (caller falls back to demo)."""
    if cfg.get("mode") != "live":
        return None
    try:
        return fn()
    except Exception:
        return None


def _json_from(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ----------------------------------------------------------------------------- style knowledge

STYLE_HINTS = {
    "ugc": "handheld phone look, authentic natural light, true-to-life grade",
    "claymation": "handmade clay textures, visible fingerprints, stop-motion charm, matte tactile grade",
    "pixar": "high-end stylized 3D animation, oversized soft key light, subsurface glow, expressive big eyes",
    "cinematic": "anamorphic 2.39:1, motivated practicals, volumetric haze, teal-orange filmic grade",
    "anime": "cel-shaded 2D, pastel skies, crisp line art, speed-line accents",
    "noir": "black & white, hard venetian shadows, single hard source, high contrast",
    "paper": "layered paper-craft diorama, soft shadowbox depth, flat crafty light",
}


def style_hint(style):
    return STYLE_HINTS.get((style or "").lower().strip(), f"{style} aesthetic (custom style)")


BEATS_15 = ["HOOK", "PROBLEM", "PRODUCT", "PROOF", "CTA"]
BEATS_MID = ["PROBLEM", "AGITATE", "REVEAL", "BENEFIT", "PROOF", "ESCALATE", "BENEFIT", "PROOF"]
SHOT_SIZES = ["Establishing wide", "Medium", "Close-up", "Insert / detail", "POV handheld", "Over-shoulder", "Macro product", "Low angle"]
MOVES = ["slow push-in", "static lockoff", "gentle orbit 20°", "whip-in from right", "slider left→right", "crane up", "handheld follow", "dutch tilt settle"]
LENSES = ["24mm", "28mm", "35mm", "50mm", "85mm", "100mm macro"]


# ----------------------------------------------------------------------------- creative package

def _mastery_applied(mastery_text):
    """Pull which Mastery principles the package consciously applied."""
    applied = []
    sections = re.split(r"\n## ", mastery_text or "")
    for sec in sections[1:]:
        title = sec.splitlines()[0].strip()[:44]
        for line in sec.splitlines()[1:]:
            if line.strip().startswith("- "):
                applied.append(f"{title} — {line.strip()[2:].strip()[:90]}")
                break
        if len(applied) >= 4:
            break
    return applied


def creative_package(brief, style, mastery_text, workflow_text, reference_desc, cfg, comment=None):
    """Stage 1: brief → one 'For Approval' package with 5 sections."""
    payload = {
        "brief": brief, "style": style, "mastery": mastery_text,
        "workflow": workflow_text, "reference": reference_desc, "comment": comment,
    }
    live = _live_or_none(cfg, lambda: _json_from(text_complete(
        "You are a direct-response creative director. Return STRICT JSON only.",
        "Given this context produce a creative package JSON with keys: scenes (list of "
        "{id,title,beat,visual,vo,duration}), cta ({line,on_screen,vo,timing}), shots (list of "
        "{scene_id,shot,lens,movement,notes}), characters (list of {token,name,role,mint_prompt}), "
        "environments (list of {token,name,mint_prompt}). Brief: " + json.dumps(payload),
        cfg)))
    if live and isinstance(live, dict) and live.get("scenes"):
        live["engine"] = "live"
        live.setdefault("version", 1)
        live.setdefault("revisions_log", [])
        live["mastery_applied"] = _mastery_applied(mastery_text)
        live["style"] = style
        return live
    return _demo_package(brief, style, mastery_text, reference_desc, cfg)


def _demo_package(brief, style, mastery_text, reference_desc, cfg):
    ss = _sentences(brief)
    words = len((brief or "").split())
    total = _detect_duration(brief, 30)
    n = max(5, min(10, round(words / 14) or 4, len(ss) * 2 or 4))
    if words < 25:
        n = 5
    dur = round(total / n, 1)
    names = _extract_names(brief)
    hint = style_hint(style)
    use_mcp = cfg["providers"]["image"].get("kind") == "higgsfield"

    # distribute sentences across scenes
    chunks, per = [], max(1, len(ss) // n)
    for i in range(n):
        c = ss[i * per:(i + 1) * per] if i < n - 1 else ss[i * per:]
        chunks.append(" ".join(c) if c else "")
    if len(ss) < n:
        chunks = [ss[i] if i < len(ss) else "" for i in range(n)]

    scenes, shots = [], []
    for i in range(n):
        sid = f"SC-{i + 1:02d}"
        beat = "HOOK" if i == 0 else ("CTA" if i == n - 1 else _pick(_seed(sid, "beat"), BEATS_MID))
        vo = chunks[i] if chunks[i] else ("(on-screen text beat)" if i else "(visual-only hook)")
        hero = names[0] if i % 2 == 0 else (names[1] if len(names) > 1 else names[0])
        title_src = (chunks[i] or brief or "Untitled").strip()
        title = " ".join(title_src.split()[:5]).strip(",.;:") or f"Scene {i + 1}"
        visual = (
            f"{hero} — { _pick(_seed(sid,'v'), ['mid-action, interrupted frame', 'direct to camera', 'in profile, lit by window', 'hands-first insert']) }"
            f"; {hint}; emphasis: {beat.lower()}"
        )
        if i == 0:
            visual = f"PATTERN-INTERRUPT — {visual} (first frame readable at 10% brightness, per Mastery §1)"
        scenes.append({"id": sid, "title": title[:60], "beat": beat, "visual": visual,
                       "vo": vo, "duration": dur})
        shots.append({
            "scene_id": sid,
            "shot": _pick(_seed(sid, "shot"), SHOT_SIZES),
            "lens": _pick(_seed(sid, "lens"), LENSES),
            "movement": _pick(_seed(sid, "mv"), MOVES),
            "notes": _pick(_seed(sid, "nt"), [
                "Cut on VO emphasis (Mastery §3).", "Hold 3 frames past comfort for retention.",
                "Product legible in frame.", "Match key-light direction with ENV mint.",
                "Leave headroom for on-screen text."]),
        })

    cta_src = ss[-1] if ss else "Try it today."
    cta = {
        "line": cta_src if "!" in cta_src or "." in cta_src else cta_src + ".",
        "on_screen": " ".join(cta_src.split()[:8]) + ("…" if len(cta_src.split()) > 8 else ""),
        "vo": cta_src,
        "timing": f"final {max(2, round(total * 0.15))}s (≈ last 15% of runtime, per Mastery §5)",
        "formula": "1 action + 1 reason + 1 urgency cue",
    }

    characters = []
    for j, nm in enumerate(names[:2]):
        characters.append({
            "token": f"CHAR_{nm.upper()}",
            "name": nm,
            "role": "Protagonist" if j == 0 else "Supporting / foil",
            "mint_prompt": (
                f"{style} character mint of '{nm}' ({'protagonist' if j == 0 else 'supporting'}): consistent face sheet, "
                f"3/4 + front + profile views, neutral expression + smile, wardrobe simple, {hint}. "
                + (f"Mint once, then ALWAYS reference as @{f'CHAR_{nm.upper()}'} via @elements (Higgsfield MCP)." if use_mcp
                   else f"Stable ID: CHAR_{nm.upper()} — reuse in every prompt to prevent drift.")),
        })

    environments = [
        {"token": "ENV_HERO", "name": "Hero location",
         "mint_prompt": f"{style} environment mint: primary world for this ad, one key-light direction, lived-in detail, {hint}. "
                        + ("Reference as @ENV_HERO via @elements on Higgsfield MCP." if use_mcp else "Stable ID: ENV_HERO.")},
        {"token": "ENV_B", "name": "Contrast location",
         "mint_prompt": f"{style} environment mint: contrasting second world (tighter, moodier) for problem/agitate beats, {hint}. "
                        + ("Reference as @ENV_B via @elements on Higgsfield MCP." if use_mcp else "Stable ID: ENV_B.")},
    ]

    pkg = {
        "engine": "demo-brain" if cfg.get("mode") != "live" else "live-fallback",
        "style": style,
        "version": 1,
        "created": _ts(),
        "target_duration": total,
        "reference_used": bool(reference_desc),
        "scenes": scenes,
        "cta": cta,
        "shots": shots,
        "characters": characters,
        "environments": environments,
        "mastery_applied": _mastery_applied(mastery_text),
        "revisions_log": [],
        "notes": ([f"Reference supplied: {reference_desc[:140]}"] if reference_desc else [])
                  + [f"Built with Mastery.md v-current + Workflow.md {('· @elements ON (Higgsfield MCP)' if use_mcp else '· @elements reserved (enable Higgsfield MCP in Settings)')}"],
    }
    return pkg


# ----------------------------------------------------------------------------- revisions

def revise_package(pkg, comments, cfg):
    """Apply revision comments to ONLY the unapproved sections. Surgical, never global."""
    new = json.loads(json.dumps(pkg))
    new["version"] = pkg.get("version", 1) + 1
    log = {"version": new["version"], "ts": _ts(), "comments": comments, "changes": {}}
    n = len(new.get("scenes", []))

    for section, comment in (comments or {}).items():
        c = (comment or "").strip()
        if not c:
            continue
        changes = []
        low = c.lower()

        if section == "storyboard":
            if re.search(r"short|fast|pac|tight", low):
                for s in new["scenes"]:
                    s["duration"] = max(0.8, round(s["duration"] * 0.85, 1))
                changes.append("Tightened pacing ~15% across all scenes.")
            if "hook" in low or re.search(r"first|open", low):
                new["scenes"][0]["visual"] = f"PATTERN-INTERRUPT v{new['version']} — {c[:90]}; readable at 10% brightness"
                changes.append("Rebuilt SC-01 as a pattern‑interrupt around your note.")
            if re.search(r"cta|ending|end\b", low):
                new["scenes"][-1]["visual"] += f" | CTA beat restaged: {c[:80]}"
                changes.append("Restaged the final CTA scene.")
            if not changes:
                idx = _seed(c) % n
                new["scenes"][idx]["visual"] += f" | rev{new['version']}: {c[:90]}"
                changes.append(f"Adjusted {new['scenes'][idx]['id']} per note: “{c[:60]}”. Rest untouched.")

        elif section == "script_cta":
            new["cta"]["vo"] = c if len(c) < 140 else new["cta"]["vo"] + " " + c[:60]
            new["cta"]["line"] = new["cta"]["vo"]
            new["cta"]["on_screen"] = " ".join(new["cta"]["vo"].split()[:8])
            for s in new["scenes"][-2:]:
                if not s["vo"].endswith("!"):
                    s["vo"] = s["vo"] + ""
            changes.append("Rewrote CTA line from your note; re-synced on-screen text.")

        elif section == "shotlist":
            for sh in new["shots"]:
                if re.search(r"move|angle|lens|camera", low):
                    sh["movement"] = _pick(_seed(c, sh["scene_id"]), MOVES)
                    sh["lens"] = _pick(_seed(c, "l", sh["scene_id"]), LENSES)
            changes.append(f"Re-blocked camera work ({c[:60]}).")

        elif section == "characters":
            tokens = re.findall(r"[\"'“](.+?)[\"'”]", c) or [w for w in c.split() if len(w) > 6][:3]
            for ch in new["characters"]:
                if tokens:
                    ch["mint_prompt"] += f" + revision v{new['version']} traits: {', '.join(tokens[:4])}"
                ch["rev"] = new["version"]
            changes.append("Mint prompts updated with new traits; IDs unchanged.")

        elif section == "environments":
            m = re.search(r"dark|bright|day|night|warm|cold|moody", low)
            for e in new["environments"]:
                e["mint_prompt"] += f" + revision v{new['version']}: {m.group(0) if m else c[:60]}"
            changes.append("Lighting/mood direction folded into environment mints.")

        log["changes"][section] = changes or [f"Noted: {c[:80]}"]

    new["revisions_log"] = pkg.get("revisions_log", []) + [log]
    return new


# ----------------------------------------------------------------------------- images

def image_prompt(scene, pkg, cfg):
    use_mcp = cfg["providers"]["image"].get("kind") == "higgsfield"
    toks = [f"@{c['token']}" for c in pkg.get("characters", [])] + [f"@{e['token']}" for e in pkg.get("environments", [])]
    core = (f"{scene['visual']} | style: {style_hint(pkg.get('style',''))} | beat: {scene['beat']} | "
            f"duration context {scene['duration']}s | 16:9, ad-frame composition, space for captions")
    neg = "no extra fingers, no warped text, no watermark, no logo drift, single character identity"
    if use_mcp:
        return f"@elements {' '.join(toks)} · {core} · negative: {neg}"
    return f"{core} · minted refs (IDs locked): {', '.join(t.replace('@','') for t in toks)} · negative: {neg}"


def refine_image_prompt(prompt, comment):
    return f"{prompt} | REVISION: {comment.strip()[:140]}"


def review_image(entry, pkg):
    """LLM QC pass. Deterministic per scene/rev so the demo loop is stable."""
    s = _seed(entry["scene_id"], "qc", entry.get("rev", 1))
    notes = [f"Composition vs board {entry['scene_id']}: matched.",
             "Identity refs held." if entry.get("rev", 1) > 1 else "Minted identity applied from prompt refs."]
    status = "pass"
    if s % 5 == 0 and entry.get("rev", 1) == 1:
        status = "attention"
        notes.append("Possible edge artifact / hand geometry risk — reroll or revise if visible at 100%.")
        notes.append("Live mode: this becomes a true vision-model abnormality scan.")
    return {"status": status, "notes": notes, "checked": _ts()}


# ----------------------------------------------------------------------------- videos

def motion_prompt(scene, img_entry, pkg):
    moves = MOVES
    mv = _pick(_seed(scene["id"], "motion", img_entry.get("rev", 1)), moves)
    acts = ["gentle head turn into a smile on the beat", "reaches for the product, lands on VO emphasis",
            "subtle breath + blink, micro-expression shift", "steps toward camera 10%, hands active",
            "holds product up to lens, controlled rack focus"]
    return (f"{mv} · subject: {_pick(_seed(scene['id'],'act'), acts)} · hold identity from {img_entry['asset_id']} "
            f"· {scene['duration']}s, 24fps · no morphing, keep on-screen space clean · style lock: {pkg.get('style','')}")


# ----------------------------------------------------------------------------- learn tab

HOOK_TYPES = ["Pattern-interrupt", "Bold claim + proof tease", "POV immersion", "Negative hook", "Question loop"]


def analyze_video(filename, mastery_text, cfg):
    """Learn tab analysis. Demo: structured heuristic analysis. Live: LLM (wire vision/frames later)."""
    payload = {"file": filename, "mastery": mastery_text}
    live = _live_or_none(cfg, lambda: _json_from(text_complete(
        "You are a direct-response ad analyst. Strict JSON only.",
        "Analyze why this ad worked and how to reuse it. JSON keys: hook, why_worked (list), "
        "steal (list), pacing, cta, structure. Media: " + json.dumps(payload), cfg)))
    if live and isinstance(live, dict) and live.get("hook"):
        live["engine"] = "live"
        return live

    base = os.path.splitext(os.path.basename(filename))[0]
    words = [w for w in re.split(r"[_\-\s]+", base) if len(w) > 3]
    topic = " ".join(words[:3]) or "its category"
    s = _seed(base)
    hook = _pick(s, HOOK_TYPES)
    struct = _pick(s // 7, ["15s: Hook → Problem → Product → Proof → CTA",
                            "30s: Hook → Agitate → Reveal → 3 benefits → Proof → CTA",
                            "Story arc: protagonist pain → discovery → payoff montage → stinger"])
    analysis = {
        "engine": "demo-brain",
        "file": filename,
        "analyzed": _ts(),
        "hook": hook,
        "topic": topic,
        "structure": struct,
        "why_worked": [
            f"Hook type '{hook}' matches the {topic} audience's scroll-state — stops the thumb in <1s.",
            "Product is recognizable by scene 2; proof (not adjectives) carries the middle third.",
            "Pacing respects cut-rhythm discipline — no two consecutive shots share framing.",
            "Single CTA with one reason and one urgency cue; end-card mirrors the spoken words.",
        ],
        "steal": [
            f"Reuse the '{hook}' opening family for our next {topic} brief, reskinned to our product.",
            "Copy the proof-first mid-section: show receipts/timers before any benefit claim.",
            "Mirror their CTA split: pivot phrase early, then the last ~15% is CTA territory only.",
        ],
        "pacing": _pick(s // 13, ["Fast UGC rhythm: cuts every 1.2–2.0s", "Hybrid: 2s cuts, 4s breathers on proof beats",
                                  "Cinematic: 2.5–4s cuts, beat-synced to VO emphasis"]),
        "cta": _pick(s // 3, ["Soft CTA: “link's below” + handheld product hold",
                              "Hard CTA: discount + deadline on end card",
                              "Question CTA: “still doing it the old way?” → product shot"]),
        "verdict": "Patterns folded into Mastery.md (Learnings Log + consolidated sections).",
    }
    return analysis


def update_mastery(analysis, know_dir):
    """The LLM always reads & updates Mastery.md. Appends a log entry then consolidates
    pattern bullets upward into their sections. Keeps versioned history."""
    path = os.path.join(know_dir, "Mastery.md")
    with open(path, "r", encoding="utf-8") as f:
        doc = f.read()

    hist = os.path.join(know_dir, "history")
    os.makedirs(hist, exist_ok=True)
    with open(os.path.join(hist, f"Mastery-{datetime.datetime.now():%Y%m%d-%H%M%S}.md"), "w", encoding="utf-8") as f:
        f.write(doc)

    # bump counters in the blockquote header
    m = re.search(r"Sources analyzed: (\d+)", doc)
    count = int(m.group(1)) + 1 if m else 1
    doc = re.sub(r"> Last consolidated:.*?Sources analyzed: \d+",
                 f"> Last consolidated: {_ts()} · Sources analyzed: {count}", doc)

    def add_under(header, bullet):
        nonlocal doc
        bullet = bullet.strip()
        if bullet[:40] in doc:
            return
        pattern = re.compile(rf"(## {re.escape(header)}[^\n]*\n(?:- [^\n]*\n)*)")
        mm = pattern.search(doc)
        if mm:
            doc = doc[:mm.end()] + f"- {bullet}\n" + doc[mm.end():]
        else:
            doc += f"\n## {header}\n- {bullet}\n"

    add_under("1. Hook Patterns", f"Observed in the wild: '{analysis['hook']}' worked for {analysis.get('topic','this category')} — {analysis['file']}.")
    add_under("3. Pacing & Editing", f"Validated pacing signature: {analysis['pacing']}.")
    add_under("5. CTA Engineering", f"Winning CTA shape: {analysis['cta']}.")
    add_under("2. Structure & Beats", f"Effective skeleton: {analysis['structure']}.")

    log_line = (f"- [{analysis['analyzed']}] **{analysis['file']}** — hook: {analysis['hook']}; "
                f"steal: {analysis['steal'][0][:110]}")
    if "## Learnings Log" in doc:
        doc = doc.rstrip() + "\n" + log_line + "\n"
    else:
        doc += f"\n## Learnings Log\n{log_line}\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(doc)
    return count
