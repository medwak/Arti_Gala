"""Draw the launcher icon (a stylised mask) at every Android density. Needs Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = {"mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192}
BG = (154, 74, 28, 255)
FACE = (243, 228, 216, 255)
DARK = (58, 30, 14, 255)
SCALE = 4  # draw large, then downsample for smooth edges


def draw(size: int) -> Image.Image:
    s = size * SCALE
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=s * 0.22, fill=BG)
    # face
    d.ellipse([s * 0.28, s * 0.12, s * 0.72, s * 0.90], fill=FACE)
    # eyes: narrow slits
    for cx in (0.41, 0.59):
        d.ellipse([s * (cx - 0.07), s * 0.40, s * (cx + 0.07), s * 0.46], fill=DARK)
    # brow ridge
    d.line([s * 0.33, s * 0.34, s * 0.67, s * 0.34], fill=DARK, width=max(1, int(s * 0.025)))
    # nose
    d.line([s * 0.50, s * 0.36, s * 0.50, s * 0.62], fill=DARK, width=max(1, int(s * 0.03)))
    # mouth
    d.rounded_rectangle([s * 0.43, s * 0.70, s * 0.57, s * 0.75], radius=s * 0.02, fill=DARK)
    # forehead mark
    d.ellipse([s * 0.475, s * 0.19, s * 0.525, s * 0.24], fill=BG)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    res = Path(__file__).parent / "res"
    for density, size in SIZES.items():
        out = res / f"mipmap-{density}" / "ic_launcher.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        draw(size).save(out, optimize=True)
    draw(512).save(Path(__file__).parent / "icon-512.png", optimize=True)


if __name__ == "__main__":
    main()
