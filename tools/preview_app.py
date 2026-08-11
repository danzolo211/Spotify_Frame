#!/usr/bin/env python3
"""
preview_app.py — try the GraceFrame phone app before the hardware arrives.

Serves the real web app + verse library + backgrounds with a pretend frame
behind it.  Crucially, /api/screen now COMPOSITES the current verse (or love
note) onto the chosen background using the same fonts and text zones the
firmware uses — so the little "frame mirror" in the app shows exactly what the
e-paper would show.  Send a note and you'll see it appear, just like the real
thing.

Run:   python preview_app.py
Open:  http://localhost:8080
"""

import json
import os
import random
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import re

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from gfxfont import GFXFont          # noqa: E402  (needs HERE on the path first)

def _sketch_dir():
    """Sketch folder holding data/ + font_*.h. Renamed GraceFrame ->
    Spotify_Frame; detect whichever exists so the mirror reads real assets."""
    root = os.path.dirname(HERE)
    for cand in ("Spotify_Frame", "GraceFrame"):
        if os.path.isdir(os.path.join(root, cand, "data", "bg")):
            return os.path.join(root, cand)
    return os.path.join(root, "Spotify_Frame")


GF_DIR = _sketch_dir()
DATA = os.path.join(GF_DIR, "data")
WWW = os.path.join(DATA, "www")
BG_DIR = os.path.join(DATA, "bg")

SW, SH = 400, 300           # screen size (H is taken by the request handler)
ADD_QUOTES = True

VERSES = []
with open(os.path.join(DATA, "verses.jsonl"), encoding="ascii") as f:
    for i, line in enumerate(f):
        v = json.loads(line)
        v["i"] = i
        VERSES.append(v)
with open(os.path.join(BG_DIR, "index.json")) as f:
    BGS = json.load(f)
BG_BY_NAME = {b["name"]: b for b in BGS}

def _day(b):
    return "special" not in b["tags"] and "night" not in b["tags"]


STATE = {"verse": random.randrange(len(VERSES)),
         "bg": random.choice([b["i"] for b in BGS if _day(b)]),
         "favs": set(), "note": None, "hist": [],
         "settings": {"verse_min": 20, "idle_min": 3, "progress_s": 10,
                      "lyrics_on": True, "lyric_lead_ms": 1100,
                      "quiet_start": 23, "quiet_end": 7,
                      "her_name": "Emily"}}

def read_notes_topic():
    env = os.environ.get("GRACEFRAME_NOTES_TOPIC", "").strip()
    if env:
        return env
    secrets = os.path.join(os.path.dirname(HERE), "Spotify_Frame", "secrets.h")
    try:
        with open(secrets, encoding="utf-8") as f:
            m = re.search(r'#define\s+NOTES_TOPIC\s+"([^"]*)"', f.read())
            return (m.group(1) if m else "").strip()
    except FileNotFoundError:
        return ""


# Remote notes: poll the same private ntfy.sh topic the firmware listens on, so
# this preview "frame" receives notes sent from send-note.html exactly like the
# real device will. The topic is loaded from the ignored secrets file or env.
NOTES_TOPIC = read_notes_topic()


def _remote_notes_loop():
    since = int(time.time())            # ignore anything cached before we start
    base = "https://ntfy.sh/%s/json?poll=1&since=" % NOTES_TOPIC
    while True:
        try:
            with urllib.request.urlopen(base + str(since), timeout=8) as r:
                payload = r.read().decode("utf-8", "replace")
            best = None
            for line in payload.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    env = json.loads(line)
                    if env.get("event") != "message":
                        continue
                    body = json.loads(env.get("message", ""))
                except ValueError:
                    continue
                if body.get("gf") != 1 or not body.get("text"):
                    continue
                mt = int(env.get("time", 0))
                if best is None or mt >= best[0]:
                    best = (mt, body)
            if best:
                mt, body = best
                STATE["note"] = {"text": body.get("text", "")[:300],
                                 "from": body.get("from", ""),
                                 "minutes": int(body.get("minutes", 30))}
                since = mt + 1
                print("remote note received:", STATE["note"]["text"][:48])
        except Exception:
            pass                        # transient network hiccup — try next tick
        time.sleep(8)


def start_remote_notes():
    if len(NOTES_TOPIC) > 4:
        threading.Thread(target=_remote_notes_loop, daemon=True).start()
        print("remote notes: watching configured ntfy topic")

MIME = {".html": "text/html", ".json": "application/json",
        ".js": "text/javascript", ".png": "image/png"}


# ----------------------------------------------------------- the pretend frame
# Text is rendered through the ACTUAL baked device fonts (GraceFrame/font_*.h),
# so the mirror is pixel-identical to the panel and the fit check is exactly the
# firmware's — no TTF approximation, no lying about what fits.
def _gf(name):
    return GFXFont(os.path.join(GF_DIR, f"font_{name}.h"))


SCRIPT_LG, SCRIPT_MD, SCRIPT_SM, SERIF_IT, SANS_SMALL = (
    _gf("ScriptLg"), _gf("ScriptMd"), _gf("ScriptSm"), _gf("SerifIt"),
    _gf("SansSmall"))
REF_FONT, CAPS_FONT = _gf("SerifRefIt"), SANS_SMALL
VERSE_CHAIN = [SCRIPT_LG, SCRIPT_MD, SCRIPT_SM, SERIF_IT]
REFBLOCK = REF_FONT.yadv + 8   # exactly render.cpp's refBlock (SerifRefIt yAdv + 8)


def _bg_image(i):
    """Load a background .bin (bit=1 -> black) into an 'L' image (0=ink)."""
    with open(os.path.join(BG_DIR, f"{i:03d}.bin"), "rb") as f:
        data = f.read()
    return Image.frombytes("1", (SW, SH), bytes(b ^ 0xFF for b in data)).convert("L")


def _wrap(text, font, maxw):
    lines, cur = [], ""
    for word in text.split():
        t = (cur + " " + word).strip()
        if font.width(t) <= maxw:
            cur = t
        elif not cur:
            return None
        else:
            lines.append(cur)
            cur = word
            if font.width(cur) > maxw:
                return None
    if cur:
        lines.append(cur)
    return lines


def _fit(text, zw, zh, reserve=REFBLOCK + 4, ref=""):
    if ref and REF_FONT.width(ref) > zw:
        return None
    for font in VERSE_CHAIN:
        maxlines = (zh - reserve) // font.yadv
        if maxlines < 1:
            continue
        lines = _wrap(text, font, zw)
        if lines and len(lines) <= maxlines and _layout_ok(font, lines, zw, zh, ref):
            return font, lines, font.yadv
    return None


def _layout_ok(font, lines, zw, zh, ref=""):
    block = len(lines) * font.yadv + 8 + REFBLOCK
    if block > zh:
        return False
    top = max(0, (zh - block) // 2)
    cx = zw // 2
    minx = miny = 10**9
    maxx = maxy = -10**9
    ascent = int(font.yadv * 0.72)
    for i, ln in enumerate(lines):
        x1, _, w, _ = font.bounds(ln, 0, 120)
        x = cx - w // 2 - x1
        bx, by, bw, bh = font.bounds(ln, x, top + i * font.yadv + ascent)
        minx = min(minx, bx)
        miny = min(miny, by)
        maxx = max(maxx, bx + bw)
        maxy = max(maxy, by + bh)
    if ref:
        x1, _, w, _ = REF_FONT.bounds(ref, 0, 120)
        x = cx - w // 2 - x1
        baseline = top + len(lines) * font.yadv + 8 + int(REF_FONT.yadv * 0.72)
        bx, by, bw, bh = REF_FONT.bounds(ref, x, baseline)
        minx = min(minx, bx)
        miny = min(miny, by)
        maxx = max(maxx, bx + bw)
        maxy = max(maxy, by + bh)
    return minx >= 0 and miny >= 0 and maxx <= zw and maxy <= zh


def _pack(img):
    """'L' image (0=ink) -> 15000 bytes, bit=1 = black (frame's screen format)."""
    bw = img.convert("1", dither=Image.Dither.NONE)   # bit=1 -> white/paper
    return bytes(b ^ 0xFF for b in bw.tobytes())      # bit=1 -> black


def _center(img, font, s, cx, baseline, ink):
    """Draw s horizontally centered on cx, sitting on the given baseline."""
    x1, _, w, _ = font.bounds(s, 0, baseline)
    font.draw(img, s, int(cx - w // 2 - x1), int(baseline), ink)
    return w


def render_verse(bg, v):
    img = _bg_image(bg["i"])
    d = ImageDraw.Draw(img)
    ink = 255 if bg["ink"] == "white" else 0
    zx, zy, zw, zh = bg["zone"]
    zx, zw = zx + 6, zw - 12
    cx = zx + zw // 2
    text = v["t"] if "t" in v else v["text"]
    if ADD_QUOTES and not text.startswith('"'):
        text = '"' + text + '"'
    ref = v.get("r") or v.get("ref", "")
    fit = _fit(text, zw, zh, ref=ref)
    if not fit:
        raise ValueError(f"verse does not fit {bg['name']}: {ref}")
    font, lines, lh = fit
    block = len(lines) * lh + 8 + REFBLOCK
    top = zy + max(0, (zh - block) // 2)
    ascent = int(lh * 0.72)
    for i, ln in enumerate(lines):
        _center(img, font, ln, cx, top + i * lh + ascent, ink)
    ry = top + len(lines) * lh + 8 + int(REF_FONT.yadv * 0.72)
    rw = _center(img, REF_FONT, ref, cx, ry, ink)
    ly = int(ry - 4)
    d.line([(cx - rw / 2 - 38, ly), (cx - rw / 2 - 14, ly)], fill=ink, width=1)
    d.line([(cx + rw / 2 + 14, ly), (cx + rw / 2 + 38, ly)], fill=ink, width=1)
    return _pack(img)


def render_note(note):
    bg = BG_BY_NAME.get("note-flourish", BGS[0])
    img = _bg_image(bg["i"])
    ink = 0
    zx, zy, zw, zh = bg["zone"]
    zx, zw = zx + 6, zw - 12
    cx = zx + zw // 2
    _center(img, CAPS_FONT, "A NOTE FOR YOU", cx,
            zy + 6 + int(CAPS_FONT.yadv * 0.7), ink)
    frm = note.get("from", "").strip()
    reserve = 26 + (22 if frm else 0)
    fit = _fit(note.get("text", ""), zw, zh, reserve)
    font, lines, lh = fit if fit else (SANS_SMALL, ["Note is too long."], SANS_SMALL.yadv)
    block = len(lines) * lh + (22 if frm else 0)
    top = zy + 26 + max(0, (zh - 26 - block) // 2)
    ascent = int(lh * 0.72)
    for i, ln in enumerate(lines):
        _center(img, font, ln, cx, top + i * lh + ascent, ink)
    if frm:
        _center(img, SERIF_IT, "- " + frm, cx,
                top + len(lines) * lh + 4 + int(SERIF_IT.yadv * 0.72), ink)
    return _pack(img)
    return _pack(img)


def render_screen():
    if STATE["note"]:
        return render_note(STATE["note"])
    return render_verse(BGS[STATE["bg"]], VERSES[STATE["verse"]])


# the same capacity-aware verse/scene pairing the firmware uses, at device metrics
def _fits(bg, text, ref=""):
    zx, zy, zw, zh = bg["zone"]
    zw -= 12
    if ADD_QUOTES and not text.startswith('"'):
        text = '"' + text + '"'
    return _fit(text, zw, zh, ref=ref) is not None


def pick_bg_for(verse_i):
    """Choose a rotating (day) background with room for this verse — mirroring
    the firmware, a themed verse (e.g. 'water') prefers a matching scene."""
    v = VERSES[verse_i]
    text, theme = v["t"], v.get("c", "")
    pool = [b for b in BGS if _day(b)]
    themed = [b["i"] for b in pool if theme in b["tags"] and _fits(b, text, v["r"])]
    if themed:
        return random.choice(themed)
    fitting = [b["i"] for b in pool if _fits(b, text, v["r"])]
    if fitting:
        return random.choice(fitting)
    raise ValueError("no fitting background for verse")


STATE["bg"] = pick_bg_for(STATE["verse"])   # make the first verse fit its scene


# ----------------------------------------------------------------- http server
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def _bytes(self, body, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = u.path
        if p == "/api/status":
            v = VERSES[STATE["verse"]]
            self._json({
                "mode": "note" if STATE["note"] else "verse", "quiet": False,
                "verse": {"id": v["i"], "ref": v["r"], "text": v["t"],
                          "cat": v["c"], "fav": v["i"] in STATE["favs"]},
                "bg": {"i": STATE["bg"], "name": BGS[STATE["bg"]]["name"]},
                "next_verse_s": 900,
                "track": {"id": "", "title": "", "artist": "",
                          "playing": False, "progress": 0, "duration": 1},
                "note": {"active": bool(STATE["note"]),
                         "text": (STATE["note"] or {}).get("text", ""),
                         "from": (STATE["note"] or {}).get("from", "")},
                "settings": dict(STATE["settings"]),
                "lyrics": {"on": STATE["settings"]["lyrics_on"], "state": "none", "lines": 0,
                           "http": 0, "len": 0, "clen": 0,
                           "lead_ms": STATE["settings"]["lyric_lead_ms"]},
                "device": {"rssi": -48, "heap": 178000, "uptime_s": 4321,
                           "refreshes": 87, "verses": len(VERSES),
                           "favs": len(STATE["favs"]), "bgs": len(BGS),
                           "translation": "NIV", "spotify_ok": True,
                           "time": time.strftime("%H:%M")}})
        elif p == "/api/settings":
            self._json(dict(STATE["settings"]))
        elif p == "/api/screen":
            self._bytes(render_screen(), "application/octet-stream")
        elif p == "/api/bg":
            i = int(q.get("i", STATE["bg"]))
            with open(os.path.join(BG_DIR, f"{i:03d}.bin"), "rb") as f:
                self._bytes(f.read(), "application/octet-stream")
        elif p == "/api/verses":
            qq = q.get("q", "").lower()
            cat = q.get("cat", "")
            fav = q.get("fav") == "1"
            off = int(q.get("offset", 0))
            lim = int(q.get("limit", 30))
            hits = [v for v in VERSES
                    if (not fav or v["i"] in STATE["favs"])
                    and (not cat or v["c"] == cat)
                    and (not qq or qq in v["r"].lower() or qq in v["t"].lower())]
            self._json({"total": len(hits), "offset": off, "items": [
                {"i": v["i"], "r": v["r"], "s": v["t"][:107] + "..." if len(v["t"]) > 110 else v["t"],
                 "c": v["c"], "f": v["i"] in STATE["favs"]}
                for v in hits[off:off + lim]]})
        elif p == "/api/verse":
            v = VERSES[int(q["id"])]
            self._json({"id": v["i"], "ref": v["r"], "text": v["t"],
                        "cat": v["c"], "fav": v["i"] in STATE["favs"]})
        elif p == "/api/history":
            self._json({"items": [
                {"i": i, "r": VERSES[i]["r"], "at": 0, "f": i in STATE["favs"]}
                for i in STATE["hist"][:24]]})
        elif p == "/api/bgs":
            cur = VERSES[STATE["verse"]]
            self._json({"current": STATE["bg"], "items": [
                {"i": b["i"], "name": b["name"],
                 "night": "night" in b["tags"], "special": "special" in b["tags"],
                 "fits": _fits(b, cur["t"], cur["r"])}
                for b in BGS]})
        else:
            fp = os.path.join(WWW, "index.html" if p == "/" else p.lstrip("/"))
            if not os.path.isfile(fp):
                fp = os.path.join(WWW, "index.html")
            with open(fp, "rb") as f:
                self._bytes(f.read(), MIME.get(os.path.splitext(fp)[1], "text/plain"))

    def do_POST(self):
        ln = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(ln) or b"{}") if ln else {}
        p = urlparse(self.path).path
        if p == "/api/verse/next":
            pool = [v for v in VERSES if not body.get("cat") or v["c"] == body["cat"]]
            STATE["verse"] = random.choice(pool)["i"]
            STATE["bg"] = pick_bg_for(STATE["verse"])
            STATE["hist"].insert(0, STATE["verse"])
            STATE["note"] = None   # explicit verse pick dismisses any active note
        elif p == "/api/verse/show":
            STATE["verse"] = int(body["id"])
            STATE["bg"] = pick_bg_for(STATE["verse"])
            STATE["hist"].insert(0, STATE["verse"])
            STATE["note"] = None   # explicit verse pick dismisses any active note
        elif p == "/api/fav":
            (STATE["favs"].add if body.get("fav") else STATE["favs"].discard)(int(body["id"]))
        elif p == "/api/bg/show":
            i = int(body["i"])
            cur = VERSES[STATE["verse"]]
            if not _fits(BGS[i], cur["t"], cur["r"]):
                self._json({"ok": False,
                            "err": "That verse needs a roomier scene."}, 409)
                return
            STATE["bg"] = i
            STATE["note"] = None   # a new-scene pick also drops the note
        elif p == "/api/note":
            STATE["note"] = body
        elif p == "/api/note/clear":
            STATE["note"] = None
        elif p == "/api/settings":
            s = STATE["settings"]
            if "verse_min" in body:
                s["verse_min"] = min(240, max(2, int(body["verse_min"])))
            if "idle_min" in body:
                s["idle_min"] = min(60, max(1, int(body["idle_min"])))
            if "progress_s" in body:
                s["progress_s"] = min(120, max(0, int(body["progress_s"])))
            if "lyric_lead_ms" in body:
                s["lyric_lead_ms"] = min(2500, max(-1000, int(body["lyric_lead_ms"])))
            if "quiet_start" in body:
                s["quiet_start"] = min(23, max(0, int(body["quiet_start"])))
            if "quiet_end" in body:
                s["quiet_end"] = min(23, max(0, int(body["quiet_end"])))
            if "lyrics_on" in body:
                s["lyrics_on"] = bool(body["lyrics_on"])
            if "her_name" in body:
                s["her_name"] = str(body["her_name"])[:30]
        self._json({"ok": True})


if __name__ == "__main__":
    print("GraceFrame preview -> http://localhost:8080")
    start_remote_notes()
    ThreadingHTTPServer(("127.0.0.1", 8080), H).serve_forever()
