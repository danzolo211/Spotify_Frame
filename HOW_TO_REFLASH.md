# How to re-flash GraceFrame

Follow this any time you update the frame. **Every update is TWO uploads** —
(A) the firmware (the code) and (B) the data (verses, scenes, phone app). Do
both, in order. It takes about 5 minutes.

> **This latest update needs BOTH A and B** (the code and the app both changed).

---

## Before you start (once)

1. Plug the frame into this computer with the **USB-C cable**.
2. Open **Arduino IDE**. Go to **File → Open** and open:
   `Spotify_Frame/Spotify_Frame.ino`
3. In the **Tools** menu, set these exactly:
   - **Board:** ESP32S3 Dev Module
   - **USB CDC On Boot:** Enabled
   - **PSRAM:** OPI PSRAM
   - **Flash Size:** 16MB
   - **Partition Scheme:** 8M with spiffs (3MB APP/1.5MB SPIFFS)
   - **Port:** the COM port that appears when you plug the frame in (e.g. `COM5`).
     Not sure which? Unplug the frame, look at the list, plug it back in — the
     new one that appears is it.

---

## Part A — Flash the firmware (the code)

1. **Close the Serial Monitor** if it's open (it holds the port and blocks uploads).
2. Click the **Upload** button — the round **→** arrow at the top-left.
3. Wait until the bottom says **"Done uploading."** (about 1–2 minutes).

**If the upload won't start / errors out:** hold the **BOOT** button on the board,
tap **RESET** once, let go of **BOOT**, then click **Upload** again.

---

## Part B — Upload the data (verses, scenes, phone app)

1. Keep the same sketch open, **Serial Monitor still closed**.
2. Press **Ctrl + Shift + P** (opens the command palette).
3. Start typing and choose: **"Upload LittleFS to Pico/ESP8266/ESP32"**.
4. Wait about a minute for it to finish.

> Don't see that command? Install the uploader plugin once (README §3, step 5),
> restart Arduino IDE, and try again.

---

## When you only changed one thing

| What changed | What to upload |
|---|---|
| Firmware / `.cpp` / `.h` / `.ino` / `config.h` | **A only** |
| Phone app (`data/www/…`), verses, or scenes (`data/…`) | **B only** |
| Not sure, or a big update like this one | **Do BOTH** |

---

## Done

Unplug it from the computer and plug it into any USB charger. It boots, joins
Wi-Fi, and shows a verse within a few seconds. Play Spotify and it appears.

**First time at her place:** it won't know her Wi-Fi yet, so it shows the
"Let's get connected" screen — that's expected. She sets it herself with the
letter in `For_Emily.html` (she never has to give you her password).
