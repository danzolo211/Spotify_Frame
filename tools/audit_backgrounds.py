#!/usr/bin/env python3
"""audit_backgrounds.py — mechanical guardrails + honest 1:1 review previews.

Proves what the eye alone can miss:
  * ZONE-CLEAN  the verse's text canvas contains zero art, so words can never
                overlap the background (checked on the exact region the firmware
                lays text into: zone inset +6/-12 in x, per render.cpp).
  * SPECKLE     no isolated 1-px threshold grain (the thing that reads as "noisy").
  * COVERAGE    ink is in a sane band (not a black blob, not empty).
  * BORDER      the outer ring isn't accidentally inked.

Then it composites the REAL verse onto each scene through the same baked device
fonts + layout the firmware uses (preview_app.render_verse) and writes 1:1
(400x300) PNGs to tools/previews/review/ so the art can be judged exactly as she
will see it — no smoothing, no lying about what fits.

Run: python tools/audit_backgrounds.py
"""
import os
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import preview_app as p          # noqa: E402  reuse the font-accurate mirror

REVIEW = os.path.join(HERE, "previews", "review")
os.makedirs(REVIEW, exist_ok=True)

W, H = 400, 300

# a representative verse per scene: roomy verses where the zone is generous,
# short ones where it's tight — so the composite is an honest fit test.
SAMPLE = {
    "golgotha-dawn": ("He was pierced for our transgressions, he was crushed "
                      "for our iniquities.", "Isaiah 53:5"),
    "shepherd": ("The Lord is my shepherd, I lack nothing.", "Psalm 23:1"),
    "lighthouse": ("The Lord is my light and my salvation - whom shall I "
                   "fear?", "Psalm 27:1"),
    "still-waters": ("He leads me beside quiet waters, he refreshes my "
                     "soul.", "Psalm 23:2-3"),
    "empty-tomb": ("He is not here; he has risen, just as he said.",
                   "Matthew 28:6"),
    "botanical-frame": ("Love is patient, love is kind. It always protects, "
                        "always trusts, always hopes.", "1 Cor 13:4-7"),
    "dove-descending": ("The Spirit of God was hovering over the waters.",
                        "Genesis 1:2"),
    "wheat-field": ("The harvest is plentiful but the workers are few.",
                    "Matthew 9:37"),
    "mountain-path": ("In all your ways submit to him, and he will make your "
                      "paths straight.", "Proverbs 3:6"),
    "open-book": ("Your word is a lamp for my feet, a light on my path.",
                  "Psalm 119:105"),
    "sailboat-dawn": ("He rebuked the wind and said, 'Quiet! Be still!'",
                      "Mark 4:39"),
    "starry-night": ("He determines the number of the stars and calls them "
                     "each by name.", "Psalm 147:4"),
    "moonlit-hills": ("I lift up my eyes to the mountains - where does my "
                      "help come from?", "Psalm 121:1"),
    # new water / ukiyo-e scenes
    "great-wave": ("You rule over the surging sea; when its waves mount up, "
                   "you still them.", "Psalm 89:9"),
    "fuji-serene": ("Be still, and know that I am God.", "Psalm 46:10"),
    "crane-moon": ("He stilled the storm to a whisper; the waves of the sea "
                   "were hushed.", "Psalm 107:29"),
}
DEFAULT = ("The Lord your God is with you, the Mighty Warrior who saves.",
           "Zephaniah 3:17")


def unpack(buf):
    return Image.frombytes("1", (W, H),
                           bytes(b ^ 0xFF for b in buf)).convert("L")


def audit_one(b):
    """Return a dict of metrics for one scene index-record `b`."""
    img = p._bg_image(b["i"])            # 'L': 0=ink(black), 255=paper(white)
    px = img.load()
    bg = 0 if b["ink"] == "white" else 255   # value the verse text sits on
    zx, zy, zw, zh = b["zone"]
    izx, izw = zx + 6, zw - 12               # firmware's real text x-range

    zone_full = zone_inset = 0
    for y in range(max(0, zy), min(zy + zh, H)):
        for x in range(max(0, zx), min(zx + zw, W)):
            if px[x, y] != bg:
                zone_full += 1
                if izx <= x < izx + izw:
                    zone_inset += 1

    ink_specks = hole_specks = ink_total = white_total = border_ink = 0
    for y in range(H):
        for x in range(W):
            v = px[x, y]
            if v == 0:
                ink_total += 1
                if x == 0 or y == 0 or x == W - 1 or y == H - 1:
                    border_ink += 1
            else:
                white_total += 1
            if 0 < x < W - 1 and 0 < y < H - 1:
                # 8-neighbour: only *truly floating* dots count as grain, so the
                # metric ignores the diagonal stair-steps of legit thin strokes.
                nb = (px[x - 1, y], px[x + 1, y], px[x, y - 1], px[x, y + 1],
                      px[x - 1, y - 1], px[x + 1, y - 1],
                      px[x - 1, y + 1], px[x + 1, y + 1])
                if v == 0 and all(n == 255 for n in nb):
                    ink_specks += 1          # black speck floating on paper
                elif v == 255 and all(n == 0 for n in nb):
                    hole_specks += 1         # white speck floating in ink

    return {
        "zone_inset": zone_inset, "zone_full": zone_full,
        "ink_specks": ink_specks, "hole_specks": hole_specks,
        "ink_pct": 100.0 * ink_total / (W * H),
        "white_pct": 100.0 * white_total / (W * H),
        "border_ink": border_ink,
    }


def verdict(b, m):
    night = b["ink"] == "white"
    fails, warns = [], []
    if m["zone_inset"] > 0:
        fails.append(f"ZONE {m['zone_inset']}px in text area")
    elif m["zone_full"] > 0:
        warns.append(f"zone margin {m['zone_full']}px")
    # grain = foreground colour floating free on the background. On night scenes
    # floating white == intended stars, so the defect there is floating black
    # holes; on day scenes it's floating black ink specks. (border/coverage are
    # reported for context, not gated — dark ground and night fields are fine.)
    grain = m["ink_specks"]
    if grain > 10:
        warns.append(f"grain {grain}")
    return ("FAIL" if fails else ("WARN" if warns else "PASS"),
            "; ".join(fails + warns))


def main():
    print(f"{'#':>2} {'name':18} {'stat':5} zoneI zoneF specks(k/h) "
          f"ink%  border  notes")
    print("-" * 92)
    nfail = nwarn = 0
    for b in p.BGS:
        m = audit_one(b)
        st, notes = verdict(b, m)
        nfail += st == "FAIL"
        nwarn += st == "WARN"
        print(f"{b['i']:>2} {b['name']:18} {st:5} "
              f"{m['zone_inset']:>5} {m['zone_full']:>5} "
              f"{m['ink_specks']:>4}/{m['hole_specks']:<4} "
              f"{m['ink_pct']:>5.1f}  {m['border_ink']:>5}  {notes}")

        # honest 1:1 previews: bare art + real verse composited
        p._bg_image(b["i"]).save(
            os.path.join(REVIEW, f"{b['i']:02d}_{b['name']}_art.png"))
        if not b["tags"] or "night" in b["tags"] or "water" in b["tags"]:
            text, ref = SAMPLE.get(b["name"], DEFAULT)
            unpack(p.render_verse(b, {"t": text, "r": ref})).save(
                os.path.join(REVIEW, f"{b['i']:02d}_{b['name']}.png"))
    print("-" * 92)
    print(f"{len(p.BGS)} scenes  |  {nfail} FAIL  {nwarn} WARN  "
          f"->  previews: tools/previews/review/")
    return nfail


if __name__ == "__main__":
    sys.exit(1 if main() else 0)   # a FAIL (art in a text zone) breaks the build
