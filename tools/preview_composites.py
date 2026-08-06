#!/usr/bin/env python3
"""Render scenes the way she'll actually see them — verse text composited onto
each background through the live pipeline. Writes tools/previews/_composed.png.
Run: python tools/preview_composites.py"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_app as p   # noqa: E402


def unpack(buf):
    return Image.frombytes("1", (400, 300),
                           bytes(b ^ 0xFF for b in buf)).convert("L")


SAMPLES = [
    ("golgotha-dawn", "He was pierced for our transgressions, he was crushed "
     "for our iniquities.", "Isaiah 53:5"),
    ("empty-tomb", "He is not here; he has risen, just as he said.",
     "Matthew 28:6"),
    ("shepherd", "The Lord is my shepherd, I lack nothing.", "Psalm 23:1"),
    ("still-waters", "He leads me beside quiet waters, he refreshes my soul.",
     "Psalm 23:2-3"),
    ("dove-descending", "The Spirit of God was hovering over the waters.",
     "Genesis 1:2"),
    ("wheat-field", "The harvest is plentiful but the workers are few.",
     "Matthew 9:37"),
    ("lighthouse", "The Lord is my light and my salvation - whom shall I fear?",
     "Psalm 27:1"),
    ("open-book", "Your word is a lamp for my feet, a light on my path.",
     "Psalm 119:105"),
    ("sailboat-dawn", "He got up, rebuked the wind and said, 'Quiet! Be still!'",
     "Mark 4:39"),
    ("mountain-path", "He will make your paths straight.", "Proverbs 3:6"),
    ("starry-night", "He determines the number of the stars and calls them "
     "each by name.", "Psalm 147:4"),
    ("moonlit-hills", "I lift up my eyes to the mountains - where does my help "
     "come from?", "Psalm 121:1"),
]

cols, tw, th = 3, 400, 300
rows = (len(SAMPLES) + cols - 1) // cols
sheet = Image.new("L", (cols * (tw + 6) + 6, rows * (th + 6) + 6), 170)
for i, (name, text, ref) in enumerate(SAMPLES):
    img = unpack(p.render_verse(p.BG_BY_NAME[name], {"t": text, "r": ref}))
    sheet.paste(img, (6 + (i % cols) * (tw + 6), 6 + (i // cols) * (th + 6)))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "previews", "_composed.png")
sheet.save(out)
print("wrote", out)
