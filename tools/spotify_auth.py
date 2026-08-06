#!/usr/bin/env python3
"""
spotify_auth.py — get (or renew) the Spotify refresh token for GraceFrame.

You only need this if the frame ever loses its Spotify link (the token in
secrets.h already works). One-time setup at https://developer.spotify.com:
  1. Create an app; add redirect URI exactly:  http://127.0.0.1:8888/callback
  2. Note the Client ID and Client Secret.

Run:
  python spotify_auth.py --id CLIENT_ID --secret CLIENT_SECRET
  python spotify_auth.py --id ... --secret ... --device graceframe.local
      (also pushes the new token straight to the frame)

A browser opens; log in with the Spotify account the frame should follow
(hers!), approve, and the refresh token prints here.
"""

import argparse
import base64
import json
import secrets as pysecrets
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

REDIRECT = "http://127.0.0.1:8888/callback"
SCOPE = "user-read-currently-playing user-read-playback-state"

got = {}


class CB(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        got["code"] = q.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2 style='font-family:serif'>GraceFrame is linked! "
                         b"You can close this tab.</h2>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--device", help="e.g. graceframe.local — push token to frame")
    args = ap.parse_args()

    state = pysecrets.token_urlsafe(12)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": args.id, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPE, "state": state})
    srv = HTTPServer(("127.0.0.1", 8888), CB)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("Opening browser — log in with HER Spotify account…")
    webbrowser.open(url)
    while "code" not in got:
        pass
    srv.server_close()
    if not got["code"]:
        raise SystemExit("Spotify did not return a code — try again.")

    auth = base64.b64encode(f"{args.id}:{args.secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": got["code"],
            "redirect_uri": REDIRECT}).encode(),
        headers={"Authorization": "Basic " + auth,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        tok = json.loads(r.read())
    refresh = tok["refresh_token"]
    print("\n=== SUCCESS ===")
    print("Refresh token:\n" + refresh)
    print("\nPaste into GraceFrame/secrets.h (SP_REFRESH_TOKEN), or the app's")
    print("Settings -> Spotify, or rerun with --device graceframe.local")

    if args.device:
        body = json.dumps({"id": args.id, "secret": args.secret,
                           "refresh": refresh}).encode()
        req = urllib.request.Request(f"http://{args.device}/api/spotify",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"Pushed to {args.device}: {r.status}")


if __name__ == "__main__":
    main()
