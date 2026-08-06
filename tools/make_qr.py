#!/usr/bin/env python3
"""Generate the two QR codes for GraceFrame.

  graceframe_local_qr.png   http://graceframe.local        (open the app on Wi-Fi)
  graceframe_remote_qr.png  send-note.html?token=<TOPIC>   (send a note from ANY
                                                            network)

The remote QR MUST carry the private note token or the sender page disables
itself. We read the token straight from GraceFrame/secrets.h (NOTES_TOPIC) so
the QR can never drift out of sync with what the frame listens on.

Run:  python tools/make_qr.py
"""
import os
import re
import sys

import qrcode

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Where the standalone sender page is hosted (GitHub Pages).
SENDER_URL = "https://danzolo211.github.io/Spotify_Frame/send-note.html"
LOCAL_URL = "http://graceframe.local"


def read_notes_topic():
    """Pull NOTES_TOPIC out of Spotify_Frame/secrets.h so the token stays in sync."""
    secrets = os.path.join(ROOT, "Spotify_Frame", "secrets.h")
    try:
        with open(secrets, encoding="utf-8") as f:
            m = re.search(r'#define\s+NOTES_TOPIC\s+"([^"]*)"', f.read())
    except FileNotFoundError:
        m = None
    if not m or not m.group(1):
        sys.exit("Could not read NOTES_TOPIC from GraceFrame/secrets.h — the "
                 "remote QR needs it. Set NOTES_TOPIC and re-run.")
    return m.group(1)


def save(url, name):
    path = os.path.join(ROOT, name)
    qrcode.make(url).save(path)
    print(f"  -> {name}  ({url})")


def main():
    token = read_notes_topic()
    print("Generating QR codes...")
    save(f"{SENDER_URL}?token={token}", "graceframe_remote_qr.png")
    save(LOCAL_URL, "graceframe_local_qr.png")
    print("Done.")


if __name__ == "__main__":
    main()
