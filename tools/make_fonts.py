#!/usr/bin/env python3
"""
make_fonts.py — GraceFrame font pipeline
========================================
Downloads three Google Fonts and converts them into Adafruit-GFX font
headers for the firmware:

  ScriptLg / ScriptMd / ScriptSm   Dancing Script Bold (the verse script)
  SerifIt  / SerifRefIt            Literata Italic (long verses + reference)
  SansBold / SansMed / SansSmall   Poppins (Spotify screen)

Font choices are driven by how they survive a 1-bit threshold at panel size:
Dancing Script at weight 700 keeps its hairline connectors solid, and Literata
(an e-reader serif with an optical-size axis) stays fully formed at 19px where
EB Garamond's delicate italic broke apart.  Each font gets its own threshold —
smaller sizes cut at a lower value so strokes stay full instead of ragged.

All fonts cover chars 32..255 (Latin-1) so accented titles render correctly.
A self-test image is written to previews/font_test.png that is rendered FROM
the packed GFX data — if that image looks right, the ESP32 will too.

Run:  python make_fonts.py
"""

import os
import sys
import urllib.request

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "Spotify_Frame")
CACHE = os.path.join(HERE, "fonts_cache")
PREV = os.path.join(HERE, "previews")

GH = "https://github.com/google/fonts/raw/main/ofl"
SOURCES = {
    "DancingScript.ttf": [f"{GH}/dancingscript/DancingScript%5Bwght%5D.ttf"],
    "LiterataItalic.ttf": [f"{GH}/literata/Literata-Italic%5Bopsz%2Cwght%5D.ttf"],
    "PoppinsSemiBold.ttf": [f"{GH}/poppins/Poppins-SemiBold.ttf"],
    "PoppinsMedium.ttf": [f"{GH}/poppins/Poppins-Medium.ttf"],
    "PoppinsRegular.ttf": [f"{GH}/poppins/Poppins-Regular.ttf"],
}

# (c_name, ttf, variable_axes_or_None, pixel_size, threshold, yadv_override)
# axes: single number = wght; tuple = the font's axis order (Literata: opsz,wght)
# yadv_override bakes a tighter line step than the airy TTF metrics — firmware
# and preview both read yAdvance from the struct, so layout stays in sync and
# long verses gain a line of capacity in the same zones.
FONTS = [
    ("ScriptLg", "DancingScript.ttf", 700, 34, 112, 40),
    ("ScriptMd", "DancingScript.ttf", 700, 28, 106, 33),
    ("ScriptSm", "DancingScript.ttf", 700, 23, 100, 28),
    ("SerifIt", "LiterataItalic.ttf", (8, 600), 18, 108, 25),
    ("SerifRefIt", "LiterataItalic.ttf", (8, 600), 16, 110, 22),
    ("SansBold", "PoppinsSemiBold.ttf", None, 21, 124, None),
    ("SansMed", "PoppinsMedium.ttf", None, 16, 124, None),
    ("SansSmall", "PoppinsRegular.ttf", None, 12, 118, None),
]

FIRST, LAST = 32, 255
SS = 4            # supersample factor: render glyphs big, area-average down, then
                  # threshold — kills the jagged/broken strokes of a direct 1-bit cut


def download(name, urls):
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return path
    last_err = None
    for url in urls:
        try:
            print(f"  downloading {name}")
            req = urllib.request.Request(url, headers={"User-Agent": "GraceFrame"})
            with urllib.request.urlopen(req, timeout=40) as r, open(path, "wb") as f:
                f.write(r.read())
            return path
        except Exception as e:
            last_err = e
    raise RuntimeError(f"could not download {name}: {last_err}")


def load_font(ttf, weight, px):
    font = ImageFont.truetype(os.path.join(CACHE, ttf), px)
    if weight is not None:
        axes = list(weight) if isinstance(weight, (tuple, list)) else [weight]
        try:
            font.set_variation_by_axes(axes)
        except Exception:
            print(f"    (no variable axes in {ttf}; using default weight)")
    return font


def build_font(cname, ttf, weight, px, threshold, yadv_override=None):
    font = load_font(ttf, weight, px)          # target-size metrics (advance/bbox)
    bigfont = load_font(ttf, weight, px * SS)  # oversized, for smooth rasterizing
    ascent, descent = font.getmetrics()
    bitmaps = bytearray()
    glyphs = []           # (offset, w, h, xAdv, xOff, yOff)

    for code in range(FIRST, LAST + 1):
        ch = chr(code)
        printable = not (0x7F <= code <= 0xA0)
        if printable:
            try:
                x0, y0, x1, y1 = font.getbbox(ch)
            except Exception:
                printable = False
        if not printable or x1 <= x0 or y1 <= y0:
            adv = int(round(font.getlength(" "))) if code in (32, 160) else 0
            glyphs.append((len(bitmaps), 0, 0, adv, 0, 0))
            continue

        # Render the glyph SS× oversized, then LANCZOS-downsample to target size so
        # the 1-bit threshold cuts a smooth grey ramp (clean curves) instead of
        # FreeType's jagged small-size hinting. Advance width is unchanged, so line
        # wrapping / fit is identical to before.
        bx0, by0, bx1, by1 = bigfont.getbbox(ch)
        big = Image.new("L", (bx1 - bx0, by1 - by0), 0)
        ImageDraw.Draw(big).text((-bx0, -by0), ch, font=bigfont, fill=255)
        w, h = max(1, round((bx1 - bx0) / SS)), max(1, round((by1 - by0) / SS))
        img = big.resize((w, h), Image.LANCZOS)
        x0, y0 = round(bx0 / SS), round(by0 / SS)
        px_data = img.load()
        bits = []
        for yy in range(h):
            for xx in range(w):
                bits.append(1 if px_data[xx, yy] >= threshold else 0)
        # pack bits MSB-first, continuous across rows (GFX format)
        offset = len(bitmaps)
        acc = 0
        nbits = 0
        for b in bits:
            acc = (acc << 1) | b
            nbits += 1
            if nbits == 8:
                bitmaps.append(acc)
                acc = nbits = 0
        if nbits:
            bitmaps.append(acc << (8 - nbits))
        adv = int(round(font.getlength(ch)))
        if adv <= 0:
            adv = w + 1
        # clamp to int8 ranges used by GFXglyph
        x_off = max(-128, min(127, x0))
        y_off = max(-128, min(127, y0 - ascent))
        glyphs.append((offset, w, h, adv, x_off, y_off))

    y_advance = yadv_override if yadv_override else ascent + descent + 1
    return bitmaps, glyphs, y_advance, ascent


def write_header(cname, bitmaps, glyphs, y_advance):
    lines = [
        "// Auto-generated by tools/make_fonts.py - do not edit by hand.",
        "#pragma once",
        "#include <Adafruit_GFX.h>",
        "",
        f"const uint8_t {cname}Bitmaps[] PROGMEM = {{",
    ]
    for i in range(0, len(bitmaps), 16):
        chunk = ", ".join(f"0x{b:02X}" for b in bitmaps[i:i + 16])
        lines.append(f"  {chunk},")
    lines.append("};")
    lines.append("")
    lines.append(f"const GFXglyph {cname}Glyphs[] PROGMEM = {{")
    for i, (off, w, h, adv, xo, yo) in enumerate(glyphs):
        code = FIRST + i
        ch = chr(code)
        cmt = ch if code < 127 and ch.isprintable() and ch != "\\" else "?"
        lines.append(f"  {{ {off}, {w}, {h}, {adv}, {xo}, {yo} }}, // 0x{FIRST + i:02X} {cmt}")
    lines.append("};")
    lines.append("")
    lines.append(
        f"const GFXfont {cname} PROGMEM = {{ (uint8_t*){cname}Bitmaps, "
        f"(GFXglyph*){cname}Glyphs, 0x{FIRST:02X}, 0x{LAST:02X}, {y_advance} }};")
    path = os.path.join(OUT_DIR, f"font_{cname}.h")
    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")
    return path


def render_sample(draw, bitmaps, glyphs, ascent, x, y, text):
    """draw text from the PACKED data — validates the GFX packing"""
    pen = x
    for ch in text:
        code = ord(ch)
        if not (FIRST <= code <= LAST):
            continue
        off, w, h, adv, xo, yo = glyphs[code - FIRST]
        bit_index = 0
        for yy in range(h):
            for xx in range(w):
                byte = bitmaps[off + (bit_index >> 3)]
                if byte & (0x80 >> (bit_index & 7)):
                    draw.point((pen + xo + xx, y + ascent + yo + yy), fill=0)
                bit_index += 1
        pen += adv
    return pen


def main():
    os.makedirs(PREV, exist_ok=True)
    for name, urls in SOURCES.items():
        download(name, urls)

    built = {}
    total = 0
    for cname, ttf, weight, px, threshold, yadv in FONTS:
        bitmaps, glyphs, y_adv, ascent = build_font(cname, ttf, weight, px,
                                                    threshold, yadv)
        path = write_header(cname, bitmaps, glyphs, y_adv)
        built[cname] = (bitmaps, glyphs, ascent)
        total += len(bitmaps)
        print(f"  {cname:10s} {px}px  {len(bitmaps):6d} bytes  -> {os.path.basename(path)}")

    # self-test sheet rendered from packed data
    img = Image.new("L", (760, 420), 255)
    d = ImageDraw.Draw(img)
    y = 8
    samples = [
        ("ScriptLg", "For God so loved the world"),
        ("ScriptMd", "Be still, and know that I am God"),
        ("ScriptSm", "The Lord is my shepherd; Amazing Grace"),
        ("SerifIt", "I can do all this through him — Philippians 4:13"),
        ("SerifRefIt", "— Jeremiah 29:11 · Psalm 23:1-3"),
        ("SansBold", "Despacito — Beyonce God's Plan"),
        ("SansMed", "Luis Fonsi, Daddy Yankee feat. Bieber"),
        ("SansSmall", "1:08 / 3:49  NOW PLAYING  0123456789"),
    ]
    for cname, text in samples:
        bitmaps, glyphs, ascent = built[cname]
        render_sample(d, bitmaps, glyphs, ascent, 10, y, text)
        y += ascent + 22
    img.save(os.path.join(PREV, "font_test.png"))
    print(f"\ntotal font flash: {total} bytes")
    print(f"self-test -> {os.path.join(PREV, 'font_test.png')}")


if __name__ == "__main__":
    main()
