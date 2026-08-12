# GraceFrame ✝

An e-ink frame for the person you love. When she plays Spotify it shows her
music — album art, title, progress, and live synced lyrics where available.
When the music stops, it quietly turns into Scripture: **135 NIV verses** over **18 hand-drawn,
postcard-style scenes** (three crosses at dawn, a shepherd's field, a moonlit
starry night…), a new one every 20 minutes. Each verse is paired only with a
scene that has room for it, so the words are always complete and razor-sharp.

And it's hers to hold: a **phone app** (no App Store needed) shows a live
mirror of the screen, lets her browse and search every verse, save favorites
(they appear more often), pick scenes, and receive **notes** you send in
handwriting — from her Wi-Fi *or from anywhere* (see “Send her a note from
anywhere,” below).

Extra graces built in:
- **Quiet hours** — the frame holds one verse of peace all night, no flashing.
- **Special dates** — birthdays/anniversaries greet her by name in the morning.
- **Skip-proof e-ink** — rapid song-skipping never wears the panel (see below).

---

## 1. What's in this folder

```
Spotify_Frame/       <- the Arduino sketch (open Spotify_Frame.ino)
  data/              <- goes onto the ESP32's flash: verses, scenes, web app
  font_*.h           <- generated fonts (script, serif, sans)
  config.h           <- personalization: her name, dates, timezone, pins
  secrets.h          <- Wi-Fi + Spotify credentials (keep private!)
tools/               <- asset pipeline (already run — outputs are committed)
  make_backgrounds.py  fetch_verses.py  make_fonts.py
  spotify_auth.py      preview_app.py
WIRING.md            <- how to wire (do this first)
README.md            <- you are here
```

Everything in `Spotify_Frame/data` and the fonts are **already generated** —
you don't need to run any Python unless you want to tweak scenes or verses.

**Try the app right now** (before the hardware arrives):
`python tools/preview_app.py` → open http://localhost:8080 on this PC.

## 2. Wire it

Follow **WIRING.md** (5 minutes, 8 wires).

## 3. Arduino IDE setup (once)

1. Install **Arduino IDE 2.x**.
2. *File → Preferences → Additional boards manager URLs*, add:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
3. *Boards Manager* → install **esp32 by Espressif Systems**.
4. *Library Manager* → install:
   **GxEPD2** · **Adafruit GFX Library** · **ArduinoJson** · **TJpg_Decoder**
5. Optional if you use the IDE: install the LittleFS uploader (for step 6):
   download
   `arduino-littlefs-upload-*.vsix` from
   https://github.com/earlephilhower/arduino-littlefs-upload/releases
   and drop it into `C:\Users\<you>\.arduinoIDE\plugins\`
   (create the folder if needed), then restart the IDE.

## 4. Personalize

- `Spotify_Frame/config.h` — set `HER_NAME`, add `SPECIAL_DATES`
  (birthday, anniversary…), check `TIMEZONE`.
- `Spotify_Frame/secrets.h` — set **her home Wi-Fi** in `WIFI_SSID`/`WIFI_PASS`
  so she never has to configure anything, and confirm the Spotify values (see §9
  — the refresh token must belong to the account whose music you want shown).

## 5. Flash the firmware and data

Recommended from PowerShell on this PC:

```
cd C:\Users\Daniel Weber\OneDrive\Desktop
.\build_spotify_frame.ps1 -Upload -UploadData -Port COM6
```

That script pins a stable Arduino CLI, refuses to upload if compile fails, flashes
the firmware, then rebuilds and uploads the LittleFS data image with the scenes,
verses, and phone app.

If you use Arduino IDE instead, open `Spotify_Frame/Spotify_Frame.ino`. Select
**Tools →**
- Board: **ESP32S3 Dev Module**
- USB CDC On Boot: **Default / Disabled**
- PSRAM: **OPI PSRAM**
- Flash Size: **16MB**
- Partition Scheme: **16M Flash (3MB APP/9.9MB FATFS)**
- Port: your COM port

Click **Upload**. (If upload won't start: hold the BOOT button, tap RESET,
release BOOT, retry.)

## 6. Upload the data (verses, scenes, app)

The PowerShell command above already does this when you include `-UploadData`.

In Arduino IDE, with the sketch still open: press **Ctrl+Shift+P**, run
**“Upload LittleFS to Pico/ESP8266/ESP32”**. This copies `Spotify_Frame/data`
onto the board (~1 MB, takes a minute). Close the Serial Monitor first —
the uploader needs the port.

## 7. First light

- The frame connects to Wi-Fi and shows its first verse. Play Spotify
  anywhere on her account → the frame follows within ~5 seconds. If synced
  lyrics are available, one clean line appears under the album art.
- If Wi-Fi fails it opens its own network **GraceFrame-Setup** — join it
  with a phone and pick the home network. After credentials work, the panel
  confirms the SSID, IP address, and `graceframe.local`.

## 8. Put the app on her phone

1. On her phone (same Wi-Fi), open **http://graceframe.local**
   (if her phone balks at `.local`, use the frame's IP — it's printed in
   the Serial Monitor at boot).
2. Share → **Add to Home Screen**. Done — it opens full-screen like a real
   app, icon and all.

## 8½. Send her a note from anywhere

When you're **on her Wi-Fi**, the app's **Notes** tab sends straight to the
frame. When you're **not** — at your place, at work — use **`send-note.html`**:

1. Open `send-note.html` on **your** phone (email/AirDrop it to yourself, or
   host it anywhere — even a free GitHub Pages). Share → **Add to Home Screen**
   so it's one tap away.
2. Type a message, tap **Send to frame**. It appears on her frame within a few
   seconds, in handwriting — no matter whose network you're on.

How it works: the frame quietly checks a **private channel** on the free
[ntfy.sh](https://ntfy.sh) service; `send-note.html` posts to that same channel.
The channel name is a shared secret defined as `NOTES_TOPIC` in the ignored
`Spotify_Frame/secrets.h`. The QR generator reads it from there and puts it in
your private `send-note.html?token=...` link. To rotate it, set a new random
topic in `secrets.h`, rerun `python tools/make_qr.py`, and replace the private
QR/link. Notes pass through ntfy.sh's public relay, so keep them sweet, not
secret. Leave `NOTES_TOPIC` blank to turn the remote path off; the on-Wi-Fi
Notes tab still works.

Want to check the pipe is live? `python tools/test_remote_note.py` publishes a
test note and confirms it comes back.

## 9. Spotify

The refresh token in `secrets.h` already follows the account it was made
with. To follow **her** account instead, make sure her account (or your
family account) is the one that authorized it. To re-link:

```
python tools/spotify_auth.py --id CLIENT_ID --secret CLIENT_SECRET --device graceframe.local
```

(Client ID/secret from https://developer.spotify.com — the app needs
redirect URI `http://127.0.0.1:8888/callback`.)

---

## How the panel is protected (why skipping songs won't hurt it)

- A new song must **survive 2.5 s** before it's drawn — a skip-storm
  settles to a single refresh of the song she lands on.
- Full-screen refreshes are hard-limited to one per 3 s. Lyric/timer strip
  refreshes share a separate 900 ms gate so they can stay in sync without
  hammering the panel.
- Each **new song is a clean full refresh**, so the previous title/art is
  wiped instead of ghosting under the next one. Within the same song, lyric
  changes clean just the lyric strip. Timer ticks use one masked clean transaction
  over the bottom progress window: only the elapsed-time digits and the moving
  fill edge are cleaned through white, with the previous progress strip preserved
  during phase 1 so the fill cannot jump ahead during the clean pass. Small
  Spotify polling jitter is ignored; real seeks still snap.
- The elapsed time is **interpolated locally** between Spotify polls, so it
  stays accurate without extra network calls; the bar repaints every 10 s by
  default.
- Verse changes are calm full refreshes every 20 min (~70/day — panels are
  rated for 1,000,000+).
- During **quiet hours** the panel doesn't refresh at all; e-ink holds the
  image with zero power.

## Tweaks & tools

| I want to… | Do this |
|---|---|
| Change rotation timing, quiet hours, her name | In the app → Settings |
| Add/redraw scenes | edit `tools/make_backgrounds.py`, run it, re-do step 6 |
| Change verse list / translation | edit `tools/fetch_verses.py`, run it (`--translation KJV` etc.), re-do step 6 |
| Different fonts/sizes | edit `tools/make_fonts.py`, run it, re-flash (step 5) |
| Panel blank/scrambled | switch panel line in `config.h` (see WIRING.md #5) |

**Note on the text:** verses come from bolls.life's NIV text (the classic
1984 edition) for personal, non-commercial use — perfect for a gift, not
for resale.

Built with love (and a soldering-free ribbon cable). 🤍
