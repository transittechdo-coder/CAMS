"""Draw the CAMS app icon as installer/cams.ico (used by the .exe and installer)."""

from pathlib import Path

from PIL import Image, ImageDraw

INK, TEAL, AMBER = (20, 48, 74), (11, 122, 117), (227, 155, 18)


def draw(size: int) -> Image.Image:
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(14 * s), fill=INK)
    d.line([(14 * s, 44 * s), (32 * s, 14 * s), (50 * s, 44 * s), (14 * s, 44 * s)], fill=TEAL, width=max(1, int(4 * s)), joint="curve")
    r = 8 * s
    d.ellipse([32 * s - r, 36 * s - r, 32 * s + r, 36 * s + r], fill=AMBER)
    r = 3 * s
    d.ellipse([32 * s - r, 36 * s - r, 32 * s + r, 36 * s + r], fill=INK)
    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "installer" / "cams.ico"
    big = draw(256)
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
