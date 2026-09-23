"""Render an original 9:16 Kaptan Qedy Instagram Reel."""
import math
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
W, H, FPS, SECONDS = 720, 1280, 30, 13
N = FPS * SECONDS

FONT_BOLD = Path("C:/Windows/Fonts/bahnschrift.ttf")
FONT_REGULAR = Path("C:/Windows/Fonts/segoeui.ttf")
FONT_MONO = Path("C:/Windows/Fonts/consola.ttf")


def font(path, size):
    return ImageFont.truetype(str(path), size)


F_TITLE = font(FONT_BOLD, 72)
F_HUGE = font(FONT_BOLD, 92)
F_MID = font(FONT_BOLD, 42)
F_LABEL = font(FONT_MONO, 17)
F_BODY = font(FONT_REGULAR, 26)

logo = Image.open(ROOT / "docs/assets/logo_cat.png").convert("RGBA")
logo = ImageOps.fit(logo, (220, 220), method=Image.Resampling.LANCZOS)
preview = Image.open(ROOT / "obs-overlay/preview-show-all.jpg").convert("RGB")
preview = ImageOps.fit(preview, (620, 440), method=Image.Resampling.LANCZOS)

# Static vertical gradient.
arr = np.zeros((H, W, 3), dtype=np.uint8)
top = np.array([4, 10, 18.0])
bottom = np.array([10, 17, 29.0])
for y in range(H):
    mix = y / (H - 1)
    arr[y, :, :] = top * (1 - mix) + bottom * mix
base = Image.fromarray(arr, "RGB").convert("RGBA")


def clamp(x):
    return max(0.0, min(1.0, x))


def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def smooth(x):
    x = clamp(x)
    return x * x * (3 - 2 * x)


def phase(t, start, end):
    return clamp((t - start) / (end - start))


def alpha_window(t, start, fadein, end, fadeout):
    return min(phase(t, start, start + fadein), 1 - phase(t, end - fadeout, end))


def center_text(draw, xy, text, fnt, fill, spacing=4, stroke=0):
    draw.multiline_text(xy, text, font=fnt, fill=fill, anchor="mm", align="center",
                        spacing=spacing, stroke_width=stroke, stroke_fill=(3, 7, 13, fill[3]))


def glow_circle(frame, center, radius, color, opacity):
    layer = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(layer)
    d.ellipse((center[0]-radius, center[1]-radius, center[0]+radius, center[1]+radius),
              fill=(*color, int(opacity)))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    frame.alpha_composite(layer)


def paste_alpha(frame, item, xy, opacity=255):
    if opacity < 255:
        item = item.copy()
        item.putalpha(item.getchannel("A").point(lambda v: v * opacity // 255))
    frame.alpha_composite(item, xy)


def render(i):
    t = i / FPS
    frame = base.copy()
    d = ImageDraw.Draw(frame)

    # Brand glows and technical grid.
    glow_circle(frame, (130, 260), 220, (145, 70, 255), 23)
    glow_circle(frame, (620, 930), 280, (34, 174, 240), 18)
    for y in range((i * 2) % 80 - 80, H, 80):
        d.line((0, y, W, y), fill=(65, 135, 166, 15), width=1)
    for x in range(40, W, 80):
        d.line((x, 0, x, H), fill=(65, 135, 166, 11), width=1)

    # Stable particles.
    for k in range(34):
        x = (k * 137 + i * (0.22 + (k % 3) * .08)) % W
        y = (k * 251 - i * (0.16 + (k % 5) * .04)) % H
        r = 1 + (k % 3 == 0)
        color = (34, 174, 240, 75) if k % 2 else (255, 61, 127, 65)
        d.ellipse((x-r, y-r, x+r, y+r), fill=color)

    # Edge rails.
    d.line((28, 74, 28, H-74), fill=(145, 70, 255, 130), width=2)
    d.line((W-28, 74, W-28, H-74), fill=(83, 252, 24, 110), width=2)
    d.line((28, 74, W-28, 74), fill=(34, 174, 240, 80), width=1)
    d.line((28, H-74, W-28, H-74), fill=(255, 61, 127, 75), width=1)

    # Opening: quiet logo reveal.
    a = alpha_window(t, 0, .55, 3.2, .55)
    if a > 0:
        scale = .74 + .26 * ease(phase(t, 0, 1.2))
        size = int(220 * scale)
        item = logo.resize((size, size), Image.Resampling.LANCZOS)
        paste_alpha(frame, item, ((W-size)//2, 250-size//2), int(255*a))
        ring_a = int(180*a)
        for n, radius in enumerate((142, 165)):
            d.arc((W//2-radius, 250-radius, W//2+radius, 250+radius),
                  start=(i*2.8+n*110)%360, end=(i*2.8+n*110)%360+230,
                  fill=(34, 174, 240, ring_a//(n+1)), width=2)
        center_text(d, (W//2, 505), "UZUN BİR ARADAN SONRA", F_LABEL, (86, 204, 250, int(255*a)))
        y = 625 + int(34*(1-ease(phase(t,.35,1.15))))
        center_text(d, (W//2, y), "KAPTAN\nQEDY", F_HUGE, (245, 249, 252, int(255*a)), spacing=-6)
        center_text(d, (W//2, 820), "GERİ DÖNÜYOR", F_MID, (255, 79, 137, int(255*a)))

    # Screens montage.
    a = alpha_window(t, 2.8, .45, 7.7, .55)
    if a > 0:
        slide = int(90 * (1 - ease(phase(t, 2.8, 3.55))))
        panel = preview.convert("RGBA")
        mask = Image.new("L", panel.size)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, panel.width-1, panel.height-1), radius=20, fill=int(255*a))
        panel.putalpha(mask)
        shadow = Image.new("RGBA", (W, H))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((48, 337+slide, W-48, 793+slide), radius=25, fill=(0,0,0,int(155*a)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(22))
        frame.alpha_composite(shadow)
        frame.alpha_composite(panel, (50, 330+slide))
        d.rounded_rectangle((49,329+slide,W-49,771+slide), radius=21,
                            outline=(73,201,246,int(190*a)), width=2)
        center_text(d, (W//2, 250), "YENİ YAYIN\nGÜVERTESİ", F_TITLE, (245,249,252,int(255*a)), spacing=-3)
        center_text(d, (W//2, 850), "HAREKETLİ SAHNELER · ORTAK SOHBET\nCANLI BİLDİRİMLER · KAPTAN KUMANDASI",
                    F_LABEL, (181, 207, 222, int(255*a)), spacing=12)

    # Two platforms, one crew.
    a = alpha_window(t, 7.25, .42, 10.55, .48)
    if a > 0:
        center_text(d, (W//2, 278), "İKİ LİMAN", F_LABEL, (104,207,248,int(255*a)))
        xoff = int(70*(1-ease(phase(t,7.25,8.0))))
        center_text(d, (W//2-xoff, 420), "TWITCH", F_HUGE, (171,120,255,int(255*a)))
        center_text(d, (W//2+xoff, 545), "+ KICK", F_HUGE, (108,255,60,int(255*a)))
        d.line((145,650,W-145,650), fill=(34,174,240,int(180*a)), width=2)
        center_text(d, (W//2, 750), "TEK GÜVERTE", F_TITLE, (245,249,252,int(255*a)))
        center_text(d, (W//2, 850), "AYNI YAYIN · TEK MÜRETTEBAT", F_LABEL, (255,75,133,int(255*a)))

    # CTA.
    a = alpha_window(t, 10.1, .5, 13, .2)
    if a > 0:
        size = int(148*(.82+.18*ease(phase(t,10.1,10.8))))
        item = logo.resize((size,size),Image.Resampling.LANCZOS)
        paste_alpha(frame,item,((W-size)//2,170),int(255*a))
        center_text(d,(W//2,425),"PAZARTESİ–CUMA",F_LABEL,(99,205,249,int(255*a)))
        center_text(d,(W//2,530),"20:30",F_HUGE,(245,249,252,int(255*a)))
        # pill
        d.rounded_rectangle((115,665,W-115,748),radius=42,fill=(8,25,39,int(230*a)),
                            outline=(34,174,240,int(190*a)),width=2)
        center_text(d,(W//2,706),"TWITCH + KICK",F_MID,(245,249,252,int(255*a)))
        center_text(d,(W//2,840),"@KAPTAN_QEDY",F_LABEL,(255,75,133,int(255*a)))
        center_text(d,(W//2,925),"GÜVERTEDE YERİN HAZIR.",F_BODY,(202,220,232,int(255*a)))

    # Timeline accent.
    progress = (i + 1) / N
    d.rounded_rectangle((55,H-52,W-55,H-46), radius=3, fill=(255,255,255,35))
    d.rounded_rectangle((55,H-52,55+int((W-110)*progress),H-46), radius=3,
                        fill=(34,174,240,185))
    return frame.convert("RGB")


def soundtrack(path):
    sr = 48000
    count = sr * SECONDS
    t = np.arange(count) / sr
    # Original ambient pulse, low enough to sit below captions.
    audio = .07*np.sin(2*np.pi*55*t) + .035*np.sin(2*np.pi*110*t + .4*np.sin(2*np.pi*.13*t))
    audio *= .65 + .35*np.sin(2*np.pi*.5*t)**2
    rng = np.random.default_rng(42)
    for hit in (0.15, 2.85, 7.3, 10.2):
        x = t-hit
        mask = (x>=0)&(x<.8)
        env = np.exp(-x[mask]*6)
        audio[mask] += .22*env*np.sin(2*np.pi*(115-55*x[mask])*x[mask])
        audio[mask] += .028*env*rng.standard_normal(mask.sum())
    fade = np.ones_like(audio)
    fade[:sr//2] = np.linspace(0,1,sr//2)
    fade[-sr:] = np.linspace(1,0,sr)
    audio = np.clip(audio*fade, -.92, .92)
    stereo = np.column_stack((audio, np.roll(audio, 130)))
    pcm = (stereo*32767).astype("<i2")
    with wave.open(str(path),"wb") as wf:
        wf.setnchannels(2); wf.setsampwidth(2); wf.setframerate(sr); wf.writeframes(pcm.tobytes())


def main():
    OUT.mkdir(exist_ok=True)
    silent = OUT / "instagram-reel-silent.mp4"
    audio = OUT / "instagram-reel-audio.wav"
    final = OUT / "instagram-reel.mp4"
    encoder = subprocess.Popen([
        "ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24",
        "-s",f"{W}x{H}","-r",str(FPS),"-i","-","-an","-c:v","libx264",
        "-preset","medium","-crf","18","-pix_fmt","yuv420p","-movflags","+faststart",
        str(silent)
    ], stdin=subprocess.PIPE)
    for i in range(N):
        encoder.stdin.write(render(i).tobytes())
    encoder.stdin.close()
    if encoder.wait() != 0:
        raise RuntimeError("Video encoder failed")
    soundtrack(audio)
    subprocess.run([
        "ffmpeg","-y","-loglevel","error","-i",str(silent),"-i",str(audio),
        "-vf","scale=1080:1920:flags=lanczos","-c:v","libx264","-preset","medium",
        "-crf","18","-pix_fmt","yuv420p","-c:a","aac","-b:a","192k","-shortest",
        "-movflags","+faststart",str(final)
    ],check=True)
    silent.unlink(); audio.unlink()
    print(f"Created {final} ({final.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
