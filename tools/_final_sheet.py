#!/usr/bin/env python3
"""Build one complete, device-exact review sheet: all scenes composited with
a representative verse the way Emily will see them, at true 400x300 pixels (no
smoothing). Writes previews/_ALL.png and opens it."""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_app as p  # noqa: E402


def unpack(buf):
    return Image.frombytes("1", (400, 300),
                           bytes(b ^ 0xFF for b in buf)).convert("L")


VERSES = {
    "note-flourish": None,
    "celebration": ("This is the day the Lord has made; let us rejoice and be "
                    "glad in it.", "Psalm 118:24"),
    "golgotha-dawn": ("By his wounds we are healed.", "Isaiah 53:5"),
    "shepherd": ("The Lord is my shepherd, I lack nothing.", "Psalm 23:1"),
    "lighthouse": ("The Lord is my light and my salvation.", "Psalm 27:1"),
    "still-waters": ("He leads me beside quiet waters.", "Psalm 23:2"),
    "empty-tomb": ("He is not here; he has risen, just as he said.",
                   "Matthew 28:6"),
    "botanical-frame": ("The Lord is my rock, my fortress and my deliverer; my "
                        "God is my rock, in whom I take refuge.", "Psalm 18:2"),
    "dove-ascending": ("The Spirit of God was hovering over the waters.",
                       "Genesis 1:2"),
    "mountain-path": ("He will make your paths straight.", "Proverbs 3:6"),
    "open-book": ("Your word is a lamp for my feet, a light on my path.",
                  "Psalm 119:105"),
    "sailboat-dawn": ("He got up, rebuked the wind and said, 'Quiet! Be "
                      "still!'", "Mark 4:39"),
    "starry-night": ("He determines the number of the stars and calls them "
                     "each by name.", "Psalm 147:4"),
    "moonlit-hills": ("I lift up my eyes to the mountains - where does my help "
                      "come from?", "Psalm 121:1"),
    "great-wave": ("When its waves mount up, you still them.", "Psalm 89:9"),
    "fuji-serene": ("Be still, and know that I am God.", "Psalm 46:10"),
    "crane-moon": ("He stilled the storm to a whisper; the waves of the sea "
                   "were hushed.", "Psalm 107:29"),
}
NOTE = {"text": "Thinking of you today. You are so loved, and I am so proud of "
        "the woman you are.", "from": "Daniel", "minutes": 30}

order = ["note-flourish", "celebration", "golgotha-dawn", "shepherd",
         "lighthouse", "still-waters", "empty-tomb", "botanical-frame",
         "dove-ascending", "mountain-path", "open-book",
         "sailboat-dawn", "starry-night", "moonlit-hills", "great-wave",
         "fuji-serene", "crane-moon"]

cols, tw, th, pad, lbl = 3, 400, 300, 8, 20
rows = (len(order) + cols - 1) // cols
sheet = Image.new("L", (cols * (tw + pad) + pad,
                        rows * (th + lbl + pad) + pad), 150)
d = ImageDraw.Draw(sheet)
for i, name in enumerate(order):
    b = p.BG_BY_NAME[name]
    if name == "note-flourish":
        img = unpack(p.render_note(NOTE))
    else:
        t, r = VERSES[name]
        img = unpack(p.render_verse(b, {"t": t, "r": r}))
    x = pad + (i % cols) * (tw + pad)
    y = pad + (i // cols) * (th + lbl + pad)
    d.text((x + 2, y), name, fill=0)
    sheet.paste(img, (x, y + lbl))
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "previews",
                   "_ALL.png")
sheet.save(out)
print("wrote", out, sheet.size)
