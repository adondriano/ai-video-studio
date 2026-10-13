"""
images.py — image generation layer.

Demo mode: a local placeholder *painter* (Pillow) that draws a styled, captioned
frame per scene — deterministic per (scene, rev) so IDs are stable and every
revision visibly changes the art. Live mode: route to Higgsfield (MCP) or the
OpenAI Images API here — same function contract.
"""

import os
import math
import random
import hashlib
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

PALETTES = {
    "ugc":       {"grad": [(247, 240, 230), (231, 210, 184), (183, 140, 104)], "accent": (216, 110, 74)},
    "claymation":{"grad": [(244, 222, 200), (224, 168, 128), (138, 84, 60)],  "accent": (196, 72, 52)},
    "pixar":     {"grad": [(214, 236, 250), (150, 196, 240), (70, 118, 200)], "accent": (255, 166, 66)},
    "cinematic": {"grad": [(26, 30, 40),  (46, 58, 74),  (122, 96, 72)],    "accent": (214, 162, 92)},
    "anime":     {"grad": [(250, 228, 236), (250, 178, 196), (122, 108, 210)], "accent": (236, 92, 140)},
    "noir":      {"grad": [(236, 236, 236), (148, 148, 148), (26, 26, 26)],  "accent": (245, 245, 245)},
    "paper":     {"grad": [(250, 244, 222), (236, 196, 150), (150, 110, 120)], "accent": (88, 140, 120)},
}


def _palette(style):
    p = PALETTES.get((style or "").lower().strip())
    if p:
        return p
    h = int(hashlib.sha256((style or "custom").encode()).hexdigest(), 16)
    def c(k):
        return ((h >> k) & 0x7f) + 90
    a = (c(0), c(5), c(11))
    b = tuple(max(0, v - 55) for v in a)
    d = tuple(max(0, v - 110) for v in a)
    return {"grad": [a, b, d], "accent": (min(255, c(3) + 60), min(255, c(7) + 30), c(13) & 0xff)}


def _font(size, bold=True):
    cands = ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"] if bold else ["DejaVuSans.ttf"]
    cands += ["arialbd.ttf" if bold else "arial.ttf"]
    for c in cands:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _gradient(w, h, stops):
    top, mid, bot = stops
    small = Image.new("RGB", (1, h))
    px = small.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = _lerp(top, mid, t * 2) if t < 0.5 else _lerp(mid, bot, (t - 0.5) * 2)
    return small.resize((w, h))


def _draw_person(dr, x, y, h, color):
    head = h * 0.16
    dr.ellipse([x - head / 2, y - h, x + head / 2, y - h + head], fill=color)
    dr.rounded_rectangle([x - h * 0.16, y - h + head * 0.95, x + h * 0.16, y], radius=h * 0.08, fill=color)


def _wrap(dr, text, font, max_w):
    words, lines, cur = (text or "").split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if dr.textlength(t, font=font) <= max_w:
            cur = t
        else:
            lines.append(cur)
            cur = w
            if len(lines) == 2:
                break
    lines.append(cur + (" …" if len(lines) >= 3 and len(words) > 0 else ""))
    return [l for l in lines if l][:3]


def paint(path, seed_key, style, scene_id, title, prompt, rev=1, w=1280, h=720):
    rng = random.Random(f"{seed_key}|{scene_id}|r{rev}")
    pal = _palette(style)
    img = _gradient(w, h, pal["grad"])
    dr = ImageDraw.Draw(img, "RGBA")
    A = pal["accent"]
    dark = pal["grad"][-1]

    # sun / hero disc with glow
    sx, sy = rng.uniform(0.18, 0.82) * w, rng.uniform(0.16, 0.4) * h
    srad = rng.uniform(0.06, 0.13) * h
    for g in range(14, 0, -1):
        a = int(10 * (15 - g))
        dr.ellipse([sx - srad * g / 3, sy - srad * g / 3, sx + srad * g / 3, sy + srad * g / 3], fill=(*A, a))
    dr.ellipse([sx - srad, sy - srad, sx + srad, sy + srad], fill=tuple(min(255, c + 40) for c in A))

    # layered hills
    for i, (yb, amp) in enumerate([(0.58, 0.05), (0.7, 0.06), (0.84, 0.07)]):
        pts, base_y = [], yb * h
        for x in range(0, w + 40, 40):
            pts.append((x, base_y + math.sin(x / w * math.pi * rng.uniform(1.5, 3) + rng.uniform(0, 6)) * amp * h))
        shade = _lerp(dark, (0, 0, 0), 0.15 * i)
        dr.polygon(pts + [(w, h), (0, h)], fill=(*shade, 235))

    # subject silhouette + product block when people/things are implied
    lowp = (prompt or "").lower()
    if any(k in lowp for k in ["maya", "leo", "nina", "theo", "person", "direct to camera", "hand", "protagon"]):
        px_, ph = rng.uniform(0.3, 0.55) * w, h * rng.uniform(0.26, 0.34)
        _draw_person(dr, px_, h * 0.86, ph, _lerp(dark, (0, 0, 0), 0.35))
        bx, by, bs = px_ + ph * 0.42, h * 0.86 - ph * 0.34, ph * 0.2
        dr.rounded_rectangle([bx, by, bx + bs, by + bs * 1.25], radius=bs * 0.15, fill=(*A, 255))
        dr.rectangle([bx, by, bx + bs, by + bs * 0.28], fill=(255, 255, 255, 60))

    # film grain + vignette
    noise = Image.effect_noise((w // 2, h // 2), 22).convert("L").resize((w, h))
    img = Image.composite(img, Image.new("RGB", (w, h), (128, 128, 128)), noise.point(lambda v: int(abs(v - 128) * 0.35) + 250))
    vin = Image.new("L", (w, h), 0)
    vd = ImageDraw.Draw(vin)
    vd.ellipse([-w * 0.25, -h * 0.25, w * 1.25, h * 1.25], fill=255)
    vin = ImageOps.invert(vin.filter(ImageFilter.GaussianBlur(h * 0.18))).point(lambda v: int(v * 0.42))
    img.paste(Image.new("RGB", (w, h), (0, 0, 0)), (0, 0), vin)
    dr = ImageDraw.Draw(img, "RGBA")

    # caption band
    band_h = int(h * 0.22)
    dr.rounded_rectangle([18, h - band_h - 16, w - 18, h - 16], radius=18, fill=(12, 12, 14, 150))
    f_sm, f_bd = _font(24), _font(30, bold=True)
    ty = h - band_h + 2
    for line in _wrap(dr, prompt, f_sm, w - 320):
        dr.text((40, ty), line, font=f_sm, fill=(238, 236, 232))
        ty += 30

    # chips: scene id, title, style, rev
    f_chip = _font(26, bold=True)
    dr.rounded_rectangle([18, 16, 150, 62], radius=14, fill=(12, 12, 14, 170))
    dr.text((34, 24), scene_id, font=f_chip, fill=(255, 255, 255))
    f_t = _font(40, bold=True)
    dr.text((170, 20), (title or "")[:34], font=f_t, fill=(250, 250, 250))
    style_txt, rev_txt = (style or "custom").upper(), f"r{rev}"
    sw = dr.textlength(style_txt, font=_font(22, bold=True))
    dr.rounded_rectangle([w - sw - 130, 16, w - 18, 56], radius=14, fill=(*A, 220))
    dr.text((w - sw - 96, 22), f"{style_txt} · {rev_txt}", font=_font(22, bold=True), fill=(20, 18, 16))

    dr.rounded_rectangle([8, 8, w - 8, h - 8], radius=16, outline=(255, 255, 255, 40), width=2)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.convert("RGB").save(path, "PNG")
    return path


# ---------------------------------------------------------------- live providers

def generate_live(prompt, out_path, cfg):
    """Live image generation via configured provider.
    Contract: must always include @elements refs in `prompt` when Higgsfield MCP is the provider."""
    kind = cfg["providers"]["image"].get("kind")

    if kind == "openai":
        import requests, base64
        key = cfg["providers"]["image"].get("api_key", "")
        r = requests.post("https://api.openai.com/v1/images/generations",
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          json={"model": cfg["providers"]["image"].get("model") or "gpt-image-1",
                                "prompt": prompt, "size": "1536x1024", "n": 1}, timeout=180)
        r.raise_for_status()
        b64 = r.json()["data"][0]["b64_json"]
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as f:
            f.write(base64.b64decode(b64))
        return out_path

    if kind == "huggingface":
        return _hf_text_to_image(prompt, out_path, cfg)

    if kind == "picsart":
        return _picsart_text_to_image(prompt, out_path, cfg)

    if kind == "stability":
        return _stability_text_to_image(prompt, out_path, cfg)

    raise RuntimeError(f"Live image provider '{kind}' not wired — use Demo mode or select a supported provider in Settings.")


def _stability_text_to_image(prompt, out_path, cfg):
    """Stability AI SDXL 1.0 text-to-image.

    Official legacy SDXL endpoint pattern:
      POST https://api.stability.ai/v1/generation/{engine_id}/text-to-image

    Cheap test defaults:
      - samples = 1
      - steps   = 10
      - cfg     = 5

    Aspect ratio is mapped to the nearest official SDXL 1.0 supported size:
      16:9 -> 1344x768
      9:16 -> 768x1344
      1:1  -> 1024x1024
      4:5  -> 896x1152
    """
    import requests
    import base64

    prov = cfg["providers"]["image"]
    key = prov.get("api_key", "").strip()
    if not key:
        raise RuntimeError("Stability API key missing — paste it in Settings → Image → API key.")

    engine_id = prov.get("model") or "stable-diffusion-xl-1024-v1-0"
    ratio = cfg.get("aspect_ratio") or prov.get("aspect_ratio") or "16:9"
    WH = {
        "16:9": (1344, 768),
        "9:16": (768, 1344),
        "1:1":  (1024, 1024),
        "4:5":  (896, 1152),
    }
    width, height = WH.get(ratio, (1024, 1024))

    steps = int(prov.get("stability_steps") or 10)
    steps = max(10, min(steps, 50))
    cfg_scale = float(prov.get("stability_cfg_scale") or 5)
    cfg_scale = max(0, min(cfg_scale, 35))

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    payload = {
        "text_prompts": [{"text": prompt, "weight": 1}],
        "cfg_scale": cfg_scale,
        "height": height,
        "width": width,
        "samples": 1,
        "steps": steps,
    }

    url = f"https://api.stability.ai/v1/generation/{engine_id}/text-to-image"
    r = requests.post(url, headers=headers, json=payload, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Stability error {r.status_code}: {r.text[:400]}")

    data = r.json()
    artifacts = data.get("artifacts") or []
    if not artifacts:
        raise RuntimeError(f"Stability returned no artifacts: {data}")

    b64 = artifacts[0].get("base64")
    if not b64:
        finish_reason = artifacts[0].get("finish_reason")
        raise RuntimeError(f"Stability returned no image base64 (finish_reason={finish_reason})")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(b64))
    return out_path


def _picsart_text_to_image(prompt, out_path, cfg):
    """PicsArt GenAI Text2Image — asynchronous (POST → poll GET → download).

    Flow:
      1. POST https://genai-api.picsart.io/v1/text2image  → 202 + {inference_id}
      2. GET  https://genai-api.picsart.io/v1/text2image/inferences/{inference_id}
             poll until status == "success" (or error)
      3. Download data[0].url and write to out_path.

    API key goes in header X-Picsart-API-Key (paat-…).
    """
    import requests
    import time

    prov = cfg["providers"]["image"]
    key = prov.get("api_key", "").strip()
    if not key:
        raise RuntimeError("PicsArt API key missing — paste your paat-… token in Settings → Image → API key.")

    model = prov.get("model") or "urn:air:fluxai:model:fluxai:flux-2-pro@1"
    # Derive width/height from the project's aspect ratio stored in config
    ratio = prov.get("aspect_ratio") or cfg.get("aspect_ratio") or "16:9"
    WH = {
        "16:9":  (1024, 576),
        "9:16":  (576, 1024),
        "1:1":   (1024, 1024),
        "4:5":   (819, 1024),
    }
    width, height = WH.get(ratio, (1024, 1024))

    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "X-Picsart-API-Key": key,
    }
    payload = {
        "prompt": prompt,
        "model": model,
        "width": width,
        "height": height,
        "count": 1,
    }

    # ── Step 1: submit
    r = requests.post("https://genai-api.picsart.io/v1/text2image",
                      json=payload, headers=headers, timeout=30)
    if r.status_code not in (200, 202):
        raise RuntimeError(f"PicsArt submit error {r.status_code}: {r.text[:300]}")

    body = r.json()
    inference_id = body.get("inference_id") or body.get("data", {}).get("inference_id")
    if not inference_id:
        # Some responses return the image immediately (200 synchronous path)
        url = (body.get("data") or [{}])[0].get("url") if isinstance(body.get("data"), list) else None
        if url:
            return _download_image(url, out_path)
        raise RuntimeError(f"PicsArt: no inference_id in response: {body}")

    # ── Step 2: poll
    poll_url = f"https://genai-api.picsart.io/v1/text2image/inferences/{inference_id}"
    max_wait, interval = 300, 4          # up to 5 min, poll every 4 s
    waited = 0
    while waited < max_wait:
        time.sleep(interval)
        waited += interval
        pr = requests.get(poll_url, headers=headers, timeout=30)
        if pr.status_code not in (200, 202):
            raise RuntimeError(f"PicsArt poll error {pr.status_code}: {pr.text[:300]}")
        pb = pr.json()
        status = pb.get("status") or pb.get("data", {}).get("status")
        if status == "success":
            data = pb.get("data")
            url = (data[0].get("url") if isinstance(data, list) else data.get("url")) if data else None
            if not url:
                raise RuntimeError(f"PicsArt success but no image URL in response: {pb}")
            return _download_image(url, out_path)
        if status and status not in ("queued", "processing", "accepted"):
            raise RuntimeError(f"PicsArt generation failed — status: {status} — body: {pb}")

    raise RuntimeError(f"PicsArt generation timed out after {max_wait}s (inference_id={inference_id})")


def _download_image(url, out_path):
    """Download an image from a URL and save it to out_path."""
    import requests
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(r.content)
    return out_path


def _hf_text_to_image(prompt, out_path, cfg):
    """Generate an image via Hugging Face Inference Client (text_to_image).
    Uses provider="auto" for serverless routing through fal / replicate / etc."""
    from huggingface_hub import InferenceClient

    prov = cfg["providers"]["image"]
    token = prov.get("api_key", "")
    if not token:
        raise RuntimeError("HuggingFace token missing — paste it in Settings → Image → API key.")
    model = prov.get("model") or "black-forest-labs/FLUX.1-dev"
    hf_provider = prov.get("hf_provider") or "auto"

    client = InferenceClient(provider=hf_provider, api_key=token)
    image = client.text_to_image(
        prompt,
        model=model,
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    image.save(out_path)
    return out_path
