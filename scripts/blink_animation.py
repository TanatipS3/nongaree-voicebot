"""Animate Aree's eyes blinking from the avatar_extraction eye frames.

The ``avatar_extraction/botset/eyes`` folder holds five SVG frames that form a
single blink, from fully open to closed and back:

    eye 1 = open   eye 2 = half   eye 3 = closed   eye 4 = half   eye 5 = open

This script rasterizes those SVGs to PNG using macOS Quick Look (``qlmanage`` —
no extra dependencies), crops them to the eye, and plays the blink. By default
it opens a Tkinter window showing two eyes that blink at natural random
intervals. Pass ``--gif out.gif`` to export an animated GIF instead.

Usage (run from the repo root):
    python scripts/blink_animation.py                # live window
    python scripts/blink_animation.py --gif blink.gif
    python scripts/blink_animation.py --render-size 1800 --eye-height 240
"""

from __future__ import annotations

import argparse
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# Repo root is one level up from this scripts/ folder.
EYES_DIR = Path(__file__).resolve().parent.parent / "avatar_extraction" / "botset" / "eyes"

# Frame order from open -> closed -> open. The middle frame (index 2) is the
# fully-closed eye; both ends are open, so we can ping-pong between them.
FRAME_NAMES = ["eye 1.svg", "eye 2.svg", "eye 3.svg", "eye 4.svg", "eye 5.svg"]

try:  # Pillow >= 9.1
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # older Pillow
    RESAMPLE = Image.LANCZOS


def rasterize(svg: Path, out_dir: Path, size: int) -> Path:
    """Render an SVG to PNG via macOS Quick Look, returning the PNG path."""
    out_png = out_dir / (svg.name + ".png")
    if out_png.exists():
        return out_png
    result = subprocess.run(
        ["qlmanage", "-t", "-s", str(size), "-o", str(out_dir), str(svg)],
        capture_output=True,
        text=True,
    )
    if not out_png.exists():
        raise RuntimeError(
            f"qlmanage failed to render {svg.name}:\n{result.stdout}\n{result.stderr}"
        )
    return out_png


def drop_white_background(img: Image.Image) -> Image.Image:
    """Flood-fill the white card behind the eye to transparency.

    ``qlmanage`` composites SVGs onto an opaque white canvas, so the eye sits on
    a white square. We flood from the borders and clear connected near-white
    pixels — flooding (rather than a global white knockout) keeps the white
    highlight dots *inside* the eye, since they're walled off by blue.
    """
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size

    def is_bg(x: int, y: int) -> bool:
        r, g, b, a = px[x, y]
        # Pure-ish white only: the cyan glow keeps b high but drops r, so the
        # >=235-on-every-channel test protects it.
        return a > 0 and r >= 235 and g >= 235 and b >= 235

    stack = [(x, 0) for x in range(w)]
    stack += [(x, h - 1) for x in range(w)]
    stack += [(0, y) for y in range(h)]
    stack += [(w - 1, y) for y in range(h)]

    while stack:
        x, y = stack.pop()
        if not (0 <= x < w and 0 <= y < h) or not is_bg(x, y):
            continue
        px[x, y] = (255, 255, 255, 0)
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))

    return img


def load_frames(render_size: int, eye_height: int) -> list[Image.Image]:
    """Rasterize, crop to the eye, and uniformly size every blink frame."""
    if not EYES_DIR.is_dir():
        sys.exit(f"Eye frames not found: {EYES_DIR}")

    cache = Path(tempfile.gettempdir()) / "aree_blink_frames"
    cache.mkdir(exist_ok=True)

    # Render crisp, then work on a smaller copy so the border flood-fill stays
    # fast. The final downscale to eye_height keeps edges sharp.
    work_h = max(eye_height, 480)
    images = []
    for name in FRAME_NAMES:
        raw = Image.open(rasterize(EYES_DIR / name, cache, render_size)).convert("RGBA")
        scale = work_h / raw.height
        work = raw.resize((round(raw.width * scale), work_h), RESAMPLE)
        images.append(drop_white_background(work))

    # After background removal the eye is the only opaque region. Use the union
    # of every frame's box so the eye stays put instead of jumping around as it
    # opens and closes.
    union = None
    for img in images:
        box = img.getbbox()
        if box is None:
            continue
        if union is None:
            union = box
        else:
            union = (
                min(union[0], box[0]),
                min(union[1], box[1]),
                max(union[2], box[2]),
                max(union[3], box[3]),
            )
    if union is None:
        sys.exit("Eye frames appear to be empty after rendering.")

    cropped = [img.crop(union) for img in images]

    # Scale so every frame shares one height, preserving the open eye's width.
    crop_w = union[2] - union[0]
    crop_h = union[3] - union[1]
    scale = eye_height / crop_h
    target = (max(1, round(crop_w * scale)), eye_height)
    return [img.resize(target, RESAMPLE) for img in cropped]


def blink_sequence() -> list[int]:
    """Frame indices for one blink: open -> closed -> open."""
    return list(range(len(FRAME_NAMES)))


def export_gif(frames: list[Image.Image], path: Path, gap: int, bg: str) -> None:
    """Write a looping GIF: a pause on the open eye, then one blink."""
    eye_w, eye_h = frames[0].size
    canvas_w = eye_w * 2 + gap
    pad = eye_h // 2
    size = (canvas_w + pad * 2, eye_h + pad * 2)

    def compose(left: Image.Image) -> Image.Image:
        right = left.transpose(Image.FLIP_LEFT_RIGHT)
        canvas = Image.new("RGBA", size, bg)
        canvas.alpha_composite(left, (pad, pad))
        canvas.alpha_composite(right, (pad + eye_w + gap, pad))
        return canvas.convert("P", palette=Image.ADAPTIVE)

    open_eye = compose(frames[0])
    blink = [compose(frames[i]) for i in blink_sequence()]

    # Hold the open eye, then run the blink fast.
    sequence = [open_eye] * 28 + blink
    durations = [40] * 28 + [45] * len(blink)

    sequence[0].save(
        path,
        save_all=True,
        append_images=sequence[1:],
        duration=durations,
        loop=0,
        disposal=2,
    )
    print(f"Wrote {path} ({len(sequence)} frames)")


def run_window(frames: list[Image.Image], gap: int, bg: str) -> None:
    """Open a Tkinter window of two eyes that blink at random intervals."""
    import tkinter as tk
    from PIL import ImageTk

    eye_w, eye_h = frames[0].size
    pad = eye_h // 2
    canvas_w = eye_w * 2 + gap + pad * 2
    canvas_h = eye_h + pad * 2

    root = tk.Tk()
    root.title("Aree — blink")
    root.configure(bg=bg)
    canvas = tk.Canvas(root, width=canvas_w, height=canvas_h, bg=bg, highlightthickness=0)
    canvas.pack()

    # Keep references so Tk doesn't garbage-collect the images.
    left_photos = [ImageTk.PhotoImage(f) for f in frames]
    right_photos = [ImageTk.PhotoImage(f.transpose(Image.FLIP_LEFT_RIGHT)) for f in frames]

    left_id = canvas.create_image(pad, pad, anchor="nw", image=left_photos[0])
    right_id = canvas.create_image(pad + eye_w + gap, pad, anchor="nw", image=right_photos[0])

    sequence = blink_sequence()

    def show(frame_idx: int) -> None:
        canvas.itemconfig(left_id, image=left_photos[frame_idx])
        canvas.itemconfig(right_id, image=right_photos[frame_idx])

    def play_blink(step: int = 0) -> None:
        if step < len(sequence):
            show(sequence[step])
            root.after(45, play_blink, step + 1)
        else:
            show(0)
            schedule_blink()

    def schedule_blink() -> None:
        # Occasionally double-blink; otherwise wait a natural pause.
        if random.random() < 0.15:
            root.after(180, play_blink)
        else:
            root.after(random.randint(1800, 5000), play_blink)

    schedule_blink()
    root.bind("<Escape>", lambda _e: root.destroy())
    root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Animate Aree's eyes blinking.")
    parser.add_argument("--gif", type=Path, help="Export an animated GIF instead of opening a window.")
    parser.add_argument("--render-size", type=int, default=1400, help="SVG rasterization size (px, longest side).")
    parser.add_argument("--eye-height", type=int, default=220, help="On-screen height of each eye (px).")
    parser.add_argument("--gap", type=int, default=60, help="Gap between the two eyes (px).")
    parser.add_argument("--bg", default="#0d1b24", help="Background color.")
    args = parser.parse_args()

    frames = load_frames(args.render_size, args.eye_height)

    if args.gif:
        export_gif(frames, args.gif, args.gap, args.bg)
    else:
        run_window(frames, args.gap, args.bg)


if __name__ == "__main__":
    main()
