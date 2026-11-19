#!/usr/bin/env python3
"""Render SynetScan's app icon (radar on a blue disc) at all sizes DSM uses."""
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 1024


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(len(a)))


def render():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # drop shadow
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse((90, 120, S - 90, S - 60), fill=(10, 40, 80, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(28)))

    # disc with vertical gradient
    grad = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(grad)
    top, bottom = (54, 170, 255), (4, 102, 214)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(top, bottom, y / S) + (255,))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).ellipse((80, 80, S - 80, S - 80), fill=255)
    img.paste(grad, (0, 0), mask)

    d = ImageDraw.Draw(img)
    cx = cy = S // 2
    # sweep (sector with fading alpha)
    sweep = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sweep)
    r = 330
    for i in range(70):
        a0 = -100 + i
        alpha = int(190 * (i / 70) ** 1.5)
        sd.pieslice((cx - r, cy - r, cx + r, cy + r), a0, a0 + 1.5, fill=(255, 255, 255, alpha))
    sweep = Image.composite(sweep, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask)
    img.alpha_composite(sweep)

    # rings
    for rr, w, a in ((330, 22, 235), (220, 20, 210), (110, 20, 190)):
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), outline=(255, 255, 255, a), width=w)
    # sweep line
    ang = math.radians(-30)
    d.line([(cx, cy), (cx + r * math.cos(ang), cy + r * math.sin(ang))], fill=(255, 255, 255, 255), width=24)
    # device blips
    for (rr, deg, size, col) in ((270, -150, 30, (255, 255, 255)), (165, 40, 26, (255, 255, 255)),
                                 (275, 115, 30, (255, 200, 70)), (250, -60, 26, (255, 255, 255))):
        x = cx + rr * math.cos(math.radians(deg))
        y = cy + rr * math.sin(math.radians(deg))
        d.ellipse((x - size * 1.7, y - size * 1.7, x + size * 1.7, y + size * 1.7), fill=col + (70,))
        d.ellipse((x - size, y - size, x + size, y + size), fill=col + (255,))
    d.ellipse((cx - 34, cy - 34, cx + 34, cy + 34), fill=(255, 255, 255, 255))

    # subtle top highlight
    hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(hl).ellipse((150, 95, S - 150, S * 0.55), fill=(255, 255, 255, 38))
    hl = Image.composite(hl, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask)
    img.alpha_composite(hl.filter(ImageFilter.GaussianBlur(20)))
    return img


def main(out_ui, out_pkg):
    big = render()
    os.makedirs(out_ui, exist_ok=True)
    os.makedirs(out_pkg, exist_ok=True)
    for size in (16, 24, 32, 48, 64, 72, 96, 128, 256):
        im = big.resize((size, size), Image.LANCZOS)
        if size <= 32:  # crisper small sizes
            im = Image.alpha_composite(Image.new("RGBA", im.size, (0, 0, 0, 0)), im)
        im.save(os.path.join(out_ui, "icon_%d.png" % size), optimize=True)
    big.resize((64, 64), Image.LANCZOS).save(os.path.join(out_pkg, "PACKAGE_ICON.PNG"), optimize=True)
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(out_pkg, "PACKAGE_ICON_256.PNG"), optimize=True)
    print("icons written")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "src/ui/images", sys.argv[2] if len(sys.argv) > 2 else "spk")
