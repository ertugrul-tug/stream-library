"""Cinematic vertical comeback Reel for Kaptan Qedy. Run: python social/reel-v2/render.py"""
from __future__ import annotations

import math
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
W, H, FPS, DURATION = 720, 1280, 30, 12
FRAMES = FPS * DURATION

FONT_HEAD = Path("C:/Windows/Fonts/bahnschrift.ttf")
FONT_BODY = Path("C:/Windows/Fonts/segoeui.ttf")

def face(size, path=FONT_HEAD):
    return ImageFont.truetype(str(path), size)

HEAD_118 = face(118)
HEAD_108 = face(108)
HEAD_82 = face(82)
HEAD_72 = face(72)
HEAD_64 = face(64)
BODY_32 = face(32, FONT_BODY)
LABEL_27 = face(27, FONT_BODY)
LABEL_22 = face(22, FONT_BODY)

hero = Image.open(HERE / "hero-ocean.png").convert("RGB")
hero = ImageOps.fit(hero, (W + 100, H + 178), method=Image.Resampling.LANCZOS)
logo = Image.open(ROOT / "docs/assets/logo_cat.png").convert("RGBA")
logo = ImageOps.fit(logo, (150, 150), method=Image.Resampling.LANCZOS)

def clamp(x):
    return max(0.0, min(1.0, x))

def ease(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3

def smooth(x):
    x = clamp(x)
    return x*x*(3-2*x)

def visible(t, start, fade_in, end, fade_out):
    return min(ease((t-start)/fade_in), 1-ease((t-(end-fade_out))/fade_out))

def track(draw, xy, text, font, fill, tracking=3):
    x, y = xy
    for char in text:
        draw.text((x,y), char, font=font, fill=fill)
        x += draw.textlength(char, font=font) + tracking

def text(layer, xy, message, font, color, opacity, anchor="lt", tracking=0):
    if opacity <= 0: return
    d = ImageDraw.Draw(layer)
    fill = (*color, int(255*clamp(opacity)))
    if tracking:
        track(d, xy, message, font, fill, tracking)
    else:
        d.text(xy, message, font=font, fill=fill, anchor=anchor)

def line(layer, points, color, opacity, width=2):
    ImageDraw.Draw(layer).line(points, fill=(*color,int(255*clamp(opacity))), width=width)

def arrow_line(layer, x, y, length, opacity):
    line(layer, [(x,y),(x+length,y)], (78,203,249), opacity, 3)
    ImageDraw.Draw(layer).polygon([(x+length,y-5),(x+length+9,y),(x+length,y+5)], fill=(78,203,249,int(255*opacity)))

def backdrop(t):
    # Subtle camera drift, with the ship remaining in the lower third.
    x = int(39 + 17*math.sin(t*.29))
    y = int(75 + 12*math.sin(t*.22+.4))
    frame = hero.crop((x,y,x+W,y+H)).convert("RGBA")
    # Darken the letter area while leaving the horizon and ship visible.
    shade = Image.new("RGBA",(W,H),(0,0,0,0))
    pix = np.zeros((H,W,4),dtype=np.uint8)
    pix[:,:,:3] = (2,8,17)
    yy=np.arange(H,dtype=np.float32)
    opacity = 34 + 93*np.exp(-((yy-550)/360)**2) + 38*(yy<240)
    if 4.0<t<8.0: opacity += 27
    pix[:,:,3] = np.clip(opacity,0,190).astype(np.uint8)[:,None]
    frame.alpha_composite(Image.fromarray(pix,"RGBA"))
    return frame

def draw_brand(frame, t):
    layer=Image.new("RGBA",(W,H))
    a=ease(t/.7)
    # Quiet editorial brand header, common to all shots.
    text(layer,(69,90),"KAPTAN QEDY",LABEL_22,(243,247,250),a,tracking=3)
    line(layer,[(69,128),(650,128)],(167,208,226),.55*a,2)
    line(layer,[(69,128),(181,128)],(45,192,245),a,3)
    # Small section marker near the lower safe area.
    text(layer,(69,1172),"01 / YENİDEN GÜVERTEDE",LABEL_22,(200,220,231),.8*a,tracking=1)
    frame.alpha_composite(layer)

def draw_intro(frame,t):
    a=visible(t,.55,.65,4.25,.42)
    if a<=0:return
    layer=Image.new("RGBA",(W,H))
    move=int(38*(1-ease((t-.6)/.7)))
    text(layer,(72,394+move),"UZUN BİR ARADAN SONRA",LABEL_27,(103,209,249),a,tracking=2)
    arrow_line(layer,72,458+move,int(110*ease((t-.75)/.55)),a)
    text(layer,(65,493+move),"GERİ",HEAD_118,(250,251,251),a)
    text(layer,(65,610+move),"DÖNDÜM.",HEAD_108,(250,251,251),a)
    # restrained chromatic underline
    line(layer,[(72,753+move),(72+int(400*ease((t-1.1)/.8)),753+move)],(255,89,145),a,5)
    text(layer,(72,789+move),"GÜVERTE YENİDEN AÇILIYOR",BODY_32,(214,228,238),a)
    frame.alpha_composite(layer)

def platform_card(layer, y, title, color, amount, from_left=True):
    d=ImageDraw.Draw(layer)
    x=int((-430+amount*502) if from_left else (W+20-amount*670))
    d.rounded_rectangle((x,y,x+574,y+135),radius=18,fill=(3,12,23,int(200*amount)),
                        outline=(*color,int(185*amount)),width=3)
    d.rectangle((x+22,y+25,x+29,y+110),fill=(*color,int(255*amount)))
    text(layer,(x+63,y+16),title,HEAD_82,(247,249,250),amount)
    return x

def draw_platforms(frame,t):
    a=visible(t,4.15,.45,8.2,.38)
    if a<=0:return
    layer=Image.new("RGBA",(W,H))
    rise=int(25*(1-ease((t-4.2)/.5)))
    text(layer,(72,285+rise),"İKİ LİMAN",LABEL_27,(102,209,251),a,tracking=3)
    platform_card(layer,389+rise,"TWITCH",(158,91,248),a*ease((t-4.2)/.55),True)
    platform_card(layer,545+rise,"KICK",(98,231,88),a*ease((t-4.45)/.55),False)
    text(layer,(72,763+rise),"TEK",HEAD_118,(249,250,250),a)
    text(layer,(72,875+rise),"MÜRETTEBAT.",HEAD_64,(249,250,250),a)
    line(layer,[(72,977+rise),(628,977+rise)],(56,185,239),a*.7,2)
    frame.alpha_composite(layer)

def draw_final(frame,t):
    a=ease((t-8.1)/.65)
    if a<=0:return
    layer=Image.new("RGBA",(W,H))
    # Logo and compass arc.
    size=int(128*(.78+.22*ease((t-8.1)/.8)))
    item=logo.resize((size,size),Image.Resampling.LANCZOS)
    item.putalpha(item.getchannel("A").point(lambda value:int(value*a)))
    layer.alpha_composite(item,(W//2-size//2,277-size//2))
    d=ImageDraw.Draw(layer)
    r=88
    d.arc((W//2-r,277-r,W//2+r,277+r),start=-90,end=-90+int(320*ease((t-8.1)/1.2)),
          fill=(74,204,250,int(230*a)),width=3)
    text(layer,(W//2,448),"KAPTAN QEDY",HEAD_72,(249,250,250),a,anchor="mt")
    text(layer,(W//2,544),"HAFTA İÇİ · CANLI",LABEL_27,(120,211,248),a,anchor="mt")
    text(layer,(W//2,603),"20:30",HEAD_118,(249,250,250),a,anchor="mt")
    # Final CTA with platform colors.
    d.rounded_rectangle((87,777,633,859),radius=16,fill=(4,14,25,int(224*a)),
                        outline=(75,187,230,int(190*a)),width=2)
    text(layer,(190,794),"TWITCH",BODY_32,(191,151,255),a)
    text(layer,(353,794),"+",BODY_32,(247,249,250),a)
    text(layer,(401,794),"KICK",BODY_32,(123,242,99),a)
    text(layer,(W//2,918),"@KAPTANQEDY",LABEL_27,(248,249,249),a,anchor="mt",tracking=0)
    line(layer,[(183,963),(537,963)],(255,101,149),a,3)
    frame.alpha_composite(layer)

def draw_sweep(frame,t,start):
    p=(t-start)/.42
    if not 0<=p<=1:return
    x=int(-100+(W+200)*smooth(p))
    veil=Image.new("RGBA",(W,H))
    d=ImageDraw.Draw(veil)
    d.polygon([(x-140,0),(x+10,0),(x+160,H),(x+10,H)],fill=(2,11,21,160))
    d.line((x+13,0,x+163,H),fill=(65,213,252,170),width=7)
    veil=veil.filter(ImageFilter.GaussianBlur(5))
    frame.alpha_composite(veil)

def render(i):
    t=i/FPS
    frame=backdrop(t)
    draw_brand(frame,t)
    draw_intro(frame,t)
    draw_platforms(frame,t)
    draw_final(frame,t)
    draw_sweep(frame,t,4.05)
    draw_sweep(frame,t,7.92)
    return frame.convert("RGB")

def soundtrack(path):
    sr=48000
    length=sr*DURATION
    tt=np.arange(length,dtype=np.float64)/sr
    audio=np.zeros(length,dtype=np.float64)
    # Three restrained minor chords, each with a slow attack and release.
    chords=[(0,4.1,[130.81,155.56,196.00]),(4.1,8.0,[103.83,155.56,207.65]),(8.0,12,[116.54,174.61,233.08])]
    for start,end,notes in chords:
        mask=(tt>=start)&(tt<end)
        local=tt[mask]-start
        env=np.minimum(1,local/.45)*np.minimum(1,(end-tt[mask])/.48)
        for j,freq in enumerate(notes):
            audio[mask]+= .025*env*np.sin(2*np.pi*freq*tt[mask] + .10*np.sin(2*np.pi*.12*tt[mask]+j))
    # Soft arpeggio pattern to provide forward motion.
    notes=[261.63,311.13,392.0,466.16,392.0,311.13]
    for n,start in enumerate(np.arange(.45,11.5,.32)):
        stop=min(length,int((start+.62)*sr));begin=int(start*sr)
        x=np.arange(stop-begin)/sr
        env=np.exp(-x*6)
        f=notes[n%len(notes)]*(.89 if start>=8 else 1)
        audio[begin:stop]+=.018*env*np.sin(2*np.pi*f*x)
    # Deep cinematic impacts at the two scene changes and final reveal.
    rng=np.random.default_rng(831)
    for start,gain in [(0.55,.55),(4.16,1.0),(8.03,1.0)]:
        begin=int(start*sr);end=min(length,begin+int(1.2*sr))
        x=np.arange(end-begin)/sr
        env=np.exp(-x*6)
        audio[begin:end]+=gain*.14*env*np.sin(2*np.pi*(76*x-20*x*x))
        audio[begin:end]+=gain*.018*env*rng.standard_normal(len(x))
    # Snare-like air sweeps leading into the cuts.
    for start in (3.55,7.48):
        begin=int(start*sr);end=min(length,begin+int(.5*sr))
        x=np.arange(end-begin)/sr
        white=rng.standard_normal(len(x))
        filtered=np.convolve(white,np.ones(36)/36,mode="same")
        audio[begin:end]+=.06*(x/.5)**2*filtered
    # Gentle stereo widening and fade.
    audio*=np.minimum(1,tt/.35)*np.minimum(1,(DURATION-tt)/.55)
    left=audio
    right=np.roll(audio,170)*.94
    pcm=(np.clip(np.column_stack([left,right]),-.95,.95)*32767).astype("<i2")
    with wave.open(str(path),"wb") as wav:
        wav.setnchannels(2);wav.setsampwidth(2);wav.setframerate(sr);wav.writeframes(pcm.tobytes())

def main():
    silent=HERE/"reel-silent.mp4"
    audio=HERE/"reel-audio.wav"
    final=HERE.parent/"instagram-reel.mp4"
    process=subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","rawvideo","-pix_fmt","rgb24",
        "-s",f"{W}x{H}","-r",str(FPS),"-i","-","-an","-c:v","libx264","-preset","medium",
        "-crf","18","-pix_fmt","yuv420p",str(silent)],stdin=subprocess.PIPE)
    for i in range(FRAMES):
        process.stdin.write(render(i).tobytes())
    process.stdin.close()
    if process.wait()!=0:raise RuntimeError("Video render failed")
    soundtrack(audio)
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",str(silent),"-i",str(audio),
        "-vf","scale=1080:1920:flags=lanczos","-c:v","libx264","-preset","medium",
        "-crf","17","-pix_fmt","yuv420p","-af","loudnorm=I=-18:TP=-2:LRA=7","-c:a","aac","-b:a","192k",
        "-shortest","-movflags","+faststart",str(final)],check=True)
    silent.unlink();audio.unlink()
    print(f"Created {final} ({final.stat().st_size:,} bytes)")

if __name__=="__main__":
    main()
