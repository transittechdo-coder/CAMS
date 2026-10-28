"""Draw the CAMS app icon as installer/cams.ico (used by the .exe and installer)."""

from pathlib import Path

from PIL import Image, ImageDraw

NAVY, TEAL, WHITE = (14, 29, 45), (0, 153, 140), (255, 255, 255)
SS = 4  # draw 4x larger, then shrink, for smooth edges


def _mark(d, s, ox=0.0, oy=0.0, ink=NAVY) -> None:
    """The CAMS mark on a 96-unit grid: teal corner brackets, navy C, teal dot."""
    P = lambda x, y: (ox + x * s, oy + y * s)
    w = max(1, round(4 * s))
    r = 7 * s
    for cx, cy, sx, sy in ((6, 6, 1, 1), (90, 6, -1, 1), (90, 90, -1, -1), (6, 90, 1, -1)):
        # straight arms
        d.line([P(cx, cy + sy * 7), P(cx, cy + sy * 22)], fill=TEAL, width=w)
        d.line([P(cx + sx * 7, cy), P(cx + sx * 22, cy)], fill=TEAL, width=w)
        # rounded corner
        x0, y0 = P(cx, cy)
        box = [min(x0, x0 + sx * 2 * r), min(y0, y0 + sy * 2 * r), max(x0, x0 + sx * 2 * r), max(y0, y0 + sy * 2 * r)]
        start = {(1, 1): 180, (-1, 1): 270, (-1, -1): 0, (1, -1): 90}[(sx, sy)]
        d.arc(box, start, start + 90, fill=TEAL, width=w)
        for ex, ey in ((cx, cy + sy * 22), (cx + sx * 22, cy)):  # round caps
            px, py = P(ex, ey)
            d.ellipse([px - w / 2, py - w / 2, px + w / 2, py + w / 2], fill=TEAL)
    # the C: ring from 38 to 322 degrees (open on the right), round ends
    cx, cy = P(47.5, 47.5)
    R, sw = 25.75 * s, 9.5 * s
    d.arc([cx - R - sw / 2, cy - R - sw / 2, cx + R + sw / 2, cy + R + sw / 2], 38, 322, fill=ink, width=round(sw))
    import math
    for a in (38, 322):
        ex, ey = cx + R * math.cos(math.radians(a)), cy + R * math.sin(math.radians(a))
        d.ellipse([ex - sw / 2, ey - sw / 2, ex + sw / 2, ey + sw / 2], fill=ink)
    px, py = P(67, 47.5)
    d.ellipse([px - 6 * s, py - 6 * s, px + 6 * s, py + 6 * s], fill=TEAL)


def draw(size: int, background: bool = True) -> Image.Image:
    big = size * SS
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if background:  # white tile so the navy C shows on dark desktops too
        d.rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.16), fill=WHITE)
        _mark(d, big / 96 * 0.86, big * 0.07, big * 0.07)
    else:
        _mark(d, big / 96)
    return img.resize((size, size), Image.LANCZOS)


def _font(size, bold=False):
    from PIL import ImageFont
    names = ("Inter-ExtraBold.ttf", "seguibl.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf") if bold \
        else ("Inter-Medium.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf")
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def logo(width: int = 600) -> Image.Image:
    """Full logo: mark + CAMS + Camera AI Management System (as on the brand sheet)."""
    k = width / 600
    big = Image.new("RGBA", (int(600 * k * SS), int(180 * k * SS)), (255, 255, 255, 255))
    d = ImageDraw.Draw(big)
    _mark(d, k * SS, 36 * k * SS, 42 * k * SS)
    d.text((158 * k * SS, 40 * k * SS), "CAMS", font=_font(int(74 * k * SS), True), fill=NAVY)
    d.text((162 * k * SS, 118 * k * SS), "Camera AI Management System", font=_font(int(16 * k * SS)), fill=NAVY)
    return big.resize((int(600 * k), int(180 * k)), Image.LANCZOS)


def splash() -> Image.Image:
    """Loading picture shown the instant CAMS.exe is opened."""
    w, h = 520, 300
    img = Image.new("RGB", (w, h), WHITE)
    lg = logo(460).convert("RGB")
    img.paste(lg, (20, 40))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 214, 480, 217], fill=(226, 232, 236))
    d.rectangle([40, 214, 200, 217], fill=TEAL)
    d.text((40, 268), "TransitTech  |  Godwill Andrew Madunda", font=_font(12), fill=(110, 125, 138))
    return img


def main() -> None:
    folder = Path(__file__).resolve().parent.parent / "installer"
    out = folder / "cams.ico"
    big = draw(256)
    big.save(out, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    splash().save(folder / "splash.png")
    docs = folder.parent / "docs" / "images"
    docs.mkdir(parents=True, exist_ok=True)
    splash().save(docs / "splash.png")
    logo(600).save(docs / "logo.png")
    draw(256, background=False).save(docs / "icon.png")
    print(f"wrote {out} and splash.png")


if __name__ == "__main__":
    main()
