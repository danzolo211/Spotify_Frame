#!/usr/bin/env python3
"""End-to-end check for remote notes: publish exactly like send-note.html, then
poll + parse exactly like the frame / preview_app. Exits non-zero on failure."""
import json
import os
import re
import sys
import time
import urllib.request


def read_notes_topic():
    env = os.environ.get("GRACEFRAME_NOTES_TOPIC", "").strip()
    if env:
        return env
    secrets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "Spotify_Frame", "secrets.h")
    try:
        with open(secrets, encoding="utf-8") as f:
            m = re.search(r'#define\s+NOTES_TOPIC\s+"([^"]*)"', f.read())
            return (m.group(1) if m else "").strip()
    except FileNotFoundError:
        return ""


TOPIC = read_notes_topic()
BASE = "https://ntfy.sh/" + TOPIC


def publish(text, frm, minutes):
    payload = json.dumps({"gf": 1, "text": text, "from": frm, "minutes": minutes})
    req = urllib.request.Request(
        BASE, data=payload.encode("utf-8"),
        headers={"Content-Type": "text/plain"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def poll(since):
    url = BASE + "/json?poll=1&since=" + str(since)
    with urllib.request.urlopen(url, timeout=10) as r:
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
    return best


def main():
    if not TOPIC:
        print("FAIL: NOTES_TOPIC not set in GRACEFRAME_NOTES_TOPIC or Spotify_Frame/secrets.h")
        return 1
    since = int(time.time()) - 2
    text = "Test note %d — thinking of you." % int(time.time())
    print("publishing:", text)
    code = publish(text, "Daniel", 30)
    print("  publish HTTP", code)
    if code not in (200, 201):
        print("FAIL: publish rejected")
        return 1
    for attempt in range(6):
        time.sleep(2)
        got = poll(since)
        if got:
            mt, body = got
            print("  polled note:", body)
            ok = body["text"] == text and body["from"] == "Daniel" and body["minutes"] == 30
            print("PASS" if ok else "FAIL: payload mismatch")
            return 0 if ok else 1
        print("  (attempt %d: nothing yet)" % (attempt + 1))
    print("FAIL: note never came back from ntfy")
    return 1


if __name__ == "__main__":
    sys.exit(main())
