#!/usr/bin/env python3
"""
make_backgrounds.py — GraceFrame background generator (postcard edition)
=======================================================================
Paints a small, curated set of devotional scenes for a 400x300 1-bit
e-paper panel — in the spirit of a linocut print or an engraved postcard.

Design language (this is the whole point):
  * NO dithering.  Skies are clean white, night is solid black.  Tone is
    suggested with deliberate engraved strokes (even hatching, ruled water,
    ray lines) — never with scattered dots.
  * Bold silhouettes for the subject, airy contour lines for distance.
  * Suns are quiet complete circles, never partial ray fans or black-dot
    medallions; the tiny screen reads simple celestial symbols best.
  * Every scene reserves a "text canvas" — an unobstructed rectangle where the
    firmware sets the verse, so the words always land on clean paper.

Each scene is drawn at 4x in grayscale (pure black on white, or white on
black for night), downsampled, then *thresholded* (no error diffusion) so
edges stay crisp and backgrounds stay perfectly smooth.

Outputs (relative to repo root):
  GraceFrame/data/bg/NNN.bin      15000-byte packed bitmaps (bit=1 -> BLACK,
                                  MSB first, 50 bytes/row, 300 rows)
  GraceFrame/data/bg/index.json   scene names, text zones, tags
  tools/previews/NNN_name.png     2x previews for humans
  tools/previews/_sheet.png       contact sheet of everything
  GraceFrame/data/www/icon.png    + icon-512.png  (PWA icons)

Run:  python make_backgrounds.py
"""

import json
import math
import os
import random

from PIL import Image, ImageDraw, ImageFilter

# ---------------------------------------------------------------- geometry
W, H = 400, 300          # panel / design space
S = 4                    # supersample factor
CW, CH = W * S, H * S

INK, PAPER = 0, 255      # grayscale values we actually use

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _sketch_data():
    """Locate the Arduino sketch's data/ dir (holds bg/ + www/). The sketch was
    renamed GraceFrame -> Spotify_Frame; detect whichever actually exists so
    regeneration always lands on the real firmware assets, never a stray tree."""
    for cand in ("Spotify_Frame", "GraceFrame"):
        d = os.path.join(ROOT, cand, "data")
        if os.path.isdir(os.path.join(d, "bg")):
            return d
    return os.path.join(ROOT, "Spotify_Frame", "data")


DATA_DIR = _sketch_data()
BG_DIR = os.path.join(DATA_DIR, "bg")
WWW_DIR = os.path.join(DATA_DIR, "www")
PREV_DIR = os.path.join(HERE, "previews")


class C:
    """A supersampled grayscale canvas with a per-scene deterministic RNG."""

    def __init__(self, seed, bg=PAPER):
        self.img = Image.new("L", (CW, CH), bg)
        self.d = ImageDraw.Draw(self.img)
        self.rng = random.Random(seed)
        self.bg = bg


def sp(pts):
    return [(x * S, y * S) for x, y in pts]


def rot(pts, cx, cy, deg):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * ca - (y - cy) * sa,
             cy + (x - cx) * sa + (y - cy) * ca) for x, y in pts]


def _cr(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return (0.5 * (2 * p1[0] + (-p0[0] + p2[0]) * t
                   + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
                   + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3),
            0.5 * (2 * p1[1] + (-p0[1] + p2[1]) * t
                   + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
                   + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3))


def smooth(pts, n=16):
    """Catmull-Rom through pts (open curve)."""
    ext = [pts[0]] + list(pts) + [pts[-1]]
    out = []
    for i in range(len(ext) - 3):
        for j in range(n):
            out.append(_cr(ext[i], ext[i + 1], ext[i + 2], ext[i + 3], j / n))
    out.append(pts[-1])
    return out


# ---------------------------------------------------------------- primitives
def stroke(c, pts, w=1.6, val=INK, closed=False, joint="curve"):
    p = sp(pts)
    if closed:
        p = p + [p[0]]
    c.d.line(p, fill=val, width=max(1, int(w * S)), joint=joint)


def fill(c, pts, val=INK):
    c.d.polygon(sp(pts), fill=val)


def disc(c, x, y, r, val=INK):
    c.d.ellipse([S * (x - r), S * (y - r), S * (x + r), S * (y + r)], fill=val)


def ring(c, x, y, r, w=1.6, val=INK):
    c.d.ellipse([S * (x - r), S * (y - r), S * (x + r), S * (y + r)],
                outline=val, width=max(1, int(w * S)))


def dot(c, x, y, r, val=INK):
    c.d.ellipse([S * (x - r), S * (y - r), S * (x + r), S * (y + r)], fill=val)


def line(c, p0, p1, w=1.6, val=INK):
    c.d.line(sp([p0, p1]), fill=val, width=max(1, int(w * S)))


# ---- suns -------------------------------------------------------
def sun_rays(c, x, y, r0, r1, n=16, a0=0, a1=360, w=1.4, val=INK, jitter=0.0):
    """straight ruled rays fanning from (x,y)."""
    rng = c.rng
    for i in range(n):
        a = math.radians(a0 + (a1 - a0) * (i / (n if a1 - a0 == 360 else n - 1)))
        rr1 = r1 * (1 + rng.uniform(-jitter, jitter))
        line(c, (x + r0 * math.cos(a), y + r0 * math.sin(a)),
             (x + rr1 * math.cos(a), y + rr1 * math.sin(a)), w, val)


def sun_solid(c, x, y, r, val=INK):
    disc(c, x, y, r, val)


def sun_plain(c, x, y, r=12, val=INK, w=1.6, rays=14, r1=None):
    """A quiet complete sun: open center, uniform full-circle rays, no black dot."""
    r1 = r1 if r1 else r + 14
    for i in range(rays):
        a = math.radians(i * 360 / rays)
        line(c, (x + (r + 4) * math.cos(a), y + (r + 4) * math.sin(a)),
             (x + r1 * math.cos(a), y + r1 * math.sin(a)), 1.0, val)
    ring(c, x, y, r, w, val)


def sun_lined(c, x, y, r, rays=18, r1=None, w=1.6, val=INK, a0=0, a1=360):
    """A tidy sun: a solid core, a slim halo ring, and evenly spaced rays that
    alternate long/short so it reads as a warm sunburst — not a spiky asterisk."""
    r1 = r1 if r1 else r * 2.1
    full = (a1 - a0) % 360 == 0
    for i in range(rays):
        frac = i / (rays if full else rays - 1)
        a = math.radians(a0 + (a1 - a0) * frac)
        rr = r1 if i % 2 == 0 else r + (r1 - r) * 0.5
        line(c, (x + (r + 4) * math.cos(a), y + (r + 4) * math.sin(a)),
             (x + rr * math.cos(a), y + rr * math.sin(a)), w, val)
    ring(c, x, y, r, w=max(1.4, w), val=val)
    disc(c, x, y, r * 0.55, val)


def sun_medallion(c, x, y, r=13, rays=18, r1=None, val=INK):
    """Compatibility wrapper for older scene calls: now a plain complete sun."""
    sun_plain(c, x, y, r + 2, val=val, w=1.6, rays=rays, r1=r1)


# ---- ground / water / hatch ------------------------------------
def ridge_pts(c, base_y, amp, seed_extra=0, waves=3):
    rng = random.Random(str(c.rng.random()) + str(seed_extra))
    wv = [(rng.uniform(0.5, 1.0), rng.uniform(0, 6.28), rng.uniform(0.8, 2.2))
          for _ in range(waves)]
    pts = []
    for x in range(-6, W + 7, 3):
        yy = base_y
        for a, ph, f in wv:
            yy -= amp * a * 0.5 * (1 + math.sin(ph + f * 2 * math.pi * x / W)) / len(wv)
        pts.append((x, yy))
    return pts


def hill_fill(c, base_y, amp, val=INK, seed_extra=0, waves=3):
    pts = ridge_pts(c, base_y, amp, seed_extra, waves)
    fill(c, pts + [(W + 6, H + 6), (-6, H + 6)], val)
    return pts


def hill_outline(c, base_y, amp, w=1.6, seed_extra=0, waves=3, val=INK):
    pts = ridge_pts(c, base_y, amp, seed_extra, waves)
    stroke(c, pts, w, val)
    return pts


def engrave_ridge(c, ridge, hz, n=6, gap=8, inset=7, w=1.0, val=PAPER,
                  fade=0.55, x0=None, x1=None):
    """Carve contour lines into a filled ridge (linocut shading): copies of the
    ridge polyline stepped downhill, each shorter than the last, so the slope
    reads as sculpted light instead of a flat black blob. Lines never reach the
    base, so the mass stays solid and grounded."""
    m = len(ridge)
    for k in range(1, n + 1):
        off = inset + (k - 1) * gap
        # each successive contour is trimmed inward from both ends -> tapered
        trim = int(m * fade * (k - 1) / max(1, n))
        seg = ridge[trim:m - trim] if m - 2 * trim > 3 else []
        seg = [(x, y + off) for (x, y) in seg
               if y + off < hz - 3 and (x0 is None or x >= x0)
               and (x1 is None or x <= x1)]
        if len(seg) > 3:
            stroke(c, seg, w, val)


def water_lines(c, y0, y1, x0=0, x1=W, gap=7, w=1.4, val=INK, seed=1, dashed=True):
    """ruled, gently rippled water — deliberate engraving, never dither."""
    rng = random.Random(seed)
    y = y0
    while y <= y1:
        yy = y
        if not dashed:
            pts = [(x, yy + 1.2 * math.sin(x / 26 + y)) for x in range(x0, x1 + 1, 4)]
            stroke(c, pts, w, val)
        else:
            x = x0 + rng.uniform(0, 14)
            while x < x1:
                seg = rng.uniform(10, 34)
                e = min(x1, x + seg)
                yb = yy + 1.1 * math.sin(x / 24 + y)
                line(c, (x, yb), (e, yb + 1.1 * math.sin(e / 24 + y)), w, val)
                x = e + rng.uniform(8, 22)
        y += gap


def hatch(c, poly, gap=6, w=1.0, val=INK, ang=0):
    """diagonal engraving fill clipped to a polygon (for gentle tone)."""
    mask = Image.new("L", (CW, CH), 0)
    ImageDraw.Draw(mask).polygon(sp(poly), fill=255)
    lines = Image.new("L", (CW, CH), 0)
    ld = ImageDraw.Draw(lines)
    diag = math.tan(math.radians(ang))
    step = gap * S
    x = -CH
    while x < CW + CH:
        ld.line([(x, 0), (x + diag * CH, CH)], fill=255, width=max(1, int(w * S)))
        x += step
    lines = Image.composite(lines, Image.new("L", (CW, CH), 0), mask)
    # paint val where lines are set
    c.img.paste(Image.new("L", (CW, CH), val), (0, 0), lines)
    c.d = ImageDraw.Draw(c.img)


def stars(c, n, zone=None, y0=6, y1=H, x0=6, x1=W - 6, vmin=200):
    """white stars for night skies (canvas bg is black)."""
    rng = c.rng
    placed = 0
    tries = 0
    while placed < n and tries < n * 20:
        tries += 1
        x = rng.uniform(x0, x1)
        y = rng.uniform(y0, y1)
        if zone and (zone[0] - 14 <= x <= zone[0] + zone[2] + 14
                     and zone[1] - 14 <= y <= zone[1] + zone[3] + 14):
            continue
        r = rng.uniform(0.5, 1.3)
        disc(c, x, y, r, rng.randint(vmin, 255))
        placed += 1
    for _ in range(max(2, n // 22)):   # a few gentle sparkles
        x = rng.uniform(x0 + 10, x1 - 10)
        y = rng.uniform(y0 + 6, (y1 - 20))
        if zone and (zone[0] - 10 <= x <= zone[0] + zone[2] + 10
                     and zone[1] - 10 <= y <= zone[1] + zone[3] + 10):
            continue
        line(c, (x - 3.5, y), (x + 3.5, y), 1.0, 255)
        line(c, (x, y - 3.5), (x, y + 3.5), 1.0, 255)


def _local(cx, cy, s_, deg, px, py):
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    return (cx + s_ * (px * ca - py * sa),
            cy + s_ * (px * sa + py * ca))


def gull(c, x, y, s_, deg=0, w=1.4, val=INK):
    """Tiny distant gull: a shaped body plus two swept wing strokes. The old
    double-arc shorthand read like stray marks; this stays bird-like at 1-bit."""
    body = [_local(x, y, s_, deg, -0.18, 0.02),
            _local(x, y, s_, deg, 0.02, -0.06),
            _local(x, y, s_, deg, 0.24, 0.02),
            _local(x, y, s_, deg, 0.02, 0.10)]
    fill(c, body, val)
    left = [_local(x, y, s_, deg, -0.03, -0.01),
            _local(x, y, s_, deg, -0.45, -0.20),
            _local(x, y, s_, deg, -0.86, -0.34)]
    right = [_local(x, y, s_, deg, 0.07, -0.02),
             _local(x, y, s_, deg, 0.46, -0.18),
             _local(x, y, s_, deg, 0.84, -0.30)]
    stroke(c, smooth(left, 8), w, val)
    stroke(c, smooth(right, 8), w, val)
    tail = [_local(x, y, s_, deg, -0.22, 0.04),
            _local(x, y, s_, deg, -0.48, 0.12)]
    stroke(c, tail, max(0.9, w * 0.75), val)


def birds(c, pts, s_=5, w=1.3, val=INK):
    for p in pts:
        x, y = p[0], p[1]
        ss = p[2] if len(p) > 2 else s_
        deg = p[3] if len(p) > 3 else 0
        gull(c, x, y, ss, deg, w, val)


# ---------------------------------------------------------------- subjects
def cross(c, cx, base_y, h, tilt=0, beam=0.30, thick=0.12, val=INK):
    t = h * thick / 2
    bw = h * 0.60 / 2
    by = base_y - h * (1 - beam)
    v = [(cx - t, base_y), (cx - t, by + t), (cx - bw, by + t), (cx - bw, by - t),
         (cx - t, by - t), (cx - t, base_y - h), (cx + t, base_y - h),
         (cx + t, by - t), (cx + bw, by - t), (cx + bw, by + t),
         (cx + t, by + t), (cx + t, base_y)]
    if tilt:
        v = rot(v, cx, base_y, tilt)
    fill(c, v, val)


def pine(c, x, base, h, w=0.34, val=INK):
    line(c, (x, base), (x, base - h * 0.16), max(1.4, h * 0.05), val)
    for i in range(3):
        t = i / 3
        wy = base - h * 0.12 - h * 0.86 * t
        ww = h * w * (1 - t * 0.6)
        fill(c, [(x, wy - h * 0.32), (x - ww, wy), (x + ww, wy)], val)


def tree_round(c, x, base, h, val=INK):
    """A clean broadleaf tree with a visible trunk and a readable leafy crown."""
    trunk_w = max(2.2, h * 0.10)
    fill(c, [(x - trunk_w / 2, base), (x - trunk_w / 2, base - h * 0.42),
             (x + trunk_w / 2, base - h * 0.42), (x + trunk_w / 2, base)], val)
    cx, cy, rw, rh = x, base - h * 0.68, h * 0.36, h * 0.35
    canopy = []
    bumps = 13
    for i in range(bumps):
        a = -math.pi / 2 + 2 * math.pi * i / bumps
        rr = 1.0 + 0.12 * math.sin(a * 6)
        canopy.append((cx + rw * rr * math.cos(a), cy + rh * rr * math.sin(a)))
    fill(c, smooth(canopy + [canopy[0]], 10), val)


def classic_tree(c, x, base, h, val=INK):
    """Small storybook tree: trunk first, then a distinct leafy top."""
    paper = PAPER if val == INK else INK
    trunk_w = max(2.0, h * 0.12)
    fill(c, [(x - trunk_w / 2, base), (x - trunk_w / 2, base - h * 0.42),
             (x + trunk_w / 2, base - h * 0.42), (x + trunk_w / 2, base)], val)
    crown = smooth([(x, base - h * 0.92), (x - h * 0.28, base - h * 0.76),
                    (x - h * 0.38, base - h * 0.54), (x - h * 0.18, base - h * 0.42),
                    (x, base - h * 0.48), (x + h * 0.18, base - h * 0.42),
                    (x + h * 0.38, base - h * 0.54), (x + h * 0.28, base - h * 0.76),
                    (x, base - h * 0.92)], 10)
    fill(c, crown, val)
    if h >= 34:
        line(c, (x, base - h * 0.83), (x, base - h * 0.52), 0.8, paper)


def sheep(c, x, y, s_, val=INK):
    """A sheep that reads even at postcard size: a woolly fleece (bright, with a
    bold scalloped outline so wool reads as wool, not a dark lump) carrying a
    small dark head on a short neck, over four fine legs."""
    paper = PAPER if val == INK else INK
    for lx in (-0.30, -0.10, 0.20, 0.40):                 # legs (behind the body)
        line(c, (x + lx * s_, y + 0.16 * s_), (x + lx * s_, y + 0.60 * s_),
             max(1.2, 0.06 * s_), val)
    cx, cy, rw, rh = x - 0.04 * s_, y, 0.62 * s_, 0.42 * s_
    bumps = 11
    poly = []
    for i in range(bumps):
        a = math.pi / 2 + 2 * math.pi * i / bumps
        rr = 1.0 + 0.13 * math.sin(a * bumps)             # scalloped wool
        poly.append((cx + rw * rr * math.cos(a), cy + rh * rr * math.sin(a)))
    poly = smooth(poly + [poly[0]], 8)
    fill(c, poly, paper)
    stroke(c, poly, max(1.3, 0.07 * s_), val)
    hx, hy = x + 0.60 * s_, y - 0.04 * s_                  # dark head, facing right
    fill(c, [(x + 0.30 * s_, y - 0.06 * s_), (hx - 0.06 * s_, hy - 0.14 * s_),
             (hx + 0.10 * s_, hy + 0.14 * s_), (x + 0.30 * s_, y + 0.14 * s_)], val)
    c.d.ellipse([S * (hx - 0.17 * s_), S * (hy - 0.17 * s_),
                 S * (hx + 0.19 * s_), S * (hy + 0.18 * s_)], fill=val)
    disc(c, hx + 0.07 * s_, hy - 0.03 * s_, 0.035 * s_, paper)   # eye
    fill(c, [(hx - 0.10 * s_, hy - 0.13 * s_), (hx - 0.24 * s_, hy - 0.20 * s_),
             (hx - 0.05 * s_, hy - 0.01 * s_)], val)            # a pricked ear


def shepherd(c, x, base, h, val=INK):
    hr = h * 0.08
    disc(c, x, base - h + hr, hr, val)
    robe = smooth([(x, base - h + hr * 1.6), (x - h * 0.13, base - h * 0.6),
                   (x - h * 0.18, base), (x + h * 0.18, base),
                   (x + h * 0.13, base - h * 0.55), (x, base - h + hr * 1.6)], 10)
    fill(c, robe, val)
    sx = x + h * 0.28
    line(c, (x + h * 0.04, base - h * 0.66), (sx, base - h * 0.54), h * 0.05, val)
    line(c, (sx, base), (sx, base - h * 0.95), h * 0.04, val)
    c.d.arc([S * (sx - h * 0.11), S * (base - h * 1.08),
             S * (sx + h * 0.11), S * (base - h * 0.86)],
            250, 110, fill=val, width=max(1, int(h * 0.04 * S)))


def lighthouse(c, x, base, h, val=INK):
    w0, w1 = h * 0.20, h * 0.12
    tower_top = base - h * 0.68
    fill(c, [(x - w0 / 2, base), (x - w1 / 2, tower_top),
             (x + w1 / 2, tower_top), (x + w0 / 2, base)], val)
    # gallery deck that visibly carries the lantern room
    deck_y = tower_top - h * 0.055
    c.d.rectangle([S * (x - w1 * 0.95), S * deck_y,
                   S * (x + w1 * 0.95), S * tower_top], fill=val)
    # lantern walls: white glass panels contained by black posts and lintels, so
    # the roof never reads as a floating cap.
    lan_bot = deck_y
    lan_top = base - h * 0.88
    c.d.rectangle([S * (x - w1 * 0.68), S * lan_top,
                   S * (x + w1 * 0.68), S * lan_bot], fill=PAPER)
    for xx, ww in ((x - w1 * 0.68, 1.7), (x, 1.2), (x + w1 * 0.68, 1.7)):
        line(c, (xx, lan_top), (xx, lan_bot), ww, val)
    line(c, (x - w1 * 0.78, lan_top), (x + w1 * 0.78, lan_top), 1.8, val)
    line(c, (x - w1 * 0.78, lan_bot), (x + w1 * 0.78, lan_bot), 1.8, val)
    roof_y = base - h * 0.98
    fill(c, [(x - w1 * 0.95, lan_top), (x, roof_y),
             (x + w1 * 0.95, lan_top), (x + w1 * 0.78, lan_top + h * 0.035),
             (x - w1 * 0.78, lan_top + h * 0.035)], val)
    line(c, (x, roof_y - h * 0.035), (x, roof_y), 1.2, val)
    # two stripes carved from the tower
    for t in (0.24, 0.46):
        ww = w0 + (w1 - w0) * t
        c.d.rectangle([S * (x - ww / 2 + 1), S * (base - h * (t + 0.09)),
                       S * (x + ww / 2 - 1), S * (base - h * t)], fill=PAPER)


def dove(c, x, y, s_, val=INK):
    """A side-profile peace dove rising to the right: outlined body, readable
    face, transparent wings, and feather lines that survive the 1-bit export."""
    s = s_
    paper = PAPER if val == INK else INK
    far = smooth([(x - 0.12 * s, y + 0.08 * s), (x - 0.42 * s, y - 0.08 * s),
                  (x - 0.76 * s, y - 0.30 * s), (x - 0.50 * s, y - 0.10 * s),
                  (x - 0.22 * s, y + 0.10 * s), (x - 0.12 * s, y + 0.08 * s)], 14)
    fill(c, far, paper)
    stroke(c, far, 1.7, val)
    for dx, dy in [(-0.62, -0.23), (-0.46, -0.10)]:
        line(c, (x - 0.18 * s, y + 0.07 * s), (x + dx * s, y + dy * s), 0.9, val)

    near = smooth([(x + 0.02 * s, y + 0.04 * s), (x + 0.00 * s, y - 0.34 * s),
                   (x + 0.18 * s, y - 0.90 * s), (x + 0.38 * s, y - 0.62 * s),
                   (x + 0.29 * s, y - 0.22 * s), (x + 0.13 * s, y + 0.08 * s),
                   (x + 0.02 * s, y + 0.04 * s)], 18)
    fill(c, near, paper)
    stroke(c, near, 2.2, val)
    for tx, ty in [(0.31, -0.58), (0.25, -0.40), (0.20, -0.22)]:
        line(c, (x + 0.08 * s, y + 0.02 * s), (x + tx * s, y + ty * s), 1.0, val)

    body = smooth([(x - 0.42 * s, y + 0.18 * s), (x - 0.16 * s, y + 0.00 * s),
                   (x + 0.24 * s, y + 0.02 * s), (x + 0.46 * s, y + 0.12 * s),
                   (x + 0.20 * s, y + 0.31 * s), (x - 0.34 * s, y + 0.27 * s),
                   (x - 0.42 * s, y + 0.18 * s)], 18)
    fill(c, body, paper)
    stroke(c, body, 2.2, val)
    hx, hy = x + 0.45 * s, y - 0.02 * s
    c.d.ellipse([S * (hx - 0.13 * s), S * (hy - 0.13 * s),
                 S * (hx + 0.13 * s), S * (hy + 0.13 * s)],
                fill=paper, outline=val, width=max(1, int(1.8 * S)))
    fill(c, [(hx + 0.12 * s, hy - 0.035 * s), (hx + 0.36 * s, hy + 0.00 * s),
             (hx + 0.12 * s, hy + 0.055 * s)], val)
    dot(c, hx + 0.03 * s, hy - 0.04 * s, 0.026 * s, val)

    root = (x - 0.36 * s, y + 0.23 * s)
    for dx, dy in [(-0.68, 0.05), (-0.60, 0.24), (-0.44, 0.42)]:
        stroke(c, smooth([root, (x + dx * s, y + dy * s)], 6), 1.8, val)


def tomb(c, x, base, s_, val=INK):
    """An iconic empty tomb: a pale domed rock face outlined in bold ink, a solid
    black arched opening (the dark, empty doorway reads as depth against the pale
    rock), and a great round stone rolled clear to the side."""
    paper = PAPER if val == INK else INK
    # rounded rock face rendered as PALE stone with a bold outline — not a black
    # blob — so the dark doorway can read as a hollow cut into it
    rock = smooth([(x - s_ * 1.30, base), (x - s_ * 1.24, base - s_ * 0.52),
                   (x - s_ * 0.90, base - s_ * 0.92), (x - s_ * 0.34, base - s_ * 1.14),
                   (x + s_ * 0.30, base - s_ * 1.10), (x + s_ * 0.72, base - s_ * 0.80),
                   (x + s_ * 0.86, base - s_ * 0.42), (x + s_ * 0.88, base)], 14)
    fill(c, rock, paper)
    stroke(c, rock, 2.0, val)
    # engraved strata rippling across the rock face (linocut tone, not dots)
    for dy, xa, xb in [(0.34, -1.02, 0.46), (0.60, -1.16, 0.62), (0.84, -1.2, 0.3)]:
        seg = smooth([(x + s_ * xa, base - s_ * dy),
                      (x + s_ * (xa + xb) / 2, base - s_ * (dy - 0.05)),
                      (x + s_ * xb, base - s_ * (dy + 0.02))], 8)
        stroke(c, seg, 1.0, val)
    # the dark arched opening: a solid ink keyhole = the empty doorway
    door = smooth([(x - s_ * 0.34, base), (x - s_ * 0.34, base - s_ * 0.54),
                   (x - s_ * 0.24, base - s_ * 0.78), (x - s_ * 0.02, base - s_ * 0.88),
                   (x + s_ * 0.20, base - s_ * 0.78), (x + s_ * 0.30, base - s_ * 0.54),
                   (x + s_ * 0.30, base)], 14)
    fill(c, door, val)
    # the great round stone, rolled clear of the mouth to the right. Drawn as a
    # PALE boulder (the same rock as the face) with a bold rim and a shaded
    # underside, so it reads as a solid rounded stone rolled aside — never a
    # second dark doorway blob beside the real one.
    st_x, st_r = x + s_ * 1.44, s_ * 0.52
    st_y = base - st_r * 0.9
    c.d.ellipse([S * (st_x - st_r * 0.95), S * (base - 3),
                 S * (st_x + st_r * 0.95), S * (base + 4)], fill=val)   # ground shadow
    disc(c, st_x, st_y, st_r, paper)                                    # pale stone body
    ring(c, st_x, st_y, st_r, 2.0, val)                                 # bold rim
    c.d.arc([S * (st_x - st_r * 0.62), S * (st_y - st_r * 0.3),         # underside shading
             S * (st_x + st_r * 0.92), S * (st_y + st_r * 0.92)],
            30, 150, fill=val, width=max(1, int(1.7 * S)))
    line(c, (x + s_ * 0.5, base), (st_x - st_r * 0.78, base), 1.2, val)  # the roll groove


def lily(c, x, base, h, val=INK):
    """A single Easter lily: a curved stem, a pair of slim leaves, and a five
    petal trumpet bloom with three stamens — drawn large enough to read at
    postcard size instead of collapsing into a speckle."""
    paper = PAPER if val == INK else INK
    stem = smooth([(x, base), (x - h * 0.06, base - h * 0.42),
                   (x + h * 0.02, base - h * 0.78)], 10)
    stroke(c, stem, 1.7, val)
    for sgn, ly in ((-1, 0.30), (1, 0.50)):       # two slim leaves near the base
        leaf(c, x + sgn * h * 0.02, base - h * ly, h * 0.28, 90 + sgn * 54, val)
    # bloom: five pointed petals fanning up-and-out from the stem tip
    cx, cy = x + h * 0.02, base - h * 0.82
    for adeg in (-150, -114, -90, -66, -30):
        a = math.radians(adeg)
        tip = (cx + h * 0.42 * math.cos(a), cy + h * 0.42 * math.sin(a))
        m1 = (cx + h * 0.17 * math.cos(a - 0.42), cy + h * 0.17 * math.sin(a - 0.42))
        m2 = (cx + h * 0.17 * math.cos(a + 0.42), cy + h * 0.17 * math.sin(a + 0.42))
        fill(c, [(cx, cy), m1, tip, m2], val)
        line(c, (cx, cy), tip, 0.6, paper)        # a carved vein down each petal
    for adeg in (-114, -90, -66):                 # three stamens tipped with anthers
        a = math.radians(adeg)
        ex, ey = cx + h * 0.30 * math.cos(a), cy + h * 0.30 * math.sin(a)
        line(c, (cx, cy), (ex, ey), 0.7, paper)
        dot(c, ex, ey, 1.3, val)


def open_book(c, cx, cy, w_, val=INK):
    h_ = w_ * 0.34
    # dark cover
    fill(c, [(cx - w_ * 0.54, cy + h_ * 0.02), (cx, cy + h_ * 0.3),
             (cx + w_ * 0.54, cy + h_ * 0.02), (cx + w_ * 0.54, cy + h_ * 0.34),
             (cx, cy + h_ * 0.62), (cx - w_ * 0.54, cy + h_ * 0.34)], val)
    for sgn in (-1, 1):
        page = smooth([(cx, cy + h_ * 0.28), (cx + sgn * w_ * 0.16, cy + h_ * 0.14),
                       (cx + sgn * w_ * 0.34, cy - h_ * 0.16),
                       (cx + sgn * w_ * 0.5, cy - h_ * 0.02),
                       (cx + sgn * w_ * 0.5, cy + h_ * 0.06),
                       (cx + sgn * w_ * 0.16, cy + h_ * 0.32),
                       (cx, cy + h_ * 0.46)], 10)
        fill(c, page, PAPER)
        stroke(c, page, 1.6, val)
        for i in range(6):                     # ruled lines of text on the leaf
            t = i / 6
            x0 = cx + sgn * w_ * (0.09 + 0.05 * t)
            x1 = cx + sgn * w_ * (0.44 + 0.02 * t)
            y0 = cy + h_ * (0.20 - 0.30 * t) + h_ * 0.14
            y1 = cy + h_ * (-0.10 - 0.26 * t) + h_ * 0.3
            line(c, (x0, y0), (x1, y1), 1.1, val)
    # a crisp spine crease where the two leaves meet
    line(c, (cx, cy + h_ * 0.30), (cx, cy + h_ * 0.56), 1.4, val)


def boat(c, x, y, s_, val=INK, sail=True):
    hull = smooth([(x - s_ * 0.6, y - s_ * 0.08), (x - s_ * 0.5, y + s_ * 0.16),
                   (x, y + s_ * 0.22), (x + s_ * 0.5, y + s_ * 0.16),
                   (x + s_ * 0.62, y - s_ * 0.1)], 8)
    hull += [(x + s_ * 0.46, y), (x - s_ * 0.46, y)]
    fill(c, hull, val)
    line(c, (x, y), (x, y - s_ * 0.95), max(1.4, 0.045 * s_), val)
    if sail:
        fill(c, [(x + s_ * 0.04, y - s_ * 0.9), (x + s_ * 0.46, y - s_ * 0.08),
                 (x + s_ * 0.04, y - s_ * 0.08)], val)
        fill(c, [(x - s_ * 0.04, y - s_ * 0.72), (x - s_ * 0.34, y - s_ * 0.08),
                 (x - s_ * 0.04, y - s_ * 0.08)], val)


def wheat(c, x, base, h, val=INK, lean=3, awns=True):
    """A single graceful wheat stalk: a slender curved stem, long fine awns, and
    crisp paired kernels climbing the top third — each kernel a clean teardrop
    carved with a center vein so it reads as grain, not a feathery blob."""
    paper = PAPER if val == INK else INK
    stem = smooth([(x, base), (x + lean * 0.4, base - h * 0.5),
                   (x + lean, base - h)], 12)
    stroke(c, stem, 1.8, val)
    tx, ty = x + lean, base - h
    if awns:
        for aw in (-0.10, -0.035, 0.035, 0.10):   # long fine awns crowning the ear
            line(c, (tx, ty), (tx + aw * h * 1.3, ty - h * 0.28), 0.7, val)
    ear, n = h * 0.34, 5
    for i in range(n):
        t = i / (n - 1)
        gy = ty + h * 0.06 + ear * t
        gx = tx - lean * t * 0.4                   # follow the stem back down
        for side in (-1, 1):
            bx, by = gx + side * h * 0.02, gy
            a = math.radians(-90 + side * 38)
            kl = h * 0.115
            tip = (bx + kl * math.cos(a), by + kl * math.sin(a))
            m1 = (bx + kl * 0.55 * math.cos(a - 0.5), by + kl * 0.55 * math.sin(a - 0.5))
            m2 = (bx + kl * 0.55 * math.cos(a + 0.5), by + kl * 0.55 * math.sin(a + 0.5))
            fill(c, [(bx, by), m1, tip, m2], val)
            line(c, (bx, by), tip, 0.5, paper)     # carved center vein


def leaf(c, x, y, s_, ang, val=INK, veined=True):
    a = math.radians(ang)
    tip = (x + s_ * math.cos(a), y + s_ * math.sin(a))
    m1 = (x + s_ * 0.5 * math.cos(a - 0.66), y + s_ * 0.5 * math.sin(a - 0.66))
    m2 = (x + s_ * 0.5 * math.cos(a + 0.66), y + s_ * 0.5 * math.sin(a + 0.66))
    fill(c, [(x, y), m1, tip, m2], val)


def sprig(c, x, y, length, ang, val=INK, leaves=5, size=7, curve=16, sign=1):
    a = math.radians(ang)
    pts = []
    for i in range(13):
        t = i / 12
        px = x + length * t * math.cos(a) + curve * t * t * math.sin(a) * sign
        py = y + length * t * math.sin(a) - curve * t * t * math.cos(a) * sign
        pts.append((px, py))
    stroke(c, pts, 1.3, val)
    for i in range(1, leaves + 1):
        t = i / (leaves + 1)
        bx, by = pts[int(t * 12)]
        la = ang + sign * (34 if i % 2 else -34) - 8 * t
        leaf(c, bx, by, size * (1 - 0.35 * t), la, val)


def heart(c, cx, cy, s_, val=INK):
    for sgn in (-1, 1):
        c.d.ellipse([S * (cx + sgn * s_ * 0.5 - s_ * 0.55), S * (cy - s_ * 0.62),
                     S * (cx + sgn * s_ * 0.5 + s_ * 0.55), S * (cy + s_ * 0.42)],
                    fill=val)
    fill(c, [(cx - s_ * 0.95, cy), (cx, cy + s_ * 1.25), (cx + s_ * 0.95, cy)], val)


def filigree_corner(c, cx, cy, fx, fy, val=INK):
    start = {(1, 1): 180, (-1, 1): 270, (1, -1): 90, (-1, -1): 0}[(fx, fy)]
    for r in (24, 16, 9):
        box = [min(cx, cx + fx * r), min(cy, cy + fy * r),
               max(cx, cx + fx * r), max(cy, cy + fy * r)]
        c.d.arc([S * box[0], S * box[1], S * box[2], S * box[3]],
                start, start + 90, fill=val, width=max(1, int(1.3 * S)))
    dot(c, cx + fx * 28, cy + fy * 28, 2.2, val)
    # a little leaf accent
    leaf(c, cx + fx * 14, cy + fy * 14, 8, math.degrees(math.atan2(fy, fx)), val)


# ================================================================ scenes
# each returns (zone, tags); zone = (x, y, w, h) clean text canvas

def sc_note_flourish(c):
    # elegant engraved border for love notes
    c.d.rounded_rectangle([S * 12, S * 12, S * (W - 12), S * (H - 12)],
                          radius=12 * S, outline=INK, width=max(1, int(1.8 * S)))
    c.d.rounded_rectangle([S * 18, S * 18, S * (W - 18), S * (H - 18)],
                          radius=9 * S, outline=INK, width=max(1, int(0.7 * S)))
    for (cx, cy, fx, fy) in [(26, 26, 1, 1), (W - 26, 26, -1, 1),
                             (26, H - 26, 1, -1), (W - 26, H - 26, -1, -1)]:
        filigree_corner(c, cx, cy, fx, fy)
    heart(c, W / 2, 26, 7)
    for sgn in (-1, 1):
        line(c, (W / 2 + sgn * 16, 26), (W / 2 + sgn * 52, 26), 0.7)
        dot(c, W / 2 + sgn * 56, 26, 1.8)
    heart(c, W / 2, H - 26, 5)
    # zone kept just inside the filigree corners so the note never touches the frame
    return (56, 60, 288, 178), ["special"]


def sc_celebration(c):
    # a radiant sunrise crown up top + full laurel branches curving up from the
    # base to a heart — canvas kept clean in the middle
    cx = W / 2
    sun_medallion(c, cx, 42, r=13, rays=22, r1=36)
    for sgn in (-1, 1):                                        # a laurel branch
        base = smooth([(cx + sgn * 8, H - 18), (cx + sgn * 80, H - 16),
                       (cx + sgn * 140, H - 34), (cx + sgn * 168, H - 78)], 16)
        stroke(c, base, 2.0)
        # well-spaced leaves alternating to either side of the branch so it
        # reads as a laurel wreath, not a fuzzy caterpillar of overlapping blobs
        for j, i in enumerate(range(3, len(base) - 3, 5)):
            bx, by = base[i]
            side = 1 if j % 2 else -1
            leaf(c, bx, by, 13, -90 + sgn * 38 + side * 30)
        dot(c, base[-1][0], base[-1][1] - 2, 2.4)             # a berry at the tip
    heart(c, cx, H - 26, 7)
    return (50, 90, 300, 132), ["special"]


def sc_golgotha_dawn(c):
    # three crosses on a hill, a quiet complete sun above the horizon. No road
    # marks: the hill should read as Calvary, not a trail through a park.
    sun_plain(c, 78, 86, r=13, rays=14, r1=32)
    pts = smooth([(-6, 214), (70, 198), (150, 192), (250, 216), (330, 238),
                  (W + 6, 252)], 10)
    fill(c, pts + [(W + 6, H + 6), (-6, H + 6)], INK)
    # light rakes across the crown of the hill — carved contour lines give the
    # mound real form instead of a flat silhouette
    engrave_ridge(c, pts, H, n=7, gap=8, inset=6, w=1.0, fade=0.5)
    cross(c, 108, 200, 84)
    cross(c, 62, 212, 54, tilt=-7)
    cross(c, 154, 210, 56, tilt=7)
    birds(c, [(136, 78, 5.6, -8), (164, 62, 6.6, 3), (195, 82, 5.2, 8)], 5)
    return (214, 58, 166, 146), []


def sc_shepherd(c):
    # shepherd leading a little flock across a meadow; a low sun behind him.
    # black silhouettes on a soft groundline — airy, postcard-clean.
    sun_medallion(c, 354, 70, r=11, rays=16, r1=25)
    # a distant hill band at the horizon for depth, carved with a bright crest so
    # the flock's meadow reads bright in front of it
    hills = smooth([(-6, 234), (80, 224), (170, 234), (260, 222), (W + 6, 232)], 10)
    fill(c, hills + [(W + 6, 252), (-6, 252)], INK)
    stroke(c, hills, 1.4, PAPER)
    ground = smooth([(-6, 268), (120, 264), (260, 268), (W + 6, 264)], 8)
    stroke(c, ground, 1.4)
    shepherd(c, 312, 266, 80)
    for sx, sy, ss in [(248, 263, 18), (204, 265, 20), (160, 263, 17),
                       (116, 265, 19)]:
        sheep(c, sx, sy, ss, INK)
    sheep(c, 288, 268, 12, INK)          # a little lamb close to the shepherd
    # a few tufts of grass along the path
    for gx in range(24, 300, 24):
        gy = 267 + 2 * math.sin(gx / 40)
        line(c, (gx, gy), (gx + c.rng.uniform(-2, 2), gy - c.rng.uniform(4, 8)), 1.0)
    return (28, 26, 278, 160), []


def sc_lighthouse(c):
    # lighthouse on a headland at right, ruled sea, a defined beam — canvas at left
    # headland the lighthouse stands on
    cliff = smooth([(250, H), (268, 250), (300, 240), (340, 246), (W, 262), (W, H)], 8)
    fill(c, cliff, INK)
    # engraved rock striations so the headland reads as layered stone, not a blob
    for yy in (260, 273, 286):
        pts = [(x, yy + 3 * math.sin(x / 16)) for x in range(286, 400, 4)]
        stroke(c, pts, 1.4, PAPER)
    # the lighthouse rises above the headland, a black silhouette on white sky
    lighthouse(c, 326, 244, 128, INK)
    # the lantern casts a small radiant glow, then a single clean beam cone
    # sweeping up over the sea (two crisp edges with a couple of guide rays
    # inside) — kept clear of the text canvas on the left
    lx, ly = 322, 146
    ring(c, lx, ly, 5, 1.2)
    disc(c, lx, ly, 2)
    # small lamp glow: short, uniform sun-ray marks around the beacon read more
    # naturally on this tiny display than a searchlight cone.
    sun_rays(c, lx, ly, 9, 25, n=12, w=0.8)
    water_lines(c, 250, 300, x0=0, x1=246, gap=8, w=1.2, seed=7)
    birds(c, [(58, 224, 8.6, -5), (95, 218, 7.8, 4),
              (132, 227, 6.8, -2)], 7)  # gulls low over the water
    return (20, 28, 222, 158), []


def _range_poly(peaks, hz):
    """A smooth mountain silhouette through `peaks`, closed down to horizon hz."""
    ridge = smooth(peaks, 14)
    return ridge + [(peaks[-1][0], hz), (peaks[0][0], hz)]


def sc_still_waters(c):
    # a range of smooth mountains mirrored in a glass-calm lake, a low sun in the
    # valley gap — a clean band of sky up top holds the verse
    hz = 182
    # a paler, farther ridge behind (outline only) for depth
    far = smooth([(-6, 166), (60, 150), (140, 160), (230, 146), (320, 160),
                  (W + 6, 152)], 12)
    stroke(c, far, 1.1)
    Lpeaks = [(-6, 158), (44, 142), (92, 120), (150, 150)]
    Rpeaks = [(232, 158), (270, 142), (312, 116), (356, 146), (W + 6, 138)]
    Lridge, Rridge = smooth(Lpeaks, 14), smooth(Rpeaks, 14)
    Lpoly = Lridge + [(Lpeaks[-1][0], hz), (Lpeaks[0][0], hz)]
    Rpoly = Rridge + [(Rpeaks[-1][0], hz), (Rpeaks[0][0], hz)]
    fill(c, Lpoly, INK)
    fill(c, Rpoly, INK)
    # carved contour lines rake down each face -> sculpted rock, not flat black
    engrave_ridge(c, Lridge, hz, n=5, gap=9, inset=8, w=1.0, fade=0.42)
    engrave_ridge(c, Rridge, hz, n=6, gap=9, inset=8, w=1.0, fade=0.42)
    for (px, py) in [(92, 120), (312, 116)]:       # snow caps carved out
        fill(c, [(px, py + 2), (px - 9, py + 18), (px - 3, py + 15),
                 (px + 1, py + 19), (px + 8, py + 15)], PAPER)
    # tiny carved pines on both ranges, matching the crane-moon tree language.
    pine(c, 62, 178, 34, val=PAPER)
    pine(c, 302, 178, 32, val=PAPER)
    line(c, (0, hz), (W, hz), 1.0)
    # reflection: mirror the two ranges below the horizon, softened by ripples
    mir = lambda poly: [(x, 2 * hz - y) for (x, y) in poly]
    fill(c, mir(Lpoly), INK)
    fill(c, mir(Rpoly), INK)
    water_lines(c, hz + 5, 298, gap=7, w=1.7, val=PAPER, seed=3)
    water_lines(c, hz + 14, 296, gap=26, w=1.0, val=INK, seed=8)
    # a small sun tucked in the valley gap + a shimmer running toward us
    sun_medallion(c, 191, 150, r=8, rays=12, r1=19)
    for k in range(5):
        yy = hz + 8 + k * 12
        hw = 5 + k * 3
        line(c, (191 - hw, yy), (191 + hw, yy), 1.4)
    return (30, 20, 340, 78), []


def sc_empty_tomb(c):
    # the empty tomb at dawn, lilies at the door — text canvas upper right
    sun_plain(c, 92, 98, r=15, rays=20, r1=44)
    hill_outline(c, 252, 14, 1.4, seed_extra=2)
    ground = smooth([(-6, 270), (140, 264), (280, 270), (W + 6, 264)], 8)
    stroke(c, ground, 1.4)
    tomb(c, 108, 268, 58)
    # a small stand of Easter lilies rising at the foot of the doorway, spaced
    # so each trumpet bloom reads on its own
    lily(c, 56, 274, 38)
    lily(c, 86, 276, 28)
    for gx in range(30, 96, 11):       # a few grass blades among them
        line(c, (gx, 274), (gx + 2, 264), 1.0)
    # all tomb art (rays, rock) ends by x~159; the right sky is clear, so the
    # verse zone runs wider than before to hold more (and longer) verses
    return (180, 44, 200, 152), []


def sc_botanical_frame(c):
    # a delicate branch framing the top and bottom, leaves turned outward so the
    # whole middle stays clean — a big, generous text canvas
    rng = c.rng
    top = smooth([(-6, 30), (70, 22), (150, 34), (240, 22), (330, 34), (W + 6, 26)], 12)
    stroke(c, top, 1.9)
    for i in range(2, len(top) - 2, 3):
        bx, by = top[i]
        leaf(c, bx, by, rng.uniform(11, 15), rng.uniform(-122, -58))
        leaf(c, bx, by, rng.uniform(8, 11), rng.uniform(-102, -78))   # a paired leaf
        if i % 2 == 0:
            dot(c, bx, by - rng.uniform(2, 4), 1.5)                   # a little bud
    bot = smooth([(-6, H - 30), (80, H - 22), (170, H - 36), (260, H - 22),
                  (W + 6, H - 30)], 12)
    stroke(c, bot, 1.9)
    for i in range(2, len(bot) - 2, 3):
        bx, by = bot[i]
        leaf(c, bx, by, rng.uniform(11, 15), rng.uniform(58, 122))
        leaf(c, bx, by, rng.uniform(8, 11), rng.uniform(78, 102))     # a paired leaf
        if i % 2 == 0:
            dot(c, bx, by + rng.uniform(2, 4), 1.5)                   # a little bud
    for (bx, by) in [(40, 40), (W - 40, 36), (50, H - 40), (W - 50, H - 38)]:
        for a in range(5):
            aa = math.radians(a * 72)
            c.d.ellipse([S * (bx + 5 * math.cos(aa) - 3), S * (by + 5 * math.sin(aa) - 3),
                         S * (bx + 5 * math.cos(aa) + 3), S * (by + 5 * math.sin(aa) + 3)],
                        outline=INK, width=max(1, int(1.0 * S)))
        dot(c, bx, by, 2)
    return (34, 52, 332, 190), []


def sc_dove_descending(c):
    # an ascending dove over a quiet horizon — generous lower text canvas
    dove(c, 202, 112, 68)
    hill_outline(c, 276, 7, 1.3, seed_extra=6)
    return (40, 158, 320, 92), []


def sc_wheat_field(c):
    # A calm harvest field: one clean sheaf, ordered furrows, and recognizable
    # stalks. No loose hatch marks in the sky or text canvas.
    sun_plain(c, 342, 118, r=13, rays=16, r1=31)
    horizon = smooth([(-6, 218), (64, 211), (138, 219), (230, 210),
                      (W + 6, 216)], 10)
    stroke(c, horizon, 1.2)
    for k in range(5):
        y = 226 + k * 12
        amp = 2.0 + k * 0.35
        pts = [(x, y + amp * math.sin((x - 40) / 78)) for x in range(0, W + 1, 8)]
        stroke(c, pts, 1.0)
    # tied sheaf on the left, composed of individual stalks with visible grain.
    base_x, base_y = 86, 292
    for h, lean in [(62, -22), (70, -13), (80, -4), (78, 7), (68, 16), (60, 24)]:
        wheat(c, base_x, base_y, h, INK, lean=lean, awns=True)
    c.d.rounded_rectangle([S * 68, S * 256, S * 104, S * 268], radius=3 * S,
                          fill=INK)
    for yy in (260, 265):
        line(c, (70, yy), (102, yy), 0.8, PAPER)
    line(c, (74, 268), (60, 292), 1.2)
    line(c, (98, 268), (114, 292), 1.2)
    # a modest right-side stand balances the composition without turning noisy.
    for x, h, lean in [(278, 54, -5), (306, 64, 4), (332, 50, 8)]:
        wheat(c, x, 292, h, INK, lean=lean, awns=True)
    return (34, 34, 270, 152), []


def sc_mountain_path(c):
    # a path winding toward distant peaks between two trees — text canvas top.
    # rays fan only upward (a rising sun behind the peak) so nothing rakes down
    # across the meadow and muddles the path
    far = smooth([(-6, 184), (60, 152), (130, 178), (200, 142), (280, 176),
                  (W + 6, 152)], 8)
    fill(c, far + [(W + 6, 190), (-6, 190)], INK)
    engrave_ridge(c, far, 190, n=4, gap=8, inset=6, w=1.0, fade=0.28)
    for (px, py) in [(200, 142), (60, 152)]:   # snow on the two high peaks
        fill(c, [(px, py + 2), (px - 8, py + 16), (px - 2, py + 13),
                 (px + 2, py + 17), (px + 7, py + 13)], PAPER)
    # meadow line
    line(c, (0, 200), (W, 196), 1.0)
    # broad path with gentle perspective: it narrows, but never pinches into a
    # needle at the mountains.
    left_edge = smooth([(154, H), (168, 262), (178, 224), (182, 198)], 10)
    right_edge = smooth([(246, H), (232, 262), (222, 224), (218, 198)], 10)
    fill(c, left_edge + right_edge[::-1], PAPER)
    path = [(154, H), (168, 262), (178, 224), (182, 198)]
    pathR = [(246, H), (232, 262), (222, 224), (218, 198)]
    stroke(c, path, 1.7)
    stroke(c, pathR, 1.7)
    for i in range(6):
        t = i / 6
        y = 300 - 100 * t
        hw = 42 * (1 - t) + 12
        line(c, (200 - hw, y), (200 + hw, y), 0.9)
    # flanking pines matching the crane-moon tree language.
    pine(c, 52, 300, 70)
    pine(c, 94, 300, 50)
    pine(c, 312, 300, 46)
    pine(c, 354, 300, 64)
    return (44, 24, 312, 98), []


def sc_open_book(c):
    # an open Bible with a simple halo above the page — text canvas up top
    hill_outline(c, 272, 10, 1.4, seed_extra=11)
    open_book(c, 200, 236, 180)
    # The verse zone ends at y=166. Keep the sunburst fully below it while still
    # giving the page a clear "word as light" glow.
    sun_plain(c, 200, 199, r=15, w=1.2, rays=14, r1=28)
    return (34, 24, 332, 142), []


def sc_sailboat_dawn(c):
    # a little sailboat on a calm sea, sun low at the horizon — text canvas up top
    sun_medallion(c, 348, 206, r=13, rays=16, r1=33)
    line(c, (0, 226), (W, 224), 1.0)
    boat(c, 258, 221, 15, INK)                   # a distant sail for depth
    boat(c, 118, 210, 54, INK)                   # the near sailboat, larger
    fill(c, [(118, 160), (142, 165), (118, 170)], INK)     # masthead pennant
    for dy in (5, 11, 17):                       # its reflection, broken by ripples
        hw = 20 - dy * 0.5
        line(c, (118 - hw, 230 + dy), (118 + hw, 230 + dy), 1.1)
    water_lines(c, 232, 298, gap=8, w=1.2, seed=5)
    for k in range(5):                           # sun shimmer running to shore
        yy = 230 + k * 12
        hw = 5 + k * 3
        line(c, (348 - hw, yy), (348 + hw, yy), 1.3)
    return (40, 24, 326, 126), []


def sc_starry_night(c):
    # minimalist night sky, crescent moon, a hill with pines — white ink text
    zone = (18, 22, 328, 200)
    stars(c, 80, zone=zone, y1=232, vmin=210)
    # small crescent moon tucked into the corner (white disc carved by a black one)
    disc(c, 366, 44, 16, 255)
    disc(c, 373, 40, 14, INK)
    # hill's white crest line + a fringe of pines along the very bottom
    stroke(c, ridge_pts(c, 246, 24, seed_extra=3), 1.4, 255)
    for x, h in [(48, 30), (78, 22), (330, 34), (360, 24), (300, 18)]:
        pine(c, x, 264, h, val=255)
    return zone, ["night", "wink"]


def sc_moonlit_hills(c):
    # clean full moon over layered hills — white ink text
    zone = (26, 30, 282, 152)
    stars(c, 44, zone=zone, y1=150, vmin=210)
    disc(c, 352, 80, 25, 255)
    # layered hills: no random foreground blobs, just clean white crest lines
    for by, amp, s in [(200, 14, 21), (230, 18, 22), (264, 24, 23)]:
        r = ridge_pts(c, by, amp, seed_extra=s)
        stroke(c, r, 1.4, 255)
    for x, h in [(44, 44), (72, 30), (328, 34), (360, 58)]:
        pine(c, x, 300, h, val=255)
    return zone, ["night", "wink"]


# ================================================================ ukiyo-e / water
def _claw(c, x, y, ang, ln, wd=3.0, val=INK):
    """A curling foam finger (Hokusai's grasping claw): a tapered blade that
    hooks over at the tip."""
    a = math.radians(ang)
    perp = a + math.pi / 2
    spine = []
    for t in (0.0, 0.4, 0.72, 1.0):
        curl = 0.7 * t * t
        px = x + ln * t * math.cos(a) + ln * curl * math.cos(a + 1.6)
        py = y + ln * t * math.sin(a) + ln * curl * math.sin(a + 1.6)
        spine.append((px, py))
    left, right = [], []
    for i, (px, py) in enumerate(spine):
        wt = wd * (1 - i / len(spine)) + 0.5
        left.append((px + wt * math.cos(perp), py + wt * math.sin(perp)))
        right.append((px - wt * math.cos(perp), py - wt * math.sin(perp)))
    fill(c, left + right[::-1], val)


def foam_scallop(c, pts, r0=5.5, val=INK):
    """A ribbon of foam bubbles (paper discs with a thin ink rim) along a crest."""
    rng = c.rng
    for (x, y) in pts:
        r = r0 * rng.uniform(0.7, 1.15)
        disc(c, x, y, r, PAPER)
        ring(c, x, y, r, 1.2, val)


def fuji(c, fx, fbase, fh, snow=0.30, ridges=True, val=INK):
    """One iconic Mt. Fuji: gently concave slopes flaring to a wide skirt, a
    sharp summit, and a carved snow crown with the classic jagged hem."""
    paper = PAPER if val == INK else INK
    peak = fbase - fh
    exp = 1.55
    left = []
    N = 30
    for i in range(N + 1):
        t = i / N                              # 0 at the skirt, 1 at the summit
        left.append((fx - fh * 0.98 * (1 - t), fbase - fh * (t ** exp)))
    fill(c, left + [(2 * fx - x, y) for (x, y) in reversed(left)], val)
    # snow: on a white sky a white cap would vanish, so the mountain stays a
    # pointed black silhouette and the snow is carved as a white drift INSET from
    # the slopes — a uniform black rim and a black peak-tip keep the summit
    # reading, with a jagged lower hem for the classic snow line. Tracing the
    # mountain's own curve (inset) means the rim never diverges into a hairline.
    snow_t = (1 - snow) ** (1 / exp)               # slope param at the snow line
    inset = fh * 0.06                              # black rim kept along each slope
    tip_t = 0.92                                   # leave the very tip black
    ts = [snow_t + (tip_t - snow_t) * i / 20 for i in range(21)]
    snowL = [(fx - fh * 0.98 * (1 - t) + inset, fbase - fh * (t ** exp)) for t in ts]
    snowR = [(2 * fx - x, y) for (x, y) in reversed(snowL)]
    hemL, hemR = snowL[0], snowR[-1]
    hem = [(hemL[0] + (hemR[0] - hemL[0]) * (i / 6),
            hemL[1] - (fh * 0.05 if i % 2 else 0.0)) for i in range(7)]
    fill(c, snowL + snowR + hem[::-1], paper)
    if ridges:
        for sgn in (-1, 1):
            line(c, (fx + sgn * fh * 0.04, peak + fh * snow * 1.1),
                 (fx + sgn * fh * 0.5, fbase - fh * 0.12), 1.0, paper)


def crane(c, x, y, s_, val=INK):
    """A crane in flight (side/below view): a slim spindle body, a long neck to a
    small head + beak reaching forward, trailing legs, and two long wings swept
    up and out in a wide shallow V — an unmistakable flying-bird silhouette."""
    body = smooth([(x - 0.30 * s_, y + 0.05 * s_), (x + 0.02 * s_, y - 0.02 * s_),
                   (x + 0.30 * s_, y + 0.01 * s_), (x + 0.02 * s_, y + 0.13 * s_),
                   (x - 0.28 * s_, y + 0.12 * s_)], 12)
    fill(c, body, val)
    neck = smooth([(x + 0.24 * s_, y), (x + 0.50 * s_, y - 0.06 * s_),
                   (x + 0.72 * s_, y - 0.11 * s_)], 10)             # neck forward
    stroke(c, neck, max(1.6, 0.06 * s_), val)
    disc(c, x + 0.73 * s_, y - 0.12 * s_, 0.05 * s_, val)           # head
    line(c, (x + 0.78 * s_, y - 0.12 * s_), (x + 0.92 * s_, y - 0.13 * s_),
         1.3, val)                                                  # beak
    stroke(c, smooth([(x - 0.26 * s_, y + 0.10 * s_),                # trailing legs
                      (x - 0.55 * s_, y + 0.14 * s_),
                      (x - 0.80 * s_, y + 0.12 * s_)], 8),
           max(1.3, 0.04 * s_), val)
    for sgn in (-1, 1):                                             # swept-V wings
        wing = smooth([(x + 0.03 * s_, y - 0.01 * s_),
                       (x + sgn * 0.34 * s_, y - 0.34 * s_),
                       (x + sgn * 0.80 * s_, y - 0.54 * s_),
                       (x + sgn * 0.82 * s_, y - 0.44 * s_),
                       (x + sgn * 0.38 * s_, y - 0.16 * s_),
                       (x + 0.05 * s_, y + 0.07 * s_)], 14)
        fill(c, wing, val)


def cloud_band(c, cy, x0, x1, h=12):
    """A drifting mist lozenge: it tapers to a soft point at both ends (an
    envelope over the ripple) so it reads as a cloud floating on the slope — not a
    band slicing the mountain in two. Keep it well inside the silhouette."""
    span = max(1, x1 - x0)
    top, bot = [], []
    for x in range(x0, x1 + 1, 4):
        t = (x - x0) / span
        env = math.sin(math.pi * t) ** 0.7          # 0 at both ends -> pointed cloud
        hh = (h / 2) * env
        top.append((x, cy - hh - 1.4 * env * math.sin(x / 30)))
        bot.append((x, cy + hh + 1.4 * env * math.sin(x / 26 + 1.0)))
    fill(c, top + bot[::-1], PAPER)


def sc_great_wave(c):
    """After Hokusai's Great Wave: a towering breaker on the left flinging foam
    claws, a small Mt. Fuji off to the right, ruled swells below — a generous
    upper-right sky carries the verse."""
    rng = c.rng
    # --- distant Fuji, low and to the right, clear of the text sky
    fuji(c, 250, 216, 44, snow=0.4)
    # --- ruled ocean swells low across the frame (kept below the text zone)
    water_lines(c, 214, 262, x0=0, x1=W, gap=9, w=1.3, seed=21)
    water_lines(c, 224, 258, x0=0, x1=W, gap=22, w=1.0, val=INK, seed=8)
    # --- the great wave: a solid breaking mass in the left third, then carved
    body = smooth([(-54, 300), (-54, 176), (-30, 150), (2, 120), (40, 88),
                   (78, 66), (114, 62), (142, 78), (154, 104),    # crest + lip
                   (144, 130), (117, 137), (104, 158),            # under the lip
                   (82, 156), (60, 142), (38, 146), (16, 164),    # scalloped front
                   (-6, 182), (-30, 200), (-54, 214)], 14)
    fill(c, body, INK)
    # the barrel: carve the eye of the wave back to paper
    barrel = smooth([(104, 156), (104, 128), (116, 110), (136, 106), (151, 118),
                     (146, 136), (128, 150), (104, 156)], 12)
    fill(c, barrel, PAPER)
    # engraved contour lines rake up the wave's front face (linocut water)
    for k in range(1, 5):
        seg = smooth([(-54 + k * 4, 206 - k * 8), (-6, 184 - k * 9),
                      (26, 158 - k * 8), (54, 140 - k * 7),
                      (78, 132 - k * 6)], 10)
        stroke(c, seg, 1.0, PAPER)
    # turbulent foam: a bold back rank of bubbles + a fine froth, then grasping
    # claws curling off the crest (all kept left of the sky zone)
    crest = smooth([(18, 100), (58, 76), (100, 66), (136, 72), (148, 96)], 5)
    foam_scallop(c, crest[::2], r0=6.5)
    foam_scallop(c, [(x + 3, y - 5) for (x, y) in crest[1::3]], r0=3.6)
    for (bx, by, ang, ln, wd) in [(100, 64, -12, 30, 3.6), (126, 68, 4, 26, 3.2),
                                  (140, 84, 26, 16, 2.8), (70, 74, -22, 24, 3.2)]:
        _claw(c, bx, by, ang, ln, wd)
    # a few flecks of spray flung ahead of the crest (kept left of the zone)
    for _ in range(9):
        sx, sy = rng.uniform(104, 150), rng.uniform(52, 96)
        dot(c, sx, sy, rng.uniform(1.0, 1.8), INK)
    return (160, 34, 226, 124), ["water"]


def sc_fuji_serene(c):
    """South-wind Fuji: one clean, iconic snow-crowned peak over a soft distant
    foothill — a generous clear sky holds the verse. (White mist over a black
    mountain only ever reads as snow ledges, so the peak is left uncluttered.)"""
    hill_outline(c, 256, 12, 1.2, seed_extra=5)   # a distant foothill for depth
    fuji(c, 200, 270, 120, snow=0.30)
    line(c, (0, 288), (W, 286), 1.0)              # a quiet groundline
    return (30, 20, 340, 122), ["water"]


def sc_crane_moon(c):
    """A crane crossing a great low moon over a moonlit sea — white ink on night.
    A wide clean dark sky at the left carries the verse."""
    zone = (22, 28, 252, 158)
    stars(c, 42, zone=zone, y1=184, vmin=210)
    disc(c, 330, 120, 47, 255)                  # the great moon
    crane(c, 330, 122, 42, val=INK)             # crane silhouetted on the moon
    band = [(x, 150 + 3 * math.sin(x / 22)) for x in range(300, 366, 5)]
    stroke(c, band, 2.6, INK)                   # a faint wisp drifts below it
    line(c, (0, 232), (W, 230), 1.2, 255)       # sea horizon
    water_lines(c, 238, 292, x0=0, x1=W, gap=8, w=1.2, val=255, seed=4)
    for k in range(5):                          # the moon's shimmer on the water
        yy, hw = 238 + k * 11, 6 + k * 3
        line(c, (330 - hw, yy), (330 + hw, yy), 1.3, 255)
    pine(c, 42, 300, 58, val=255)               # a pine bough in the near corner
    return zone, ["night", "water", "wink"]


SCENES = [
    ("note-flourish", sc_note_flourish),
    ("celebration", sc_celebration),
    ("golgotha-dawn", sc_golgotha_dawn),
    ("shepherd", sc_shepherd),
    ("lighthouse", sc_lighthouse),
    ("still-waters", sc_still_waters),
    ("empty-tomb", sc_empty_tomb),
    ("botanical-frame", sc_botanical_frame),
    ("dove-ascending", sc_dove_descending),
    ("mountain-path", sc_mountain_path),
    ("open-book", sc_open_book),
    ("sailboat-dawn", sc_sailboat_dawn),
    ("starry-night", sc_starry_night),
    ("moonlit-hills", sc_moonlit_hills),
    ("great-wave", sc_great_wave),
    ("fuji-serene", sc_fuji_serene),
    ("crane-moon", sc_crane_moon),
]


# ---------------------------------------------------------------- export
NIGHT_SCENES = {"starry-night", "moonlit-hills", "crane-moon"}


def _despeckle(img, night):
    """Remove lone threshold specks that read as noise: on day scenes, isolated
    BLACK pixels sitting on clean paper (all 8 neighbours white). Night scenes are
    left untouched — their lone white pixels are intended stars. Deterministic and
    purely subtractive: it can only erase a floating dot, never add or move ink."""
    if night:
        return img
    px = img.load()
    w, h = img.size
    flip = []
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if px[x, y] != 0:
                continue
            if all(px[x + dx, y + dy] == 255
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy):
                flip.append((x, y))
    for (x, y) in flip:
        px[x, y] = 255
    return img


def export(idx, name, fn):
    c = C(name, bg=INK if name in NIGHT_SCENES else PAPER)
    zone, tags = fn(c)
    white_ink = "wink" in tags
    tags = [t for t in tags if t != "wink"]
    small = c.img.resize((W, H), Image.BILINEAR)
    bw = small.convert("1", dither=Image.Dither.NONE)   # threshold, no dither
    bw = _despeckle(bw, name in NIGHT_SCENES)           # kill lone ink grain
    raw = bw.tobytes()       # PIL: bit=1 -> white; we want bit=1 -> black
    data = bytes(b ^ 0xFF for b in raw)
    assert len(data) == W * H // 8, f"{name}: {len(data)} bytes"
    with open(os.path.join(BG_DIR, f"{idx:03d}.bin"), "wb") as f:
        f.write(data)
    prev = bw.convert("L").resize((W * 2, H * 2), Image.NEAREST)
    prev.save(os.path.join(PREV_DIR, f"{idx:03d}_{name}.png"))
    return {"i": idx, "name": name, "zone": list(zone), "tags": tags,
            "ink": "white" if white_ink else "black"}, bw


def make_icons():
    for size, fname in ((512, "icon-512.png"), (180, "icon.png")):
        img = Image.new("L", (size * 2, size * 2), 245)
        d = ImageDraw.Draw(img)
        m = size * 2
        d.rounded_rectangle([0, 0, m - 1, m - 1], radius=m // 5, fill=38)
        cw = m * 0.1
        d.rectangle([m / 2 - cw / 2, m * 0.16, m / 2 + cw / 2, m * 0.84], fill=245)
        d.rectangle([m * 0.26, m * 0.36, m * 0.74, m * 0.36 + cw], fill=245)
        hy = m * 0.36 + cw / 2
        hs = m * 0.045
        for sgn in (-1, 1):
            d.ellipse([m / 2 + sgn * hs * 0.5 - hs * 0.62, hy - hs * 0.7,
                       m / 2 + sgn * hs * 0.5 + hs * 0.62, hy + hs * 0.5], fill=38)
        d.polygon([(m / 2 - hs * 1.1, hy), (m / 2, hy + hs * 1.5),
                   (m / 2 + hs * 1.1, hy)], fill=38)
        img = img.resize((size, size), Image.LANCZOS).convert("RGB")
        img.save(os.path.join(WWW_DIR, fname))


def main():
    os.makedirs(BG_DIR, exist_ok=True)
    os.makedirs(WWW_DIR, exist_ok=True)
    os.makedirs(PREV_DIR, exist_ok=True)
    index = []
    thumbs = []
    for idx, (name, fn) in enumerate(SCENES):
        meta, bw = export(idx, name, fn)
        index.append(meta)
        thumbs.append(bw.convert("L"))
        print(f"  [{idx:2d}] {name:18} zone={meta['zone']} {meta['tags']}")
    with open(os.path.join(BG_DIR, "index.json"), "w") as f:
        json.dump(index, f, separators=(",", ":"))
    cols, tw, th = 5, 200, 150
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("L", (cols * (tw + 4), rows * (th + 4)), 128)
    for i, t in enumerate(thumbs):
        sheet.paste(t.resize((tw, th)), ((i % cols) * (tw + 4) + 2,
                                         (i // cols) * (th + 4) + 2))
    sheet.save(os.path.join(PREV_DIR, "_sheet.png"))
    make_icons()
    print(f"\n{len(SCENES)} backgrounds -> {BG_DIR}")
    print(f"previews -> {PREV_DIR}\\_sheet.png")


if __name__ == "__main__":
    main()
