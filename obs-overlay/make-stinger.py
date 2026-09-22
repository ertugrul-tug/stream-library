"""Create the transparent compass stinger. Requires Pillow and ffmpeg on PATH."""
import math
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
W, H, FPS, COUNT = 1280, 720, 60, 72
FONT = Path("C:/Windows/Fonts/arialbd.ttf")
font_big = ImageFont.truetype(str(FONT), 62)
font_small = ImageFont.truetype(str(FONT), 18)


def ease(x):
    x = min(1, max(0, x))
    return x * x * (3 - 2 * x)


def frame(n):
    t = n / (COUNT - 1)
    image = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    if t < .5:
        edge = -200 + (W + 400) * ease(t / .5)
        d.polygon([(0, 0), (edge + 130, 0), (edge - 130, H), (0, H)], fill=(6, 15, 27, 255))
    elif t < .58:
        edge = W + 200
        d.rectangle((0, 0, W, H), fill=(6, 15, 27, 255))
    else:
        edge = -200 + (W + 400) * ease((t - .58) / .42)
        d.polygon([(edge - 130, 0), (W, 0), (W, H), (edge + 130, H)], fill=(6, 15, 27, 255))
    # Streaks and port/starboard lines move with the cover.
    shift = int((t - .5) * 180)
    for i, color in enumerate(((145, 70, 255, 170), (34, 174, 240, 200), (83, 252, 24, 150))):
        x = edge + shift - 75 + i * 35
        d.polygon([(x - 50, 0), (x - 22, 0), (x + 105, H), (x + 77, H)], fill=color)
    opacity = int(255 * min(1, max(0, (t - .23) / .17), max(0, (.84 - t) / .17)))
    if opacity:
        cx, cy = W // 2, H // 2
        radius = 145
        d.ellipse((cx-radius, cy-radius, cx+radius, cy+radius), outline=(47, 192, 245, opacity), width=4)
        d.ellipse((cx-radius+18, cy-radius+18, cx+radius-18, cy+radius-18), outline=(188, 230, 247, opacity//2), width=2)
        angle = (t * 2.5 - .8) * math.pi
        dx, dy = math.cos(angle)*105, math.sin(angle)*105
        d.line((cx-dx, cy-dy, cx+dx, cy+dy), fill=(239, 248, 255, opacity), width=8)
        d.polygon([(cx+dx, cy+dy), (cx+dy*.18,cy-dx*.18), (cx-dy*.18,cy+dx*.18)], fill=(255, 61, 127, opacity))
        d.text((cx, cy+190), "KAPTAN QEDY", font=font_big, anchor="mm", fill=(245, 250, 255, opacity), stroke_width=1)
        d.text((cx, cy+239), "YENİ ROTA · AYNI MÜRETTEBAT", font=font_small, anchor="mm", fill=(113, 210, 248, opacity))
    return image


def main():
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for n in range(COUNT):
            frame(n).save(folder / f"f{n:03}.png")
        output = ROOT / "pusula-gecis.webm"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS),
                        "-i", str(folder / "f%03d.png"), "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "30",
                        "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(output)], check=True)
        print(f"Created {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
