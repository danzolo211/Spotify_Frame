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
BG_DIR = os.path.join(ROOT, "GraceFrame", "data", "bg")
WWW_DIR = os.path.join(ROOT, "GraceFrame", "data", "www")
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


def sun_lined(c, x, y, r, rays=18, r1=None, w=1.6, val=INK, a0=0, a1=360):
    """an outlined sun with a ring of straight rays — airy and postcard-y."""
    r1 = r1 if r1 else r * 2.1
    sun_rays(c, x, y, r + 5, r1, rays, a0, a1, w=w, val=val)
    ring(c, x, y, r, w=w, val=val)


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


def birds(c, pts, s_=5, w=1.3, val=INK):
    for (x, y) in pts:
        c.d.arc([S * (x - s_), S * (y - s_ * 0.7), S * x, S * (y + s_ * 0.7)],
                200, 335, fill=val, width=max(1, int(w * S)))
        c.d.arc([S * x, S * (y - s_ * 0.7), S * (x + s_), S * (y + s_ * 0.7)],
                205, 340, fill=val, width=max(1, int(w * S)))


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
    """A clean broadleaf tree: a slim trunk under a single full, gently scalloped
    canopy (a smooth closed curve, not a pile of lumpy discs)."""
    line(c, (x, base), (x, base - h * 0.46), max(1.6, h * 0.07), val)
    cx, cy, rw, rh = x, base - h * 0.66, h * 0.40, h * 0.42
    canopy = []
    bumps = 11
    for i in range(bumps):
        a = -math.pi / 2 + 2 * math.pi * i / bumps
        # a gentle scallop on the radius so the crown reads as leaves, not a ball
        rr = 1.0 + 0.09 * math.sin(a * 5)
        canopy.append((cx + rw * rr * math.cos(a), cy + rh * rr * math.sin(a)))
    fill(c, smooth(canopy + [canopy[0]], 10), val)


def sheep(c, x, y, s_, val=INK):
    """A small, tidy sheep: a round fleece body with a scalloped top, a dark
    head on a short neck, and four fine legs. Legible even at postcard size."""
    # legs first (behind the body)
    for lx in (-0.24, -0.06, 0.30, 0.48):
        line(c, (x + lx * s_, y + 0.18 * s_), (x + lx * s_, y + 0.62 * s_),
             max(1.1, 0.055 * s_), val)
    # fleece body: an oval with a few soft bumps carved into its crown
    c.d.ellipse([S * (x - 0.62 * s_), S * (y - 0.34 * s_),
                 S * (x + 0.5 * s_), S * (y + 0.34 * s_)], fill=val)
    for bx in (-0.4, -0.16, 0.08, 0.32):
        disc(c, x + bx * s_, y - 0.34 * s_, 0.15 * s_, val)
    # head + short neck (facing right, slightly down as if grazing)
    hx, hy = x + 0.58 * s_, y - 0.12 * s_
    fill(c, [(x + 0.28 * s_, y - 0.14 * s_), (hx, hy - 0.16 * s_),
             (hx + 0.02 * s_, hy + 0.18 * s_), (x + 0.30 * s_, y + 0.14 * s_)], val)
    c.d.ellipse([S * (hx - 0.16 * s_), S * (hy - 0.17 * s_),
                 S * (hx + 0.19 * s_), S * (hy + 0.17 * s_)], fill=val)
    disc(c, hx + 0.06 * s_, hy - 0.03 * s_, 0.03 * s_,
         PAPER if val == INK else INK)   # eye
    c.d.arc([S * (hx - 0.14 * s_), S * (hy - 0.30 * s_),   # a small ear
             S * (hx + 0.02 * s_), S * (hy - 0.06 * s_)], 20, 160,
            fill=val, width=max(1, int(0.05 * s_ * S)))


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
    w0, w1 = h * 0.19, h * 0.11
    fill(c, [(x - w0 / 2, base), (x - w1 / 2, base - h * 0.7),
             (x + w1 / 2, base - h * 0.7), (x + w0 / 2, base)], val)
    # lantern room
    c.d.rectangle([S * (x - w1 * 0.75), S * (base - h * 0.78),
                   S * (x + w1 * 0.75), S * (base - h * 0.7)], fill=val)
    fill(c, [(x - w1 * 0.8, base - h * 0.9), (x, base - h),
             (x + w1 * 0.8, base - h * 0.9)], val)
    # windows carved out (paper)
    c.d.rectangle([S * (x - w1 * 0.5), S * (base - h * 0.9),
                   S * (x + w1 * 0.5), S * (base - h * 0.79)], fill=PAPER)
    # two stripes carved from the tower
    for t in (0.24, 0.46):
        ww = w0 + (w1 - w0) * t
        c.d.rectangle([S * (x - ww / 2 + 1), S * (base - h * (t + 0.09)),
                       S * (x + ww / 2 - 1), S * (base - h * t)], fill=PAPER)


def dove(c, x, y, s_, val=INK):
    """An iconic dove alighting: plump breast, small head, a fanned tail, and two
    broad wings lifted overhead. Read from the side — unmistakably a dove."""
    s = s_
    paper = PAPER if val == INK else INK
    # ---- fanned tail: three clean pointed feathers sweeping back-left
    tb = (x - 0.24 * s, y + 0.02 * s)
    for tx_, ty_ in [(-1.00, -0.26), (-1.10, -0.04), (-1.02, 0.20)]:
        fill(c, [(tb[0], tb[1] - 0.11 * s), (x + tx_ * s, y + ty_ * s),
                 (tb[0], tb[1] + 0.11 * s)], val)
    # ---- body: full breast to the right, tapering into the tail at the left
    body = smooth([(x + 0.30 * s, y - 0.02 * s),    # throat
                   (x + 0.33 * s, y + 0.16 * s),    # breast
                   (x + 0.06 * s, y + 0.30 * s),    # belly
                   (x - 0.26 * s, y + 0.20 * s),
                   (x - 0.28 * s, y - 0.04 * s),    # tail base
                   (x - 0.06 * s, y - 0.18 * s),
                   (x + 0.16 * s, y - 0.16 * s)], 16)
    fill(c, body, val)
    # ---- head + short beak, lifted up-right; neck bridges to the body
    hx, hy = x + 0.42 * s, y - 0.24 * s
    fill(c, [(x + 0.10 * s, y - 0.14 * s), (hx - 0.10 * s, hy - 0.08 * s),
             (hx + 0.08 * s, hy + 0.14 * s), (x + 0.24 * s, y + 0.06 * s)], val)
    disc(c, hx, hy, 0.155 * s, val)
    fill(c, [(hx + 0.10 * s, hy - 0.05 * s), (hx + 0.32 * s, hy + 0.01 * s),
             (hx + 0.10 * s, hy + 0.07 * s)], val)   # beak
    disc(c, hx + 0.02 * s, hy - 0.02 * s, 0.032 * s, paper)   # eye
    # ---- near wing (in front of body): the hero — a broad curved blade
    near = smooth([(x + 0.18 * s, y - 0.02 * s),   # shoulder
                   (x + 0.40 * s, y - 0.44 * s),   # leading edge
                   (x + 0.28 * s, y - 0.92 * s),   # tip
                   (x + 0.04 * s, y - 0.88 * s),
                   (x - 0.12 * s, y - 0.52 * s),   # trailing edge
                   (x - 0.16 * s, y - 0.18 * s),
                   (x + 0.02 * s, y - 0.06 * s)], 16)
    fill(c, near, val)
    # three feather separations carved across the near wing
    for lx, ly, tx, ty in [(0.30, -0.30, 0.04, -0.24), (0.24, -0.52, -0.06, -0.44),
                           (0.16, -0.72, -0.06, -0.64)]:
        line(c, (x + lx * s, y + ly * s), (x + tx * s, y + ty * s), 0.9, paper)


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
    # great round stone, rolled clear of the mouth to the right; a carved rim
    # highlight gives it weight, a ground groove shows it was rolled aside
    st_x, st_r = x + s_ * 1.36, s_ * 0.5
    disc(c, st_x, base - st_r * 0.86, st_r, val)
    c.d.arc([S * (st_x - st_r * 0.62), S * (base - st_r * 0.86 - st_r * 0.62),
             S * (st_x + st_r * 0.2), S * (base - st_r * 0.86 + st_r * 0.2)],
            150, 255, fill=paper, width=max(1, int(1.0 * S)))   # rim highlight
    line(c, (x + s_ * 0.52, base), (st_x - st_r * 0.55, base), 1.2, val)


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


def wheat(c, x, base, h, val=INK, lean=3):
    """A single graceful wheat stalk: a slender curved stem, long fine awns, and
    crisp paired kernels climbing the top third — each kernel a clean teardrop
    carved with a center vein so it reads as grain, not a feathery blob."""
    paper = PAPER if val == INK else INK
    stem = smooth([(x, base), (x + lean * 0.4, base - h * 0.5),
                   (x + lean, base - h)], 12)
    stroke(c, stem, 1.8, val)
    tx, ty = x + lean, base - h
    for aw in (-0.10, -0.035, 0.035, 0.10):       # long fine awns crowning the ear
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
    return (46, 54, 308, 188), ["special"]


def sc_celebration(c):
    # a radiant sunrise crown up top + full laurel branches curving up from the
    # base to a heart — canvas kept clean in the middle
    cx = W / 2
    sun_rays(c, cx, 44, 20, 84, n=24, a0=180, a1=360, w=1.5)   # a full fan of rays
    ring(c, cx, 44, 18, 2.0)
    disc(c, cx, 44, 5)
    for sgn in (-1, 1):                                        # flourish rule
        line(c, (cx + sgn * 14, 70), (cx + sgn * 94, 70), 1.0)
        dot(c, cx + sgn * 100, 70, 2.4)
    dot(c, cx, 70, 2.6)
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
    return (50, 78, 300, 146), ["special"]


def sc_golgotha_dawn(c):
    # three crosses on a hill, sun rising low behind it — text canvas at right
    sun_rays(c, 104, 196, 30, 100, n=13, a0=198, a1=340, w=1.3)
    ring(c, 104, 196, 24, 1.8)
    pts = smooth([(-6, 214), (70, 198), (150, 192), (250, 216), (330, 238),
                  (W + 6, 252)], 10)
    fill(c, pts + [(W + 6, H + 6), (-6, H + 6)], INK)
    # light rakes across the crown of the hill — carved contour lines give the
    # mound real form instead of a flat silhouette
    engrave_ridge(c, pts, H, n=7, gap=8, inset=6, w=1.0, fade=0.5)
    # a footpath worn up the near slope, a couple of scattered stones
    line(c, (196, H), (150, 230), 1.1, PAPER)
    line(c, (206, H), (168, 228), 1.1, PAPER)
    for sx, sy, sr in [(232, 246, 3), (256, 232, 2.4), (300, 252, 3.2)]:
        ring(c, sx, sy, sr, 0.9, PAPER)
    cross(c, 108, 200, 84)
    cross(c, 62, 212, 54, tilt=-7)
    cross(c, 154, 210, 56, tilt=7)
    birds(c, [(58, 70), (74, 62), (94, 72)], 5)
    return (214, 58, 166, 146), []


def sc_shepherd(c):
    # shepherd leading a little flock across a meadow; a low sun behind him.
    # black silhouettes on a soft groundline — airy, postcard-clean.
    sun_lined(c, 352, 66, 15, rays=13, r1=40, w=1.2, a0=112, a1=248)
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
    sun_rays(c, lx, ly, 7, 12, n=8, w=0.7)
    stroke(c, [(lx, ly), (250, 44)], 1.0)          # upper edge of the beam
    stroke(c, [(lx, ly), (214, 96)], 1.0)          # lower edge of the beam
    for fx, fy in [(238, 60), (226, 78)]:          # two guide rays inside the cone
        line(c, (lx, ly), (fx, fy), 0.6)
    water_lines(c, 250, 300, x0=0, x1=246, gap=8, w=1.2, seed=7)
    birds(c, [(58, 236), (80, 229), (102, 236)], 7)  # gulls low over the water
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
    far = smooth([(-6, 158), (60, 138), (140, 150), (230, 132), (320, 150),
                  (W + 6, 140)], 12)
    stroke(c, far, 1.1)
    Lpeaks = [(-6, 150), (44, 128), (92, 100), (150, 140)]
    Rpeaks = [(232, 150), (270, 128), (312, 94), (356, 132), (W + 6, 122)]
    Lridge, Rridge = smooth(Lpeaks, 14), smooth(Rpeaks, 14)
    Lpoly = Lridge + [(Lpeaks[-1][0], hz), (Lpeaks[0][0], hz)]
    Rpoly = Rridge + [(Rpeaks[-1][0], hz), (Rpeaks[0][0], hz)]
    fill(c, Lpoly, INK)
    fill(c, Rpoly, INK)
    # carved contour lines rake down each face -> sculpted rock, not flat black
    engrave_ridge(c, Lridge, hz, n=5, gap=9, inset=8, w=1.0, fade=0.42)
    engrave_ridge(c, Rridge, hz, n=6, gap=9, inset=8, w=1.0, fade=0.42)
    for (px, py) in [(92, 100), (312, 94)]:       # snow caps carved out
        fill(c, [(px, py + 2), (px - 9, py + 18), (px - 3, py + 15),
                 (px + 1, py + 19), (px + 8, py + 15)], PAPER)
    line(c, (0, hz), (W, hz), 1.0)
    # reflection: mirror the two ranges below the horizon, softened by ripples
    mir = lambda poly: [(x, 2 * hz - y) for (x, y) in poly]
    fill(c, mir(Lpoly), INK)
    fill(c, mir(Rpoly), INK)
    water_lines(c, hz + 5, 298, gap=7, w=1.7, val=PAPER, seed=3)
    water_lines(c, hz + 14, 296, gap=26, w=1.0, val=INK, seed=8)
    # a small sun tucked in the valley gap + a shimmer running toward us
    sun_lined(c, 191, 150, 11, rays=12, r1=24, w=1.0, a0=186, a1=354)
    for k in range(5):
        yy = hz + 8 + k * 12
        hw = 5 + k * 3
        line(c, (191 - hw, yy), (191 + hw, yy), 1.4)
    return (30, 22, 340, 84), []


def sc_empty_tomb(c):
    # the empty tomb at dawn, lilies at the door — text canvas upper right
    sun_rays(c, 92, 98, 22, 74, n=13, a0=205, a1=335, w=1.3)
    ring(c, 92, 98, 18, 1.8)
    disc(c, 92, 98, 3)
    hill_outline(c, 252, 14, 1.4, seed_extra=2)
    ground = smooth([(-6, 270), (140, 264), (280, 270), (W + 6, 264)], 8)
    stroke(c, ground, 1.4)
    tomb(c, 108, 268, 58)
    # a small stand of Easter lilies rising at the foot of the doorway, spaced
    # so each trumpet bloom reads on its own
    lily(c, 56, 273, 34)
    lily(c, 84, 275, 25)
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
    # a descending dove with light breaking above it — text canvas lower
    sun_rays(c, 202, 96, 62, 92, n=18, a0=188, a1=352, w=1.0)   # radiance above
    dove(c, 202, 96, 50)
    hill_outline(c, 262, 12, 1.4, seed_extra=6)
    return (40, 150, 320, 100), []


def sc_wheat_field(c):
    # a small sheaf of wheat leaning in from the lower left, a low sun at right,
    # and a fine horizon — the whole right side stays open for the verse
    sun_lined(c, 332, 236, 16, rays=13, r1=30, w=1.1, a0=200, a1=340)
    hill_outline(c, 250, 10, 1.2, seed_extra=9)
    line(c, (0, 282), (W, 280), 1.0)
    # a gathered sheaf: five stalks fanning from a common foot, each ear reading
    # on its own, bound low with a wrapped band
    for h, lean in [(150, -46), (170, -24), (182, -2), (170, 22), (150, 44)]:
        wheat(c, 106, 300, h, INK, lean=lean)
    c.d.rounded_rectangle([S * 92, S * 258, S * 120, S * 272], radius=3 * S,
                          fill=INK)                       # binding band
    line(c, (98, 272), (90, 288), 1.4)                    # loose tie ends
    line(c, (112, 272), (120, 289), 1.4)
    for gx, ga in [(176, -18), (44, -150), (60, -30)]:    # a few fallen grains
        leaf(c, gx, 289, 5, ga)
    return (176, 38, 200, 182), []


def sc_mountain_path(c):
    # a path winding toward distant peaks between two trees — text canvas top.
    # rays fan only upward (a rising sun behind the peak) so nothing rakes down
    # across the meadow and muddles the path
    sun_lined(c, 200, 150, 16, rays=12, r1=40, w=1.0, a0=182, a1=358)
    far = smooth([(-6, 176), (60, 140), (130, 168), (200, 128), (280, 166),
                  (W + 6, 140)], 8)
    fill(c, far + [(W + 6, 176), (-6, 176)], INK)
    engrave_ridge(c, far, 176, n=4, gap=8, inset=6, w=1.0, fade=0.28)
    for (px, py) in [(200, 128), (60, 140)]:   # snow on the two high peaks
        fill(c, [(px, py + 2), (px - 8, py + 16), (px - 2, py + 13),
                 (px + 2, py + 17), (px + 7, py + 13)], PAPER)
    # meadow line
    line(c, (0, 200), (W, 196), 1.0)
    # winding path (paper) with bold ruled edges + stepping-stone rungs so it
    # reads clearly as a trail climbing toward the peak
    path = [(168, H), (188, 252), (194, 216), (200, 198)]
    pathR = [(232, H), (212, 252), (206, 216), (200, 198)]
    fill(c, [(168, H)] + smooth(path[1:], 8)[::-1] + smooth(pathR[1:], 8) + [(232, H)],
         PAPER)
    stroke(c, path, 1.7)
    stroke(c, pathR, 1.7)
    for i in range(6):
        t = i / 6
        y = 300 - 100 * t
        hw = 30 * (1 - t) + 3
        line(c, (200 - hw, y), (200 + hw, y), 0.9)
    # flanking trees, kept a little lighter so the scene doesn't go bottom-heavy
    tree_round(c, 44, 300, 78)
    pine(c, 92, 300, 56)
    tree_round(c, 360, 300, 70)
    pine(c, 312, 300, 50)
    return (44, 26, 312, 100), []


def sc_open_book(c):
    # an open Bible with quiet rays rising off the page — text canvas up top
    sun_rays(c, 200, 250, 20, 78, n=13, a0=206, a1=334, w=1.0)
    hill_outline(c, 272, 10, 1.4, seed_extra=11)
    open_book(c, 200, 236, 180)
    for (x, y) in [(150, 178), (250, 172), (200, 186)]:   # sparkles above the page
        line(c, (x - 3, y), (x + 3, y), 0.9)
        line(c, (x, y - 3), (x, y + 3), 0.9)
    return (34, 24, 332, 142), []


def sc_sailboat_dawn(c):
    # a little sailboat on a calm sea, sun low at the horizon — text canvas up top
    sun_lined(c, 348, 206, 17, rays=14, r1=42, w=1.2, a0=196, a1=344)
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
    zone = (20, 24, 324, 194)
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
    # a large low moon over layered hills — white ink text
    zone = (26, 30, 282, 152)
    stars(c, 44, zone=zone, y1=150, vmin=210)
    disc(c, 352, 150, 40, 255)          # big low moon, clear of the text canvas
    # a couple of soft craters carved back to sky
    for (mx, my, mr) in [(344, 142, 5), (362, 156, 4), (350, 166, 3)]:
        disc(c, mx, my, mr, INK)
    # layered hills as filled black shapes with a bright white crest line
    for by, amp, s in [(198, 16, 21), (228, 20, 22), (262, 26, 23)]:
        r = ridge_pts(c, by, amp, seed_extra=s)
        stroke(c, r, 1.4, 255)
    tree_round(c, 70, 300, 70, val=255)
    pine(c, 350, 300, 64, val=255)
    return zone, ["night", "wink"]


SCENES = [
    ("note-flourish", sc_note_flourish),
    ("celebration", sc_celebration),
    ("golgotha-dawn", sc_golgotha_dawn),
    ("shepherd", sc_shepherd),
    ("lighthouse", sc_lighthouse),
    ("still-waters", sc_still_waters),
    ("empty-tomb", sc_empty_tomb),
    ("botanical-frame", sc_botanical_frame),
    ("dove-descending", sc_dove_descending),
    ("wheat-field", sc_wheat_field),
    ("mountain-path", sc_mountain_path),
    ("open-book", sc_open_book),
    ("sailboat-dawn", sc_sailboat_dawn),
    ("starry-night", sc_starry_night),
    ("moonlit-hills", sc_moonlit_hills),
]


# ---------------------------------------------------------------- export
NIGHT_SCENES = {"starry-night", "moonlit-hills"}


def export(idx, name, fn):
    c = C(name, bg=INK if name in NIGHT_SCENES else PAPER)
    zone, tags = fn(c)
    white_ink = "wink" in tags
    tags = [t for t in tags if t != "wink"]
    small = c.img.resize((W, H), Image.BILINEAR)
    bw = small.convert("1", dither=Image.Dither.NONE)   # threshold, no dither
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
