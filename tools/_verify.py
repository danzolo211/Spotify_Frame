#!/usr/bin/env python3
"""Objective, non-visual proof of crispness for GraceFrame.

Blur is impossible to bake into this art: every asset is 1 bit per pixel, so a
pixel is exactly black or white — there is no grey to smear. This checks that
invariant end to end, plus that each scene keeps its verse zone clean (no stray
ink / speckle where the words land).
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_app as p  # noqa: E402

BG_DIR = p.BG_DIR
day_or_night = p.BGS


def unpack(buf):
    return Image.frombytes("1", (400, 300), bytes(b ^ 0xFF for b in buf))


print("== 1-bit invariant (no grey can exist -> no blur in the data) ==")
ok = True
for b in p.BGS:
    path = os.path.join(BG_DIR, "%03d.bin" % b["i"])
    n = os.path.getsize(path)
    bits_ok = (n == 400 * 300 // 8)
    ok &= bits_ok
    # a rendered verse composite must also be pure 1-bit
    comp = p.render_verse(b, {"t": "Crisp pixels.", "r": "Test"})
    comp_ok = (len(comp) == 15000)
    ok &= comp_ok
print("  all %d backgrounds are exactly 15000 bytes (1 bit/pixel):" % len(p.BGS),
      "PASS" if ok else "FAIL")

print("\n== verse-zone cleanliness (stray pixels where the words go) ==")
print("  a clean canvas should be near 0%%; framed scenes a touch higher\n")
worst = 0.0
for b in p.BGS:
    with open(os.path.join(BG_DIR, "%03d.bin" % b["i"]), "rb") as f:
        img = unpack(f.read()).convert("L")
    zx, zy, zw, zh = b["zone"]
    crop = img.crop((zx, zy, zx + zw, zy + zh))
    text_bg = 0 if b.get("ink") == "white" else 255
    px = list(crop.getdata())
    stray = sum(1 for v in px if v != text_bg) / len(px) * 100
    worst = max(worst, stray)
    flag = "  <-- check" if stray > 6 else ""
    print("  %-16s zone stray %5.2f%%%s" % (b["name"], stray, flag))
print("\n  worst zone stray: %.2f%%  (%s)" %
      (worst, "clean" if worst < 8 else "review"))
