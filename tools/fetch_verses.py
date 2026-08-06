#!/usr/bin/env python3
"""
fetch_verses.py — GraceFrame verse library builder
==================================================
Downloads the NIV text for a hand-curated shortlist of the most loved,
most encouraging verses in Scripture (from bolls.life — free, no API key)
and packs them for the ESP32.

This is a *curated* library, not a firehose: ~120 of the best-known verses
on hope, peace, strength, joy, wisdom, comfort, and God's faithfulness.
Obscure censuses, genealogies and ceremonial passages are deliberately left
out so every verse that lands on the frame is one worth reading twice.

A verse spec may be a single verse ("16") or a small range ("5-6"); a range
is stitched into ONE entry with a range reference (e.g. "Proverbs 3:5-6"),
so famous couplets stay whole instead of being split mid-thought.

Outputs:
  GraceFrame/data/verses.jsonl   one JSON object per line:
                                 {"r":"John 3:16","t":"For God so...","c":"love"}
  GraceFrame/data/verses.idx     binary: uint32 count, then uint32 byte-offset
                                 of each line (little-endian) — lets the ESP32
                                 seek straight to verse N
  GraceFrame/data/verses_meta.json

Chapters are cached in tools/verse_cache/ so re-runs are instant.

Run:  python fetch_verses.py            (NIV, default)
      python fetch_verses.py --translation KJV
"""

import argparse
import json
import os
import re
import struct
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "GraceFrame", "data")
CACHE = os.path.join(HERE, "verse_cache")

MAX_LEN = 290          # verses longer than this can't render beautifully
THROTTLE_S = 0.65      # be polite to bolls.life

# A few beloved passages are too long to render beautifully in full on the
# 400x300 1-bit panel (they'd fall back to tiny serif or truncate). Replace them
# with tighter exact-NIV excerpts, keyed by the generated reference. Applied
# after fetch+clean so the rest of the pipeline is unchanged.
OVERRIDES = {
    "Isaiah 43:2": "When you pass through the waters, I will be with you; and "
                   "when you pass through the rivers, they will not sweep over you.",
    "Philippians 4:8": "Whatever is true, whatever is noble, whatever is right, "
                       "whatever is pure - think about such things.",
    "Romans 8:38-39": "Neither death nor life, nor anything else in all creation, "
                      "will be able to separate us from the love of God that is in "
                      "Christ Jesus our Lord.",
    "Psalm 23:1-3": "The Lord is my shepherd, I shall not be in want. He makes "
                    "me lie down in green pastures, he leads me beside quiet "
                    "waters, he restores my soul.",
    "Psalm 100:4-5": "Enter his gates with thanksgiving and his courts with "
                     "praise; give thanks to him and praise his name. For the "
                     "Lord is good and his love endures forever.",
    "Romans 12:2": "Do not conform any longer to the pattern of this world, "
                   "but be transformed by the renewing of your mind.",
    "2 Corinthians 12:9": "My grace is sufficient for you, for my power is "
                          "made perfect in weakness.",
    "Nehemiah 8:10": "Do not grieve, for the joy of the Lord is your strength.",
}

BOOK_IDS = {
    "Genesis": 1, "Exodus": 2, "Leviticus": 3, "Numbers": 4, "Deuteronomy": 5,
    "Joshua": 6, "Judges": 7, "Ruth": 8, "1 Samuel": 9, "2 Samuel": 10,
    "1 Kings": 11, "2 Kings": 12, "1 Chronicles": 13, "2 Chronicles": 14,
    "Ezra": 15, "Nehemiah": 16, "Esther": 17, "Job": 18, "Psalm": 19,
    "Proverbs": 20, "Ecclesiastes": 21, "Song of Songs": 22, "Isaiah": 23,
    "Jeremiah": 24, "Lamentations": 25, "Ezekiel": 26, "Daniel": 27,
    "Hosea": 28, "Joel": 29, "Amos": 30, "Obadiah": 31, "Jonah": 32,
    "Micah": 33, "Nahum": 34, "Habakkuk": 35, "Zephaniah": 36, "Haggai": 37,
    "Zechariah": 38, "Malachi": 39, "Matthew": 40, "Mark": 41, "Luke": 42,
    "John": 43, "Acts": 44, "Romans": 45, "1 Corinthians": 46,
    "2 Corinthians": 47, "Galatians": 48, "Ephesians": 49, "Philippians": 50,
    "Colossians": 51, "1 Thessalonians": 52, "2 Thessalonians": 53,
    "1 Timothy": 54, "2 Timothy": 55, "Titus": 56, "Philemon": 57,
    "Hebrews": 58, "James": 59, "1 Peter": 60, "2 Peter": 61, "1 John": 62,
    "2 John": 63, "3 John": 64, "Jude": 65, "Revelation": 66,
}

# ------------------------------------------------------------------
# The curated library: (book, chapter, "verse spec", category)
#   spec "16"   -> single verse                 -> "Book 3:16"
#   spec "5-6"  -> range, stitched into one     -> "Book 3:5-6"
# Categories: love hope faith peace strength comfort joy wisdom praise
#             promise salvation prayer guidance courage
# ------------------------------------------------------------------
REFS = [
    # --- opening & blessing ---
    ("Genesis", 1, "1", "praise"),
    ("Numbers", 6, "24-26", "promise"),
    ("Deuteronomy", 31, "6", "courage"),
    ("Joshua", 1, "9", "courage"),

    # --- Psalms ---
    ("Psalm", 16, "11", "joy"),
    ("Psalm", 18, "2", "strength"),
    ("Psalm", 19, "1", "praise"),
    ("Psalm", 19, "14", "prayer"),
    ("Psalm", 23, "1-3", "comfort"),
    ("Psalm", 23, "4", "comfort"),
    ("Psalm", 27, "1", "courage"),
    ("Psalm", 28, "7", "strength"),
    ("Psalm", 29, "11", "peace"),
    ("Psalm", 30, "5", "joy"),
    ("Psalm", 32, "8", "guidance"),
    ("Psalm", 34, "4", "courage"),
    ("Psalm", 34, "8", "faith"),
    ("Psalm", 34, "18", "comfort"),
    ("Psalm", 37, "4", "promise"),
    ("Psalm", 37, "5-6", "guidance"),
    ("Psalm", 42, "11", "hope"),
    ("Psalm", 46, "1", "strength"),
    ("Psalm", 46, "10", "peace"),
    ("Psalm", 51, "10", "prayer"),
    ("Psalm", 55, "22", "comfort"),
    ("Psalm", 62, "1", "peace"),
    ("Psalm", 73, "26", "strength"),
    ("Psalm", 91, "1-2", "strength"),
    ("Psalm", 91, "4", "comfort"),
    ("Psalm", 94, "19", "comfort"),
    ("Psalm", 100, "4-5", "praise"),
    ("Psalm", 103, "1", "praise"),
    ("Psalm", 103, "8", "love"),
    ("Psalm", 118, "24", "joy"),
    ("Psalm", 119, "105", "wisdom"),
    ("Psalm", 121, "1-2", "strength"),
    ("Psalm", 126, "5", "hope"),
    ("Psalm", 136, "1", "praise"),
    ("Psalm", 139, "14", "praise"),
    ("Psalm", 139, "23-24", "prayer"),
    ("Psalm", 143, "8", "guidance"),
    ("Psalm", 145, "18", "prayer"),
    ("Psalm", 147, "3", "comfort"),

    # --- Proverbs & Ecclesiastes ---
    ("Proverbs", 3, "5-6", "wisdom"),
    ("Proverbs", 4, "23", "wisdom"),
    ("Proverbs", 16, "3", "guidance"),
    ("Proverbs", 16, "9", "guidance"),
    ("Proverbs", 17, "22", "joy"),
    ("Proverbs", 18, "10", "strength"),
    ("Proverbs", 31, "25", "courage"),
    ("Ecclesiastes", 3, "1", "wisdom"),
    ("Ecclesiastes", 4, "9-10", "love"),

    # --- Isaiah, Jeremiah, Lamentations & the Prophets ---
    ("Isaiah", 12, "2", "joy"),
    ("Isaiah", 26, "3", "peace"),
    ("Isaiah", 30, "15", "peace"),
    ("Isaiah", 40, "8", "promise"),
    ("Isaiah", 40, "29", "strength"),
    ("Isaiah", 40, "31", "strength"),
    ("Isaiah", 41, "10", "courage"),
    ("Isaiah", 41, "13", "courage"),
    ("Isaiah", 43, "1", "promise"),
    ("Isaiah", 43, "2", "comfort"),
    ("Isaiah", 43, "19", "promise"),
    ("Jeremiah", 17, "7", "faith"),
    ("Jeremiah", 29, "11", "hope"),
    ("Jeremiah", 33, "3", "prayer"),
    ("Lamentations", 3, "22-23", "hope"),
    ("Micah", 6, "8", "guidance"),
    ("Zephaniah", 3, "17", "love"),

    # --- the Gospels ---
    ("Matthew", 5, "16", "wisdom"),
    ("Matthew", 6, "33", "faith"),
    ("Matthew", 6, "34", "peace"),
    ("Matthew", 7, "7", "prayer"),
    ("Matthew", 5, "4", "comfort"),
    ("Matthew", 11, "28", "comfort"),   # v28 alone (v28-30 too long for the panel)
    ("Matthew", 19, "26", "faith"),
    ("Mark", 11, "24", "prayer"),
    ("Luke", 1, "37", "faith"),
    ("John", 3, "16", "love"),
    ("John", 8, "12", "hope"),
    ("John", 10, "10", "hope"),
    ("John", 13, "34", "love"),
    ("John", 14, "1", "peace"),
    ("John", 14, "6", "salvation"),
    ("John", 14, "27", "peace"),
    ("John", 15, "5", "faith"),
    ("John", 16, "33", "courage"),
    ("Acts", 16, "31", "salvation"),

    # --- Paul's letters ---
    ("Romans", 5, "8", "love"),
    ("Romans", 8, "28", "hope"),
    ("Romans", 8, "31", "courage"),
    ("Romans", 8, "38-39", "love"),
    ("Romans", 6, "23", "salvation"),
    ("Romans", 10, "9", "salvation"),
    ("Romans", 12, "2", "guidance"),
    ("Romans", 12, "12", "hope"),
    ("Romans", 15, "13", "hope"),
    ("1 Corinthians", 13, "4", "love"),   # v4 alone (v4-6 too long for the panel)
    ("1 Corinthians", 13, "13", "love"),
    ("1 Corinthians", 16, "14", "love"),
    ("2 Corinthians", 5, "7", "faith"),
    ("2 Corinthians", 12, "9", "strength"),
    ("Galatians", 5, "22-23", "love"),
    ("Ephesians", 2, "8", "salvation"),
    ("Ephesians", 3, "20", "praise"),
    ("Philippians", 1, "6", "hope"),
    ("Philippians", 4, "4", "joy"),
    ("Philippians", 4, "6", "prayer"),
    ("Philippians", 4, "7", "peace"),   # v7 alone (v6-7 too long for the panel)
    ("Philippians", 4, "8", "wisdom"),
    ("Philippians", 4, "13", "strength"),
    ("Philippians", 4, "19", "promise"),
    ("Colossians", 3, "15", "peace"),
    ("Colossians", 3, "23", "wisdom"),
    ("1 Thessalonians", 5, "16-18", "joy"),

    # --- the general letters & Revelation ---
    ("2 Timothy", 1, "7", "courage"),
    ("Titus", 3, "5", "salvation"),
    ("Hebrews", 11, "1", "faith"),
    ("Hebrews", 13, "5", "promise"),
    ("Hebrews", 13, "8", "faith"),
    ("James", 1, "2-3", "wisdom"),
    ("James", 1, "5", "wisdom"),
    ("James", 1, "17", "promise"),
    ("1 Peter", 5, "7", "comfort"),
    ("1 John", 4, "7", "love"),
    ("1 John", 4, "18", "love"),
    ("1 John", 4, "19", "love"),
    ("Revelation", 21, "4", "hope"),
    ("Nehemiah", 8, "10", "joy"),
]

UNICODE_MAP = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": " - ", "…": "...", " ": " ",
    "‑": "-", "′": "'", "א": "", "​": "",
}

# little words that stay lowercase inside a Title-Case heading
_MINOR = {"a", "an", "the", "of", "and", "or", "nor", "but", "for", "to",
          "in", "on", "at", "by", "with", "from", "as", "into", "over", "upon"}


SUPERSCRIPTS = (
    "a psalm", "a song", "a maskil", "a miktam", "a prayer", "a shiggaion",
    "of david", "of solomon", "of asaph", "of the sons", "of moses",
    "for the director", "to the tune", "when he ", "when the ",
)


def _is_heading(seg):
    """chapter headings / psalm superscriptions bolls embeds before the text.

    The tricky part: bolls uses <br/> for poetic line breaks *inside* a verse
    too, so we must tell a real section heading ("More Than Conquerors",
    "Jesus Comforts His Disciples") from a poetic opening line ("The Lord bless
    you", "Enter his gates with thanksgiving").  The reliable signal is case:
    NIV section headings are Title Case (every word capitalized); scripture
    lines are sentence case (they contain lowercase words like "bless you").
    """
    if not seg:
        return True
    if re.fullmatch(r"(BOOK\s+[IVXLC]+.*|Psalm\s+\d+)", seg, re.I):
        return True
    low = seg.lower()
    if any(low.startswith(p) for p in SUPERSCRIPTS) and len(seg) <= 90:
        return True
    # a short line with no ending punctuation whose every significant word is
    # capitalized = a Title-Case section heading (never a verse line).  Minor
    # words ("A Time *for* Everything") may stay lowercase; a real verse line
    # ("Enter *his gates with thanksgiving*") always has lowercase content words.
    words = re.findall(r"[A-Za-z'’‘]+", seg)   # keep "Israel's" whole
    if (words and len(seg) <= 50 and len(words) <= 7
            and words[0][0].isupper()
            and not re.search(r"[.,;:!?'\"-]$", seg)
            and all(w[0].isupper() or w.lower() in _MINOR for w in words)):
        return True
    return False


def clean(text):
    segs = re.split(r"<br\s*/?>", text)
    while len(segs) > 1:
        s0 = re.sub(r"<[^>]+>", " ", segs[0]).strip()
        if _is_heading(s0):
            segs.pop(0)
        else:
            break
    text = " ".join(segs)
    text = re.sub(r"<[^>]+>", " ", text)                 # html tags
    text = re.sub(r"\[[a-z0-9]{1,3}\]", "", text)        # footnote markers
    for k, v in UNICODE_MAP.items():
        text = text.replace(k, v)
    # anything else non-latin1 -> drop
    text = text.encode("latin-1", "ignore").decode("latin-1")
    text = re.sub(r"\s+", " ", text).strip()
    # Drop any outer layer of quotation marks. The frame wraps every verse in
    # one clean pair itself (ADD_QUOTES), so leading/trailing quotes only cause
    # doubles or nested-quote clutter — e.g. the priestly blessing arrives as
    #   "'"The Lord bless you ... give you peace.'"
    # We want the words, cleanly, and let the frame add the quotes.
    text = re.sub(r'^[\s"\']+', "", text)
    text = re.sub(r'[\s"\']+$', "", text)
    # a quotation that spans verses can still leave an unbalanced mark inside
    while text.count('"') % 2 == 1:
        text = text[::-1].replace('"', "", 1)[::-1]
    text = text.strip()
    # a verse clipped before the next one often ends on a connector (",", ":",
    # ";", "-"); close the thought with a period so it stands on its own
    text = re.sub(r"[\s,;:\-]+$", ".", text)
    # capitalize the opening letter so half-sentence verses (Isaiah 40:31's
    # "but those who hope...") still read cleanly on their own
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def parse_spec(spec):
    """return (list_of_verse_numbers, is_range)"""
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-")
        return list(range(int(a), int(b) + 1)), True
    return [int(spec)], False


def fetch_chapter(translation, book_id, chapter):
    os.makedirs(CACHE, exist_ok=True)
    cpath = os.path.join(CACHE, f"{translation}_{book_id}_{chapter}.json")
    if os.path.exists(cpath):
        with open(cpath, encoding="utf-8") as f:
            return json.load(f)
    url = f"https://bolls.life/get-text/{translation}/{book_id}/{chapter}/"
    req = urllib.request.Request(url, headers={"User-Agent": "GraceFrame/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                data = json.loads(r.read().decode("utf-8"))
            with open(cpath, "w", encoding="utf-8") as f:
                json.dump(data, f)
            time.sleep(THROTTLE_S)
            return data
        except Exception as e:
            wait = 3 * (attempt + 1)
            print(f"    retry {attempt + 1} ({e}) in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"could not fetch {url}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--translation", default="NIV",
                    help="bolls.life translation code (NIV, KJV, ESV, NKJV...)")
    args = ap.parse_args()
    tr = args.translation.upper()

    os.makedirs(OUT_DIR, exist_ok=True)
    verses, seen = [], set()
    skipped_long = skipped_missing = 0
    chapters = {}
    total_chapters = len({(b, ch) for b, ch, _, _ in REFS})
    done = 0

    for book, chapter, spec, cat in REFS:
        key = (book, chapter)
        if key not in chapters:
            done += 1
            print(f"[{done}/{total_chapters}] {book} {chapter}")
            chapters[key] = {v["verse"]: v["text"]
                             for v in fetch_chapter(tr, BOOK_IDS[book], chapter)}
        chap = chapters[key]

        nums, is_range = parse_spec(spec)
        ref = f"{book} {chapter}:{spec}" if is_range \
            else f"{book} {chapter}:{nums[0]}"
        if ref in seen:
            continue
        seen.add(ref)

        raws = [chap.get(n) for n in nums]
        if any(r is None for r in raws):
            skipped_missing += 1
            print(f"    !! missing {ref}")
            continue
        # stitch the range together, then clean once so a quotation that
        # opens in one verse and closes in the next stays balanced
        text = OVERRIDES.get(ref) or clean(" ".join(raws))
        if len(text) > MAX_LEN:
            skipped_long += 1
            print(f"    .. too long ({len(text)}) {ref}")
            continue
        if len(text) < 12:
            skipped_missing += 1
            continue
        verses.append({"r": ref, "t": text, "c": cat})

    # write jsonl + offset index
    jsonl_path = os.path.join(OUT_DIR, "verses.jsonl")
    idx_path = os.path.join(OUT_DIR, "verses.idx")
    offsets = []
    with open(jsonl_path, "wb") as f:
        for v in verses:
            offsets.append(f.tell())
            f.write(json.dumps(v, ensure_ascii=True,
                               separators=(",", ":")).encode("ascii"))
            f.write(b"\n")
    with open(idx_path, "wb") as f:
        f.write(struct.pack("<I", len(offsets)))
        for off in offsets:
            f.write(struct.pack("<I", off))
    cats = sorted({v["c"] for v in verses})
    with open(os.path.join(OUT_DIR, "verses_meta.json"), "w") as f:
        json.dump({"count": len(verses), "translation": tr,
                   "categories": cats}, f)

    # a little category tally so it's easy to see the balance
    tally = {}
    for v in verses:
        tally[v["c"]] = tally.get(v["c"], 0) + 1
    print(f"\n{len(verses)} verses written ({tr})")
    print(f"   skipped {skipped_long} too-long, {skipped_missing} missing")
    print("   by theme: " + ", ".join(f"{k} {tally[k]}" for k in sorted(tally)))
    print(f"   -> {jsonl_path}")
    print(f"   -> {idx_path}")


if __name__ == "__main__":
    main()
