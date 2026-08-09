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


def exchange_code(args, code):
    """Trade a one-time authorization code for a long-lived refresh token."""
    auth = base64.b64encode(f"{args.id}:{args.secret}".encode()).decode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=urllib.parse.urlencode({
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": REDIRECT}).encode(),
        headers={"Authorization": "Basic " + auth,
                 "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["refresh_token"]


def finish(args, refresh):
    """Show the refresh token and, if asked, push it straight to the frame.
    A failed push is not fatal — the token is printed first, and we show how to
    set it from the app instead."""
    print("\n=== SUCCESS ===")
    print("Refresh token (the account that just signed in):\n" + refresh)
    if args.device:
        body = json.dumps({"id": args.id, "secret": args.secret,
                           "refresh": refresh}).encode()
        req = urllib.request.Request(f"http://{args.device}/api/spotify",
                                     data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                print(f"Pushed to {args.device}: {r.status} — done!")
                return
        except Exception as e:
            print(f"\nCouldn't reach the frame at {args.device} ({e}).")
    print("\nThe token is NOT lost — set it on the frame the easy way:")
    print("  open the GraceFrame app -> Settings -> Spotify and paste:")
    print("    Client ID:     " + args.id)
    print("    Client secret: " + args.secret)
    print("    Refresh token: " + refresh)
    print("  then Save. If graceframe.local won't load, use the frame's IP")
    print("  (e.g. http://192.168.0.244), or rerun with --device <that-IP>.")


def code_from_url(pasted):
    q = urllib.parse.parse_qs(urllib.parse.urlparse(pasted.strip()).query)
    return q.get("code", [None])[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True)
    ap.add_argument("--secret", required=True)
    ap.add_argument("--device", help="e.g. graceframe.local — push token to frame")
    ap.add_argument("--manual", action="store_true",
                    help="remote sign-in: send her a link; she taps Agree on her "
                         "own phone and sends you back the address bar")
    ap.add_argument("--push-token",
                    help="skip sign-in and just push this refresh token to "
                         "--device (use the frame's IP if .local won't resolve)")
    args = ap.parse_args()

    # Already have a refresh token (e.g. printed by an earlier run)? Just push it.
    if args.push_token:
        finish(args, args.push_token)
        return

    state = pysecrets.token_urlsafe(12)
    url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": args.id, "response_type": "code", "redirect_uri": REDIRECT,
        "scope": SCOPE, "state": state, "show_dialog": "true"})

    # Remote: she authorizes on HER device; you never touch her password.
    if args.manual:
        print("\n--- Remote sign-in (she uses her own phone) ---")
        print("1) Send HER this link. She opens it, signs in, and taps Agree:\n")
        print("   " + url + "\n")
        print("2) Her browser then tries to open a page that will NOT load (the")
        print("   address starts http://127.0.0.1:8888/callback?code=...). That is")
        print("   EXPECTED — ask her to copy that whole address and send it to you.\n")
        code = code_from_url(input("Paste the address she sent, here: "))
        if not code:
            raise SystemExit("No sign-in code found in that address — try again.")
        finish(args, exchange_code(args, code))
        return

    # Local: we deliberately do NOT auto-open a browser (that reused YOUR login).
    # You open the link yourself in an Incognito window, where SHE signs in.
    srv = HTTPServer(("127.0.0.1", 8888), CB)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    print("\nOpen this link in an INCOGNITO / PRIVATE window (Ctrl+Shift+N) and have")
    print("HER sign in there — do NOT open it in your normal browser:\n")
    print("   " + url + "\n")
    print("Waiting for her to tap Agree…")
    while "code" not in got:
        pass
    srv.server_close()
    if not got["code"]:
        raise SystemExit("Spotify did not return a code — try again.")
    finish(args, exchange_code(args, got["code"]))


if __name__ == "__main__":
    main()
