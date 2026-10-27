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


def splash() -> Image.Image:
    """Loading picture shown the instant CAMS.exe is opened."""
    from PIL import ImageFont

    w, h = 520, 300
    img = Image.new("RGB", (w, h), INK)
    d = ImageDraw.Draw(img)
    # faint site-plan grid
    for x in range(0, w, 26):
        d.line([(x, 0), (x, h)], fill=(30, 60, 88))
    for y in range(0, h, 26):
        d.line([(0, y), (w, y)], fill=(30, 60, 88))
    img.paste(draw(96), (40, 70), draw(96))

    def font(size, bold=False):
        for name in (("bahnschrift.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf") if bold else ("segoeui.ttf", "DejaVuSans.ttf")):
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    d.text((156, 78), "CAMS", font=font(54, True), fill=(227, 236, 239))
    d.text((158, 144), "Camera AI Monitoring System", font=font(19), fill=(169, 188, 198))
    d.rectangle([40, 214, 480, 217], fill=(30, 60, 88))
    d.rectangle([40, 214, 200, 217], fill=TEAL)
    d.text((40, 268), "TransitTech  |  Godwill Andrew Madunda", font=font(12), fill=(116, 137, 154))
    return img


def main() -> None:
    folder = Path(__file__).resolve().parent.parent / "installer"
    out = folder / "cams.ico"
    big = draw(256)
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    splash().save(folder / "splash.png")
    print(f"wrote {out} and splash.png")


if __name__ == "__main__":
    main()
