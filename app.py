#!/usr/bin/env python3
"""
Framecraft — AI Video Production Studio
Local-first Flask app. Demo mode = built-in local python generators (zero API keys).
Live mode = OpenAI/Anthropic (+Higgsfield/HeyGen/ElevenLabs) once keys are saved in Settings.

Run:  python app.py   →  http://127.0.0.1:5000
"""

import os
import re
import io
import json
import zipfile
import datetime

from flask import Flask, request, jsonify, send_file, send_from_directory, render_template
from werkzeug.utils import secure_filename

from services import llm, images as img_svc, video as vid_svc, final_edit, stt

BASE = os.path.dirname(os.path.abspath(__file__))
KNOW = os.path.join(BASE, "knowledge")
DATA = os.path.join(BASE, "data")
UPLOADS = os.path.join(BASE, "uploads")
SKILLS_DIR = os.path.join(BASE, "skills")
for d in (KNOW, DATA, UPLOADS, SKILLS_DIR, os.path.join(KNOW, "history")):
    os.makedirs(d, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4GB uploads

CONFIG_PATH = os.path.join(BASE, "config.json")
SECTION_KEYS = ["storyboard", "script_cta", "shotlist", "characters", "environments"]

DEFAULT_CFG = {
    "mode": "demo",
    "projects_root": os.path.join(BASE, "projects"),
    "projects": {},
    "providers": {
        "llm":   {"kind": "local", "api_key": "", "model": "gpt-4o", "local_script": ""},
        "image": {
            "kind": "local",
            "api_key": "",
            "model": "gpt-image-1",
            "use_mcp": True,
            "hf_provider": "auto",
            "stability_steps": 10,
            "stability_cfg_scale": 5,
        },
        "video": {"kind": "local", "api_key": "", "model": "", "hf_provider": "auto"},
        "voice": {"kind": "local", "api_key": "", "voice_id": ""},
    },
}


# ----------------------------------------------------------------------------- helpers

def ts():
    return datetime.datetime.now().isoformat(timespec="seconds")


def slugify(s):
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "untitled"


def load_cfg():
    cfg = json.loads(json.dumps(DEFAULT_CFG))
    if os.path.exists(CONFIG_PATH):
        try:
            saved = json.load(open(CONFIG_PATH))
            for k, v in saved.items():
                if k == "providers":
                    for pk, pv in v.items():
                        cfg["providers"].setdefault(pk, {}).update(pv)
                else:
                    cfg[k] = v
        except Exception:
            pass
    return cfg


def save_cfg(cfg):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


def provider_ready(cfg):
    p = cfg["providers"]

    llm_kind = p["llm"].get("kind", "local")
    image_kind = p["image"].get("kind", "local")
    video_kind = p["video"].get("kind", "local")
    voice_kind = p["voice"].get("kind", "local")

    # Local providers are valid for Live mode.
    llm_ok = (
        llm_kind == "local"
        or (llm_kind in ("openai", "anthropic", "gemini") and bool(p["llm"].get("api_key")))
        or (llm_kind == "opencode" and bool(p["llm"].get("base_url")))
        or (llm_kind == "script" and bool(p["llm"].get("local_script")))
    )

    img_ok = (
        image_kind == "local"
        or bool(p["image"].get("api_key"))
    )

    vid_ok = (
        video_kind == "local"
        or bool(p["video"].get("api_key"))
    )

    voice_ok = (
        voice_kind == "local"
        or bool(p["voice"].get("api_key"))
    )

    return {
        "llm": llm_ok,
        "image": img_ok,
        "video": vid_ok,
        "voice": voice_ok,
    }


def live_ready(cfg):
    r = provider_ready(cfg)
    return r["llm"] and r["image"]


def public_cfg(cfg):
    out = {"mode": cfg.get("mode", "demo"), "projects_root": cfg["projects_root"],
           "live_ready": live_ready(cfg), "ready": provider_ready(cfg), "providers": {}}
    for name, p in cfg["providers"].items():
        out["providers"][name] = {k: v for k, v in p.items() if k != "api_key"}
        out["providers"][name]["has_key"] = bool(p.get("api_key"))
        out["providers"][name]["key_tail"] = ("…" + p["api_key"][-4:]) if p.get("api_key") else ""
    return out


def mastery_text():
    return open(os.path.join(KNOW, "Mastery.md"), encoding="utf-8").read()


def workflow_text():
    return open(os.path.join(KNOW, "Workflow.md"), encoding="utf-8").read()


def save_project(p):
    os.makedirs(p["folder"], exist_ok=True)
    with open(os.path.join(p["folder"], "project.json"), "w") as f:
        json.dump(p, f, indent=2)


def get_project(pid):
    cfg = load_cfg()
    rec = cfg.get("projects", {}).get(pid)
    if not rec:
        return None
    f = os.path.join(rec["folder"], "project.json")
    if not os.path.exists(f):
        return None
    return json.load(open(f))


def register_project(p):
    cfg = load_cfg()
    cfg.setdefault("projects", {})[p["id"]] = {"name": p["name"], "folder": p["folder"], "created_at": p["created_at"]}
    save_cfg(cfg)


def err(msg, code=400):
    return jsonify({"ok": False, "error": msg}), code


# ----------------------------------------------------------------------------- pages / state

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/state")
def state():
    cfg = load_cfg()
    projects = []
    for pid, rec in cfg.get("projects", {}).items():
        pj = os.path.join(rec["folder"], "project.json")
        stage, updated = "unknown", ""
        if os.path.exists(pj):
            try:
                d = json.load(open(pj))
                stage, updated = d.get("stage", "?"), d.get("updated", "")
            except Exception:
                pass
        projects.append({"id": pid, "name": rec["name"], "folder": rec["folder"], "stage": stage, "updated": updated})
    projects.sort(key=lambda x: x.get("updated", ""), reverse=True)
    return jsonify({"ok": True, "settings": public_cfg(cfg), "projects": projects})


@app.post("/api/mode")
def set_mode():
    mode = (request.get_json(force=True) or {}).get("mode", "demo")
    cfg = load_cfg()
    if mode == "live" and not live_ready(cfg):
        r = provider_ready(cfg)
        missing = [k for k in ("llm", "image") if not r[k]]
        return err(f"Live is locked — configure API keys for: {', '.join(missing)} (Settings tab).", 409)
    cfg["mode"] = mode
    save_cfg(cfg)
    return jsonify({"ok": True, "mode": mode, "settings": public_cfg(cfg)})


@app.post("/api/settings")
def settings():
    body = request.get_json(force=True) or {}
    cfg = load_cfg()
    if body.get("projects_root"):
        cfg["projects_root"] = body["projects_root"]
    for name, vals in (body.get("providers") or {}).items():
        if name not in cfg["providers"]:
            continue
        for k, v in vals.items():
            if k == "api_key" and (v is None or v == ""):
                continue  # never wipe a stored key with an empty field
            cfg["providers"][name][k] = v
    save_cfg(cfg)
    return jsonify({"ok": True, "settings": public_cfg(cfg)})


@app.get("/api/knowledge/<which>")
def knowledge(which):
    fn = "Mastery.md" if which == "mastery" else ("Workflow.md" if which == "workflow" else None)
    if not fn:
        return err("unknown doc", 404)
    return jsonify({"ok": True, "name": fn, "text": open(os.path.join(KNOW, fn), encoding="utf-8").read()})


@app.get("/api/knowledge/mastery/history")
def mastery_history():
    hist = os.path.join(KNOW, "history")
    vs = sorted(os.listdir(hist), reverse=True) if os.path.isdir(hist) else []
    return jsonify({"ok": True, "versions": vs[:30]})


@app.get("/api/skills/status")
def skills():
    return jsonify({"ok": True, **final_edit.skill_status(SKILLS_DIR)})


# ----------------------------------------------------------------------------- projects

@app.post("/api/projects")
def new_project():
    body = request.get_json(force=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return err("Ad name is required.")
    cfg = load_cfg()
    pid, i = slugify(name), 2
    while pid in cfg.get("projects", {}):
        pid = f"{slugify(name)}-{i}"
        i += 1
    folder = (body.get("folder") or "").strip() or os.path.join(cfg["projects_root"], pid)
    folder = os.path.abspath(os.path.expanduser(folder))
    for sub in ("images", "clips", "reference", "edit", "voiceover"):
        os.makedirs(os.path.join(folder, sub), exist_ok=True)
    p = {"id": pid, "name": name, "folder": folder, "created_at": ts(), "updated": ts(),
         "stage": "brief", "brief": {"text": "", "style": "ugc", "reference": None, "reference_note": "", "voiceover": None, "transcript": "", "transcript_source": ""},
         "package": None, "package_approved": False, "approvals": {k: False for k in SECTION_KEYS},
         "images": [], "images_done": False,
         "videos": {"batches": [], "done": False},
         "edit": {"self": None, "status": "idle", "result": None}}
    save_project(p)
    register_project(p)
    return jsonify({"ok": True, "project": p})


@app.get("/api/projects/<pid>")
def project(pid):
    p = get_project(pid)
    return jsonify({"ok": bool(p), "project": p}) if p else err("not found", 404)


@app.post("/api/projects/<pid>/process")
def process(pid):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    brief = (request.form.get("brief") or "").strip()
    style = (request.form.get("style") or "ugc").strip()
    aspect_ratio = (request.form.get("aspect_ratio") or "16:9").strip()
    note = (request.form.get("reference_note") or "").strip()
    ref = p["brief"].get("reference")
    voice = p["brief"].get("voiceover")
    transcript = p["brief"].get("transcript", "")
    transcript_source = p["brief"].get("transcript_source", "")

    f = request.files.get("reference")
    if f and f.filename:
        fn = f"{int(datetime.datetime.now().timestamp())}_{secure_filename(f.filename)}"
        rp = os.path.join(p["folder"], "reference", fn)
        f.save(rp)
        ref = {"file": os.path.join("reference", fn), "orig": f.filename}

    vf = request.files.get("voiceover")
    if vf and vf.filename:
        vfn = f"{int(datetime.datetime.now().timestamp())}_{secure_filename(vf.filename)}"
        vp = os.path.join(p["folder"], "voiceover", vfn)
        vf.save(vp)
        voice = {"file": os.path.join("voiceover", vfn), "orig": vf.filename}
        transcript, transcript_source = stt.transcribe_audio(vp)

    if len(brief) < 10 and len(transcript or "") < 10:
        return err("Paste a script/ad brief or upload a voiceover first (MP3/WAV/M4A).")

    effective_brief = brief.strip()
    if transcript:
        effective_brief = (effective_brief + "\n\nVoiceover transcript for captions / timing:\n" + transcript).strip() if effective_brief else transcript

    p["brief"] = {
        "text": brief,
        "style": style,
        "aspect_ratio": aspect_ratio,
        "reference": ref,
        "reference_note": note,
        "voiceover": voice,
        "transcript": transcript,
        "transcript_source": transcript_source,
    }
    ref_desc = " | ".join(x for x in [note, (ref or {}).get("orig", ""), (voice or {}).get("orig", "")] if x)
    cfg = load_cfg()
    p["package"] = llm.creative_package(effective_brief, style, mastery_text(), workflow_text(), ref_desc, cfg)
    p["package_approved"] = False
    p["approvals"] = {k: False for k in SECTION_KEYS}
    p["images"] = []
    p["images_done"] = False
    p["videos"] = {"batches": [], "done": False}
    p["edit"] = {"self": None, "status": "idle", "result": None}
    p["stage"] = "approval"
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/package/decision")
def package_decision(pid):
    p = get_project(pid)
    if not p or not p.get("package"):
        return err("no package", 404)
    body = request.get_json(force=True) or {}
    approvals = {k: bool((body.get("approvals") or {}).get(k)) for k in SECTION_KEYS}
    comments = {k: (body.get("comments") or {}).get(k, "") for k in SECTION_KEYS}
    approved_once = bool(p.get("package_approved"))

    if approved_once:
        revise_targets = {k: v for k, v in comments.items() if v.strip() and (not approvals.get(k) or approvals.get(k))}
        if not revise_targets and all(approvals.values()):
            p["approvals"] = {k: True for k in SECTION_KEYS}
            p["updated"] = ts()
            save_project(p)
            return jsonify({"ok": True, "next": "noop", "project": p})
        if not revise_targets:
            revise_targets = {k: comments[k] for k in SECTION_KEYS if not approvals.get(k) and comments[k].strip()}
        if not revise_targets:
            return err("Add a revision comment to any unchecked section.")
        p["package"] = llm.revise_package(p["package"], revise_targets, load_cfg())
        p["approvals"] = {k: True for k in SECTION_KEYS}
        p["updated"] = ts()
        save_project(p)
        return jsonify({"ok": True, "next": "revised-approved", "project": p})

    p["approvals"] = approvals
    if all(approvals.values()):
        p["package_approved"] = True
        p["stage"] = "images"
        p["updated"] = ts()
        save_project(p)
        return jsonify({"ok": True, "next": "images", "project": p})
    targets = {k: v for k, v in comments.items() if not approvals.get(k) and v.strip()}
    if not targets:
        return err("Unchecked sections need a revision comment.")
    p["package"] = llm.revise_package(p["package"], targets, load_cfg())
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "next": "revise", "project": p})


# ----------------------------------------------------------------------------- images

def _img_use_live(cfg):
    return cfg.get("mode") == "live" and cfg["providers"]["image"].get("kind") != "local"


def _make_image(p, scene, cfg):
    prompt = llm.image_prompt(scene, p["package"], cfg)
    sid = scene["id"]
    rel = os.path.join("images", f"{sid}.png")
    abs_path = os.path.join(p["folder"], rel)
    if _img_use_live(cfg):
        # Pass the project's aspect ratio into the cfg so providers can pick the right size
        cfg = dict(cfg)
        cfg["aspect_ratio"] = p.get("brief", {}).get("aspect_ratio", "16:9")
        img_svc.generate_live(prompt, abs_path, cfg)
    else:
        img_svc.paint(abs_path, p["id"], p["package"].get("style", "ugc"), sid, scene["title"], prompt, rev=1)
    return {"scene_id": sid, "asset_id": f"IMG-{sid}-r1", "prompt": prompt, "file": rel,
            "rev": 1, "approved": False, "qc": None, "history": []}


@app.post("/api/projects/<pid>/images/generate")
def images_generate(pid):
    p = get_project(pid)
    if not p or not p.get("package"):
        return err("no package", 404)
    cfg = load_cfg()
    try:
        keep = {i["scene_id"]: i for i in p.get("images", []) if i.get("approved")}
        out = []
        for sc in p["package"]["scenes"]:
            entry = keep.get(sc["id"]) or _make_image(p, sc, cfg)
            if not entry.get("qc"):
                entry["qc"] = llm.review_image(entry, p["package"])
            out.append(entry)
        p["images"] = out
        p["stage"] = "images"
        p["updated"] = ts()
        save_project(p)
    except Exception as e:
        return err(f"Image generation failed: {e}", 502)
    return jsonify({"ok": True, "project": p})


def _find(lst, sid):
    return next((x for x in lst if (x.get("scene_id") or x.get("id")) == sid), None)


@app.post("/api/projects/<pid>/images/mark")
def images_mark(pid):
    p = get_project(pid)
    body = request.get_json(force=True) or {}
    e = _find(p.get("images", []), body.get("scene_id", ""))
    if not p or not e:
        return err("not found", 404)
    e["approved"] = bool(body.get("approved"))
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/images/decision")
def images_decision(pid):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    if not p.get("images") or not all(i.get("approved") for i in p["images"]):
        return err("Every scene image must be approved before video generation.", 409)
    p["images_done"] = True
    p["stage"] = "videos"
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/images/<sid>/revise")
def images_revise(pid, sid):
    p = get_project(pid)
    e = _find(p.get("images", []), sid)
    if not p or not e:
        return err("not found", 404)
    comment = ((request.get_json(force=True) or {}).get("comment") or "").strip()
    if not comment:
        return err("Revision comment required.")
    cfg = load_cfg()
    e["rev"] += 1
    e["prompt"] = llm.refine_image_prompt(e["prompt"], comment)
    e["asset_id"] = f"IMG-{sid}-r{e['rev']}"
    e["approved"] = False
    try:
        if _img_use_live(cfg):
            img_svc.generate_live(e["prompt"], os.path.join(p["folder"], e["file"]), cfg)
        else:
            sc = _find(p["package"]["scenes"], sid)
            img_svc.paint(os.path.join(p["folder"], e["file"]), p["id"] + comment,
                          p["package"].get("style", "ugc"), sid, sc["title"], e["prompt"], rev=e["rev"])
    except Exception as ex:
        return err(f"Revision failed: {ex}", 502)
    e["qc"] = llm.review_image(e, p["package"])
    e["history"].append({"rev": e["rev"] - 1, "comment": comment, "ts": ts()})
    for b in p.get("videos", {}).get("batches", []):
        changed = False
        for c in b.get("clips", []):
            if c["scene_id"] == sid:
                c["approved"] = False
                changed = True
        if changed:
            b["approved"] = False
            b["approved_at"] = None
    p["videos"]["done"] = False
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/images/<sid>/reroll")
def images_reroll(pid, sid):
    p = get_project(pid)
    e = _find(p.get("images", []), sid)
    if not p or not e:
        return err("not found", 404)
    e["rev"] += 1
    e["asset_id"] = f"IMG-{sid}-r{e['rev']}"
    e["approved"] = False
    sc = _find(p["package"]["scenes"], sid)
    img_svc.paint(os.path.join(p["folder"], e["file"]), p["id"] + f"reroll{e['rev']}",
                  p["package"].get("style", "ugc"), sid, sc["title"], e["prompt"], rev=e["rev"])
    e["qc"] = llm.review_image(e, p["package"])
    for b in p.get("videos", {}).get("batches", []):
        changed = False
        for c in b.get("clips", []):
            if c["scene_id"] == sid:
                c["approved"] = False
                changed = True
        if changed:
            b["approved"] = False
            b["approved_at"] = None
    p["videos"]["done"] = False
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


# ----------------------------------------------------------------------------- videos

def _clip_scenes(p):
    return [c["scene_id"] for b in p["videos"]["batches"] for c in b["clips"]]


@app.post("/api/projects/<pid>/videos/next")
def videos_next(pid):
    p = get_project(pid)
    if not p or not p.get("images_done"):
        return err("Finish image approval first.", 409)
    done = set(_clip_scenes(p))
    imgs = {i["scene_id"]: i for i in p["images"]}
    remaining = [sc for sc in p["package"]["scenes"] if sc["id"] not in done]
    if not remaining:
        return err("All scenes already have clips.", 409)
    blocked = [sc["id"] for sc in remaining if not imgs.get(sc["id"], {}).get("approved")]
    if blocked:
        return err(f"Approve the current keyframe(s) first before generating clips: {', '.join(blocked[:4])}", 409)
    cfg = load_cfg()
    batch_n = len(p["videos"]["batches"])
    clips = []
    try:
        for sc in remaining[:4]:
            ie = imgs[sc["id"]]
            motion = llm.motion_prompt(sc, ie, p["package"])
            vid_kind = cfg["providers"]["video"].get("kind", "local")
            use_live = cfg.get("mode") == "live" and vid_kind != "local"
            ext = "mp4" if (use_live and vid_kind == "huggingface") else "gif"
            rel = os.path.join("clips", f"{sc['id']}.{ext}")
            abs_out = os.path.join(p["folder"], rel)
            if use_live:
                vid_svc.generate_live(os.path.join(p["folder"], ie["file"]), motion, abs_out, cfg)
                pattern = "live"
            else:
                _, pattern = vid_svc.render_clip(os.path.join(p["folder"], ie["file"]), abs_out, f"{p['id']}|{sc['id']}", motion)
            clips.append({
                "scene_id": sc["id"],
                "asset_id": f"CLIP-{sc['id']}-r1",
                "motion": motion,
                "file": rel,
                "move": pattern,
                "rev": 1,
                "approved": False,
                "history": [],
                "source_image_rev": ie.get("rev", 1)
            })
    except Exception as e:
        return err(f"Video generation failed: {e}", 502)
    p["videos"]["batches"].append({"index": batch_n, "approved": False, "approved_at": None, "clips": clips})
    p["stage"] = "videos"
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/videos/mark")
def videos_mark(pid):
    p = get_project(pid)
    body = request.get_json(force=True) or {}
    sid, flag = body.get("scene_id", ""), bool(body.get("approved"))
    img = _find(p.get("images", []), sid)
    for b in p["videos"]["batches"]:
        for c in b["clips"]:
            if c["scene_id"] == sid:
                if flag and img and img.get("rev", 1) > c.get("source_image_rev", 1):
                    return err(f"{sid} uses an older keyframe revision. Reroll or revise the clip first.", 409)
                c["approved"] = flag
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/videos/batch/<int:idx>/approve")
def videos_batch_approve(pid, idx):
    p = get_project(pid)
    if not p or idx >= len(p["videos"]["batches"]):
        return err("not found", 404)
    b = p["videos"]["batches"][idx]
    if not all(c.get("approved") for c in b["clips"]):
        return err("Approve every clip in the batch first (checkboxes).", 409)
    stale = []
    for c in b["clips"]:
        img = _find(p.get("images", []), c["scene_id"])
        if img and img.get("rev", 1) > c.get("source_image_rev", 1):
            stale.append(c["scene_id"])
    if stale:
        return err(f"These clips are out of sync with newer keyframes: {', '.join(stale)}", 409)
    b["approved"] = True
    b["approved_at"] = ts()
    total = len(p["package"]["scenes"])
    made = len(_clip_scenes(p))
    if made >= total and all(bb.get("approved") for bb in p["videos"]["batches"]):
        p["videos"]["done"] = True
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "all_done": p["videos"]["done"], "remaining": total - made, "project": p})


@app.post("/api/projects/<pid>/videos/<sid>/reroll")
def videos_reroll(pid, sid):
    p = get_project(pid)
    ie = _find(p.get("images", []), sid)
    for b in p["videos"]["batches"]:
        for c in b["clips"]:
            if c["scene_id"] == sid:
                c["rev"] += 1
                c["approved"] = False
                c["asset_id"] = f"CLIP-{sid}-r{c['rev']}"
                c["source_image_rev"] = ie.get("rev", 1)
                _, c["move"] = vid_svc.render_clip(os.path.join(p["folder"], ie["file"]),
                                                   os.path.join(p["folder"], c["file"]), f"{p['id']}|{sid}|rr{c['rev']}", c["motion"])
                p["updated"] = ts()
                save_project(p)
                return jsonify({"ok": True, "project": p})
    return err("not found", 404)


@app.post("/api/projects/<pid>/videos/<sid>/revise")
def videos_revise(pid, sid):
    comment = ((request.get_json(force=True) or {}).get("comment") or "").strip()
    if not comment:
        return err("Revision comment required.")
    p = get_project(pid)
    ie = _find(p.get("images", []), sid)
    for b in p["videos"]["batches"]:
        for c in b["clips"]:
            if c["scene_id"] == sid:
                c["rev"] += 1
                c["approved"] = False
                c["motion"] += f" | REVISION: {comment[:140]}"
                c["asset_id"] = f"CLIP-{sid}-r{c['rev']}"
                c["source_image_rev"] = ie.get("rev", 1)
                _, c["move"] = vid_svc.render_clip(os.path.join(p["folder"], ie["file"]),
                                                   os.path.join(p["folder"], c["file"]), f"{p['id']}|{sid}|rev{c['rev']}|{comment[:30]}", c["motion"])
                c["history"].append({"rev": c["rev"] - 1, "comment": comment, "ts": ts()})
                p["updated"] = ts()
                save_project(p)
                return jsonify({"ok": True, "project": p})
    return err("not found", 404)

@app.post("/api/projects/<pid>/stage")
def set_stage(pid):
    body = request.get_json(force=True) or {}
    stage = body.get("stage")
    valid = {"brief", "approval", "images", "videos", "edit", "done"}
    if stage not in valid:
        return err(f"invalid stage '{stage}'")
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    # guard: can only navigate to stages that have been reached before
    order = ["brief", "approval", "images", "videos", "edit", "done"]
    current_idx = order.index(p["stage"]) if p["stage"] in order else 0
    target_idx  = order.index(stage)
    # Allow navigation to any visited stage (≤ current) or to the very next one
    if target_idx > current_idx + 1:
        return err(f"Stage '{stage}' has not been reached yet.")
    p["stage"] = stage
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


@app.post("/api/projects/<pid>/voiceover")
def upload_voiceover(pid):
    """Upload + transcribe a voiceover independently of running the full process."""
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    vf = request.files.get("voiceover")
    if not vf or not vf.filename:
        return err("No audio file received.")
    os.makedirs(os.path.join(p["folder"], "voiceover"), exist_ok=True)
    vfn = f"{int(datetime.datetime.now().timestamp())}_{secure_filename(vf.filename)}"
    vp = os.path.join(p["folder"], "voiceover", vfn)
    vf.save(vp)
    transcript, source = stt.transcribe_audio(vp)
    p["brief"]["voiceover"] = {"file": os.path.join("voiceover", vfn), "orig": vf.filename}
    p["brief"]["transcript"] = transcript
    p["brief"]["transcript_source"] = source
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p, "transcript": transcript, "source": source})


@app.post("/api/projects/<pid>/videos/choice")
def videos_choice(pid):
    p = get_project(pid)
    if not p or not p.get("videos", {}).get("done"):
        return err("Approve all batches first.", 409)
    self_edit = bool((request.get_json(force=True) or {}).get("self"))
    p["edit"]["self"] = self_edit
    p["stage"] = "done" if self_edit else "edit"
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p})


# ----------------------------------------------------------------------------- final edit

@app.get("/api/projects/<pid>/edit/status")
def edit_status(pid):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    return jsonify({"ok": True, "skills": final_edit.skill_status(SKILLS_DIR),
                    "edit": p.get("edit", {}), "marker": final_edit.scene_marker_rows(p)})


@app.post("/api/projects/<pid>/edit/begin")
def edit_begin(pid):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    cfg = load_cfg()
    status = final_edit.skill_status(SKILLS_DIR)
    if not status["installed"] and cfg.get("mode") == "live":
        return err("claude-remotion-skill is not installed. Clone it into ./skills first (see instructions).", 409)
    p["edit"]["status"] = "running"
    save_project(p)
    try:
        result = final_edit.run_final_edit(p, cfg)
    except Exception as e:
        p["edit"]["status"] = "idle"
        save_project(p)
        return err(f"Final edit failed: {e}", 502)
    p["edit"]["status"] = "done"
    p["edit"]["result"] = result
    p["updated"] = ts()
    save_project(p)
    return jsonify({"ok": True, "project": p, "result": result})


# ----------------------------------------------------------------------------- assets & downloads

@app.get("/api/projects/<pid>/asset")
def asset(pid):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    rel = request.args.get("rel", "")
    full = os.path.abspath(os.path.join(p["folder"], rel))
    if not full.startswith(os.path.abspath(p["folder"]) + os.sep) and full != os.path.abspath(p["folder"]):
        return err("bad path", 403)
    if not os.path.exists(full):
        return err("missing", 404)
    return send_file(full)


def _zip(p, pairs, name):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel, arc in pairs:
            full = os.path.join(p["folder"], rel)
            if os.path.exists(full):
                z.write(full, arc)
    buf.seek(0)
    return send_file(buf, mimetype="application/zip", as_attachment=True, download_name=name)


@app.get("/api/projects/<pid>/download/<what>")
def download(pid, what):
    p = get_project(pid)
    if not p:
        return err("not found", 404)
    if what == "images.zip":
        return _zip(p, [(i["file"], f"{i['asset_id']}.png") for i in p.get("images", [])], f"{pid}-images.zip")
    if what == "clips.zip":
        pairs = [(c["file"], f"{c['asset_id']}.gif") for b in p["videos"]["batches"] for c in b["clips"]]
        pairs.append(("edit/scene_marker.json", "scene_marker.json"))
        return _zip(p, pairs, f"{pid}-clips.zip")
    m = re.match(r"batch-(\d+)\.zip", what)
    if m:
        idx = int(m.group(1))
        b = p["videos"]["batches"][idx]
        return _zip(p, [(c["file"], f"{c['asset_id']}.gif") for c in b["clips"]], f"{pid}-batch-{idx + 1}.zip")
    if what == "final.zip":
        r = (p.get("edit") or {}).get("result") or {}
        pairs = [(r.get(k), os.path.basename(r.get(k) or "")) for k in ("preview", "edl", "notes", "scene_marker") if r.get(k)]
        pairs.append(("project.json", "project.json"))
        return _zip(p, pairs, f"{pid}-final.zip")
    return err("unknown", 404)


# ----------------------------------------------------------------------------- learn tab

LEARN_IDX = os.path.join(DATA, "learn_index.json")


def learn_load():
    return json.load(open(LEARN_IDX)) if os.path.exists(LEARN_IDX) else {}


def learn_save(d):
    with open(LEARN_IDX, "w") as f:
        json.dump(d, f, indent=2)


@app.post("/api/learn/upload")
def learn_upload():
    files = request.files.getlist("files")
    if not files:
        return err("No files selected.")
    idx = learn_load()
    saved = []
    for f in files:
        if not f.filename:
            continue
        fn = secure_filename(f.filename)
        base, ext = os.path.splitext(fn)
        cand, i = fn, 2
        while os.path.exists(os.path.join(UPLOADS, cand)) and cand not in idx:
            cand = f"{base}-{i}{ext}"
            i += 1
        f.save(os.path.join(UPLOADS, cand))
        idx.setdefault(cand, {"processed": False, "uploaded": ts(), "insights": None})
        saved.append(cand)
    learn_save(idx)
    return jsonify({"ok": True, "saved": saved})


@app.get("/api/learn/list")
def learn_list():
    idx = learn_load()
    out = []
    for fn, meta in sorted(idx.items(), key=lambda kv: kv[1].get("uploaded", ""), reverse=True):
        fp = os.path.join(UPLOADS, fn)
        out.append({"file": fn, "size": os.path.getsize(fp) if os.path.exists(fp) else 0, **meta})
    return jsonify({"ok": True, "items": out})


@app.post("/api/learn/process")
def learn_process():
    fn = (request.get_json(force=True) or {}).get("file", "")
    safe = secure_filename(fn)
    if not safe or not os.path.exists(os.path.join(UPLOADS, safe)):
        return err("file not found", 404)
    analysis = llm.analyze_video(safe, mastery_text(), load_cfg())
    count = llm.update_mastery(analysis, KNOW)
    idx = learn_load()
    idx.setdefault(safe, {})["processed"] = True
    idx[safe]["processed_at"] = ts()
    idx[safe]["insights"] = analysis
    learn_save(idx)
    return jsonify({"ok": True, "analysis": analysis, "mastery_sources": count})


@app.get("/uploads/<path:fn>")
def uploaded(fn):
    return send_from_directory(UPLOADS, fn)


if __name__ == "__main__":
    print("\n  Framecraft — AI Video Production Studio")
    print("  → http://127.0.0.1:5000  (Demo mode works out of the box)\n")
    app.run(host="127.0.0.1", port=5000, debug=False)
