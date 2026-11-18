"""Draws docs/banner.jpg: an original neon / scanline / glitch banner. Needs numpy and Pillow."""
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1600, 420
OUT = Path(__file__).with_name("banner.jpg")
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
MONO_R = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
CYAN, MAGENTA, YELLOW, BG = (0, 240, 255), (255, 30, 170), (255, 225, 60), (8, 6, 20)
rng = np.random.default_rng(7)


def glow(layer, radii=(3, 10, 28), gain=(1.0, 0.9, 0.8)):
    out = np.array(layer, dtype=np.float32)
    for r, g in zip(radii, gain):
        out += g * np.array(layer.filter(ImageFilter.GaussianBlur(r)), dtype=np.float32)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))


# background gradient
y = np.linspace(0, 1, H)[:, None, None]
bg = np.array(BG, dtype=np.float32) * (1 - y) + np.array((30, 8, 50), dtype=np.float32) * y
img = Image.fromarray(np.repeat(bg, W, axis=1).astype(np.uint8))

# perspective grid on the lower part
grid = Image.new("RGB", (W, H), (0, 0, 0))
d = ImageDraw.Draw(grid)
horizon = int(H * 0.62)
for i in range(-30, 31):
    d.line([(W / 2 + i * 25, horizon), (W / 2 + i * 190, H)], fill=MAGENTA, width=2)
k = 1
while True:
    yy = horizon + (k ** 2) * 2.2
    if yy > H:
        break
    d.line([(0, yy), (W, yy)], fill=MAGENTA, width=2)
    k += 1
fade = np.clip((np.arange(H) - horizon) / (H - horizon), 0, 1)[:, None, None] ** 0.7
grid = Image.fromarray((np.array(glow(grid, (2, 8), (0.8, 0.6)), dtype=np.float32) * fade * 0.8).astype(np.uint8))
img = Image.fromarray(np.clip(np.array(img, dtype=np.float32) + np.array(grid, dtype=np.float32), 0, 255).astype(np.uint8))

# a noisy measurement curve with a fit, drawn as neon, behind the title
x = np.linspace(0, 1, 140)
fit = 0.55 + 0.28 * np.sin(2 * np.pi * (1.3 * x + 0.1)) * np.exp(-1.1 * x)
pts = [(60 + xi * (W - 120), 40 + (1 - fi) * 230) for xi, fi in zip(x, fit)]
curve = Image.new("RGB", (W, H), (0, 0, 0))
d = ImageDraw.Draw(curve)
d.line(pts, fill=CYAN, width=3)
for xi, fi in zip(x[::5], fit[::5]):
    px, py = 60 + xi * (W - 120), 40 + (1 - (fi + rng.normal(0, 0.025))) * 230
    d.ellipse([px - 5, py - 5, px + 5, py + 5], outline=YELLOW, width=2)
curve = glow(curve)
img = Image.fromarray(np.clip(np.array(img, dtype=np.float32) + 0.75 * np.array(curve, dtype=np.float32), 0, 255).astype(np.uint8))

# title with chromatic aberration
title, sub = "BRAINDANCE", "publication-ready figures  //  every plotted value checked against its data"
f1, f2 = ImageFont.truetype(MONO, 150), ImageFont.truetype(MONO_R, 27)
txt = Image.new("RGB", (W, H), (0, 0, 0))
tw = ImageDraw.Draw(txt).textlength(title, font=f1)
tx, ty = (W - tw) / 2, 95
for off, col in ((-6, MAGENTA), (6, CYAN)):
    layer = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(layer).text((tx + off, ty), title, font=f1, fill=col)
    txt = Image.fromarray(np.clip(np.array(txt, dtype=np.float32) + np.array(glow(layer, (4, 14), (0.7, 0.6)), dtype=np.float32), 0, 255).astype(np.uint8))
core = Image.new("RGB", (W, H), (0, 0, 0))
ImageDraw.Draw(core).text((tx, ty), title, font=f1, fill=(245, 250, 255))
txt = Image.fromarray(np.clip(np.array(txt, dtype=np.float32) + np.array(core, dtype=np.float32), 0, 255).astype(np.uint8))
sw = ImageDraw.Draw(txt).textlength(sub, font=f2)
ImageDraw.Draw(txt).text(((W - sw) / 2, 290), sub, font=f2, fill=CYAN)
arr = np.array(txt, dtype=np.float32)

# glitch: shift a few horizontal slices of the text layer
for _ in range(7):
    y0 = int(rng.integers(ty, ty + 150)); h = int(rng.integers(4, 16)); s = int(rng.integers(-40, 40))
    arr[y0:y0 + h] = np.roll(arr[y0:y0 + h], s, axis=1)
base = np.array(img, dtype=np.float32)
out = np.clip(base + arr, 0, 255)

# scanlines, vignette, noise
out *= np.where(np.arange(H)[:, None, None] % 3 == 0, 0.78, 1.0)
yy, xx = np.mgrid[0:H, 0:W]
vig = 1 - 0.55 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
out = out * vig[..., None] + rng.normal(0, 4, out.shape)
Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(OUT, quality=90, optimize=True)
print(OUT)
