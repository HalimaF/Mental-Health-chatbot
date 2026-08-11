"""Generate the PWA icon set from the brand mark.

The manifest referenced eight icons that were never created, so every one of
them 404'd and "Add to Home Screen" produced a blank tile. Run this after any
brand change:

    python tools/make_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"
SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

GRAD_TOP = (42, 122, 95)     # --brand-2  #2A7A5F
GRAD_BOTTOM = (31, 95, 75)   # --brand    #1F5F4B


def rounded_gradient(size: int, radius_ratio: float, pad_ratio: float) -> Image.Image:
    """A rounded square filled with a vertical brand gradient."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    grad = Image.new("RGBA", (size, size))
    gd = ImageDraw.Draw(grad)
    for y in range(size):
        t = y / max(size - 1, 1)
        gd.line(
            [(0, y), (size, y)],
            fill=tuple(
                round(a + (b - a) * t) for a, b in zip(GRAD_TOP, GRAD_BOTTOM, strict=False)
            ) + (255,),
        )

    pad = round(size * pad_ratio)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [pad, pad, size - pad - 1, size - pad - 1],
        radius=round(size * radius_ratio),
        fill=255,
    )
    img.paste(grad, (0, 0), mask)
    return img


def draw_heart(img: Image.Image, size: int, scale: float) -> None:
    """Two lobes plus a tapering point — the same mark as the header."""
    d = ImageDraw.Draw(img)
    w = size * scale
    cx, cy = size / 2, size / 2
    top = cy - w * 0.34
    lobe_r = w * 0.27
    left_c = (cx - lobe_r * 0.92, top + lobe_r * 0.52)
    right_c = (cx + lobe_r * 0.92, top + lobe_r * 0.52)
    white = (255, 255, 255, 255)

    for c in (left_c, right_c):
        d.ellipse([c[0] - lobe_r, c[1] - lobe_r, c[0] + lobe_r, c[1] + lobe_r], fill=white)

    d.polygon(
        [
            (left_c[0] - lobe_r * 0.99, left_c[1] + lobe_r * 0.12),
            (right_c[0] + lobe_r * 0.99, right_c[1] + lobe_r * 0.12),
            (cx, cy + w * 0.47),
        ],
        fill=white,
    )


def build(size: int, maskable: bool = False) -> Image.Image:
    # Maskable icons get squeezed into a circle by the launcher, so the mark
    # needs to sit inside the ~80% safe zone.
    ss = size * 4  # supersample, then downscale for clean edges
    img = rounded_gradient(ss, radius_ratio=0.0 if maskable else 0.22, pad_ratio=0.0)
    draw_heart(img, ss, scale=0.46 if maskable else 0.62)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        build(size).save(OUT / f"icon-{size}x{size}.png", optimize=True)
    build(512, maskable=True).save(OUT / "icon-maskable-512x512.png", optimize=True)
    build(180).save(OUT / "apple-touch-icon.png", optimize=True)
    print(f"Wrote {len(SIZES) + 2} icons to {OUT}")


if __name__ == "__main__":
    main()
