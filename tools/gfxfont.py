"""Parse a baked Adafruit-GFX font header (GraceFrame/font_*.h) and measure /
render text exactly as the firmware does, so the preview mirror matches the
physical panel 1:1 (same glyph bitmaps, same advances, same line height).
"""
import os
import re


class GFXFont:
    def __init__(self, path):
        self.name = os.path.splitext(os.path.basename(path))[0].replace("font_", "")
        s = open(path, encoding="utf-8", errors="ignore").read()
        bm = re.search(r"Bitmaps\[\][^=]*=\s*\{(.*?)\};", s, re.S).group(1)
        self.bitmaps = [int(x, 16) for x in re.findall(r"0x[0-9A-Fa-f]{2}", bm)]
        gl = re.search(r"Glyphs\[\][^=]*=\s*\{(.*?)\};", s, re.S).group(1)
        self.glyphs = [tuple(int(n) for n in g) for g in re.findall(
            r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,"
            r"\s*(-?\d+)\s*,\s*(-?\d+)\s*\}", gl)]
        m = re.search(r"GFXfont\s+\w+\s*PROGMEM\s*=\s*\{[^,]*,[^,]*,\s*"
                      r"(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(\d+)", s)
        self.first, self.last = int(m.group(1), 16), int(m.group(2), 16)
        self.yadv = int(m.group(3))

    def _g(self, ch):
        c = ord(ch)
        if not (self.first <= c <= self.last):
            c = ord("?") if self.first <= ord("?") <= self.last else self.first
        return self.glyphs[c - self.first]

    def bounds(self, s, x=0, baseline=0):
        """Adafruit_GFX-style text bounds for one line."""
        minx = miny = 10**9
        maxx = maxy = -10**9
        pen = x
        any_pixel = False
        for ch in s:
            off, w, h, adv, xo, yo = self._g(ch)
            if w and h:
                any_pixel = True
                minx = min(minx, pen + xo)
                miny = min(miny, baseline + yo)
                maxx = max(maxx, pen + xo + w - 1)
                maxy = max(maxy, baseline + yo + h - 1)
            pen += adv
        if not any_pixel:
            return x, baseline, 0, 0
        return minx, miny, maxx - minx + 1, maxy - miny + 1

    def width(self, s):
        return self.bounds(s, 0, 120)[2]

    def draw(self, img, s, x, baseline, ink):
        """Blit `s` with its left edge at x and baseline at `baseline`."""
        px = img.load()
        W, H = img.size
        pen = x
        for ch in s:
            off, w, h, adv, xo, yo = self._g(ch)
            bi = 0
            for yy in range(h):
                Y = baseline + yo + yy
                row_ok = 0 <= Y < H
                for xx in range(w):
                    if self.bitmaps[off + (bi >> 3)] & (0x80 >> (bi & 7)):
                        X = pen + xo + xx
                        if row_ok and 0 <= X < W:
                            px[X, Y] = ink
                    bi += 1
            pen += adv
        return pen - x
