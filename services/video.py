"""
video.py — video generation layer.

Demo mode: renders an animated preview clip (GIF) from the approved still with a
Ken-Burns move + light sweep + grain — motion direction seeded per (scene, rev),
so Reroll visibly changes the move. Live mode: route the same contract to
Higgsfield / HeyGen and store the returned mp4.
"""

import os
import math
import random
from PIL import Image, ImageDraw, ImageFilter

PATTERNS = ["pan-right", "pan-left", "push-in", "pull-out", "tilt-up", "drift-diag"]


def _frame(base, box, w, h):
    return base.resize((760, 428)).crop(box).resize((w, h), Image.LANCZOS)


def render_clip(image_path, out_gif, seed_key, motion_desc="", frames=40, w=640, h=360):
    rng = random.Random(f"clip|{seed_key}")
    base = Image.open(image_path).convert("RGB").resize((760, 428), Image.LANCZOS)
    pattern = PATTERNS[rng.randrange(len(PATTERNS))]

    sw, sh = 640, 360
    def box_at(t):
        if pattern in ("push-in", "pull-out"):
            z0, z1 = (1.0, 0.88) if pattern == "push-in" else (0.88, 1.0)
            z = z0 + (z1 - z0) * t
            cw, ch = sw * z, sh * z
            return ((760 - cw) / 2, (428 - ch) / 2, (760 + cw) / 2, (428 + ch) / 2)
        span_x, span_y = 760 - sw, 428 - sh
        if pattern == "pan-right":
            x, y = span_x * t, span_y * 0.5
        elif pattern == "pan-left":
            x, y = span_x * (1 - t), span_y * 0.5
        elif pattern == "tilt-up":
            x, y = span_x * 0.5, span_y * (1 - t)
        else:
            x, y = span_x * t, span_y * t
        return (x, y, x + sw, y + sh)

    noise = Image.effect_noise((w // 2, h // 2), 26).convert("L").resize((w, h))
    noise_a = noise.point(lambda v: int(abs(v - 128) * 0.32) + 246)
    imgs = []
    sweep_x0 = rng.uniform(-0.3, 0.2) * w
    for i in range(frames):
        t = i / max(1, frames - 1)
        fr = _frame(base, box_at(t), w, h).convert("RGBA")
        fr = Image.composite(fr, Image.new("RGBA", (w, h), (128, 128, 128, 255)), noise_a)
        # light sweep
        ov = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        sx = sweep_x0 + (w + 320) * t
        od.polygon([(sx, -20), (sx + 90, -20), (sx - 120, h + 20), (sx - 210, h + 20)], fill=(255, 255, 255, 16))
        fr = Image.alpha_composite(fr, ov.filter(ImageFilter.GaussianBlur(6)))
        imgs.append(fr.convert("P", palette=Image.ADAPTIVE, colors=256))

    os.makedirs(os.path.dirname(out_gif), exist_ok=True)
    imgs[0].save(out_gif, save_all=True, append_images=imgs[1:], duration=85, loop=0, optimize=True)
    return out_gif, pattern


# ---------------------------------------------------------------- live providers

def generate_live(image_path, motion_prompt, out_path, cfg):
    """Live clip generation via configured provider.
    Contract: image_path is the approved still; motion_prompt from services.llm.motion_prompt;
    write the resulting video to out_path. Batch orchestration stays in app.py (4 at a time)."""
    kind = cfg["providers"]["video"].get("kind")

    if kind == "huggingface":
        return _hf_image_to_video(image_path, motion_prompt, out_path, cfg)

    raise RuntimeError(f"Live video provider '{kind}' not wired — use Demo mode or select a supported provider in Settings.")


def _hf_image_to_video(image_path, motion_prompt, out_path, cfg):
    """Generate a video clip from an image + motion prompt via HF Inference Client."""
    from huggingface_hub import InferenceClient

    prov = cfg["providers"]["video"]

    token = prov.get("api_key", "")
    if not token:
        raise RuntimeError(
            "HuggingFace token missing — paste it in Settings → Video → API key."
        )

    model = prov.get("model") or "Wan-AI/Wan2.2-I2V-A14B"
    hf_provider = prov.get("hf_provider") or "auto"

    client = InferenceClient(
        provider=hf_provider,
        api_key=token,
    )

    with open(image_path, "rb") as f:
        input_image = f.read()

    video_bytes = client.image_to_video(
        input_image,
        prompt=motion_prompt,
        model=model,
    )

    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    with open(out_path, "wb") as f:
        f.write(video_bytes)

    return out_path