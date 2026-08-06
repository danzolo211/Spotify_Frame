/* =====================================================================
   GraceFrame — an e-ink frame that shows what she's listening to,
   and speaks Scripture over her day when the music stops.

   ESP32-S3 + Waveshare 4.2" e-paper (400x300)

   Modes
     SPOTIFY  music is playing: album art, title, artist, progress
     VERSE    rotating NIV verses over hand-drawn backgrounds
     NOTE     a note sent from the phone app
     SPECIAL  birthdays / anniversaries, shown in the morning

   The phone app lives at  http://graceframe.local
   Full setup guide in ../README.md — wiring in ../WIRING.md

   Libraries (Library Manager): GxEPD2, Adafruit GFX, ArduinoJson,
   TJpg_Decoder. Board: "ESP32S3 Dev Module", PSRAM: "OPI PSRAM",
   Flash Size: 16MB, Partition: "8M with spiffs (3MB APP/1.5MB SPIFFS)".
   ===================================================================== */

#include <Arduino.h>
#include <WiFi.h>
#include <LittleFS.h>
#include <time.h>

#include "config.h"
#include "state.h"
#include "util.h"
#include "epaper.h"
#include "render.h"
#include "verses.h"
#include "bgs.h"
#include "spotify.h"
#include "netmgr.h"
#include "webapi.h"
#include "remote_notes.h"

// ------------------------------------------------------------ locals
static uint32_t nextPollAt = 0;
static String committedTrack = "";
static String pendingTrack = "";
static uint32_t pendingSince = 0;
static Track pendingInfo;
static uint32_t lastBarPush = 0;
static bool artValid = false;
static bool prevPlaying = false;
static uint32_t specialShownAt = 0;
static uint32_t lastWifiCheck = 0;
static bool assetsOk = false;

// Local progress interpolation: Spotify is only polled every few seconds, but
// the elapsed time ticks smoothly. We remember the last reported position and
// advance it with the clock, so what's drawn matches the song without extra
// API calls. See liveProgressMs().
static long     progressAnchorMs = 0;
static uint32_t progressAnchorAt = 0;

// When she picks a verse/scene in the app while music happens to be playing,
// hold off the automatic Spotify takeover briefly so her choice stays up.
static uint32_t idleHoldUntil = 0;

// ------------------------------------------------------------ helpers
static bool timeSynced() { return time(nullptr) > 1600000000; }

static bool isNightNow() {
  if (!timeSynced()) return false;
  time_t now = time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  return t.tm_hour >= 20 || t.tm_hour < 6;
}

static bool inQuietHours() {
  if (!timeSynced()) return false;
  time_t now = time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  uint8_t h = t.tm_hour, s = settings.quietStart, e = settings.quietEnd;
  if (s == e) return false;
  return (s < e) ? (h >= s && h < e) : (h >= s || h < e);
}

// Pick a background that actually has room for this verse. Tries a handful of
// random (recent-avoiding) scenes; if none fit — a very long verse — it falls
// back to the roomiest one it saw, so the words are never chopped off.
static int pickBgFor(const String& text, bool night) {
  int best = -1;
  long bestCap = -1;
  for (int tries = 0; tries < 24; tries++) {
    int bg = bgsPickRandom(night);
    const BgInfo& b = bgsGet(bg);
    if (renderVerseFits(text, b.zw - 12, b.zh)) return bg;
    long cap = (long)b.zw * b.zh;
    if (cap > bestCap) { bestCap = cap; best = bg; }
  }
  return best >= 0 ? best : bgsPickRandom(night);
}

static void showRandomVerse(const String& cat = "", int forceBg = -1) {
  if (!assetsOk) return;
  int id = versesPickRandom(cat);
  if (id < 0) return;
  Verse v;
  if (!versesGet(id, v)) return;
  int bg = (forceBg >= 0) ? forceBg : pickBgFor(v.text, isNightNow());
  renderVerse(v, bg);
  epdPush(PUSH_FULL);
  app.mode = MODE_VERSE;
  app.verseId = id;
  app.bgId = bg;
  app.verseShownAt = millis();
  versesHistoryAdd(id);
}

static void showVerseById(int id, int forceBg = -1) {
  Verse v;
  if (!versesGet(id, v)) return;
  int bg = (forceBg >= 0) ? forceBg : pickBgFor(v.text, isNightNow());
  renderVerse(v, bg);
  epdPush(PUSH_FULL);
  app.mode = MODE_VERSE;
  app.verseId = id;
  app.bgId = bg;
  app.verseShownAt = millis();
  versesHistoryAdd(id);
}

static void showNoteScreen() {
  renderNote(app.note.text, app.note.from);
  epdPush(PUSH_FULL);
  app.mode = MODE_NOTE;
}

static void backToIdleScreen() {
  if (app.note.active) showNoteScreen();
  else showRandomVerse();
}

// ------------------------------------------------------------ spotify
// Where the song is right now, interpolated from the last poll so the elapsed
// time is honest between API calls (and never runs past the song's end).
static long liveProgressMs() {
  long p = progressAnchorMs;
  if (app.trackPlaying) p += (long)(millis() - progressAnchorAt);
  if (p < 0) p = 0;
  if (app.trackDuration > 0 && p > app.trackDuration) p = app.trackDuration;
  return p;
}

// Draw the Now Playing screen with a fresh, interpolated position.
static void drawSpotify() {
  app.trackProgress = liveProgressMs();
  renderSpotify(spotifyArtBits(), artValid);
}

static void commitTrack(const Track& t) {
  committedTrack = t.id;
  app.trackId = t.id;
  app.trackTitle = t.title;
  app.trackArtist = t.artist;
  app.trackPlaying = t.playing;
  app.trackProgress = t.progress;
  app.trackDuration = t.duration;
  progressAnchorMs = t.progress;
  progressAnchorAt = millis();
  artValid = t.artUrl.length() ? spotifyFetchArt(t.artUrl) : false;
  drawSpotify();
  // A new song is a clean slate: always a full refresh so the previous title,
  // artist and art are wiped instead of ghosting under the new ones.
  epdPush(PUSH_FULL);
  app.mode = MODE_SPOTIFY;
  lastBarPush = millis();
  prevPlaying = t.playing;
}

static void spotifyTick() {
  if ((int32_t)(millis() - nextPollAt) < 0) return;

  Track t;
  int r = spotifyPoll(t);
  bool active = false;

  if (r == SP_OK) {
    app.trackProgress = t.progress;
    app.trackDuration = t.duration;
    app.trackPlaying = t.playing;
    progressAnchorMs = t.progress;      // re-sync the interpolation clock
    progressAnchorAt = millis();
    // keep app fields fresh for the phone even before anything is drawn
    app.trackId = t.id;
    app.trackTitle = t.title;
    app.trackArtist = t.artist;
    if (t.playing) {
      app.lastMusicActive = millis();
      active = true;
    }

    bool showingThis = (app.mode == MODE_SPOTIFY && t.id == committedTrack);

    if (showingThis) {
      // Same song already on the panel: nudge the play/pause icon or the bar.
      // Both live in the bottom strip, so keep every in-song update a clean
      // region refresh of just that strip (y >= 208).
      if (t.playing != prevPlaying) {                 // play <-> pause
        prevPlaying = t.playing;
        drawSpotify();
        epdPush(PUSH_REGION, 0, 208, SCREEN_W, SCREEN_H - 208);
        lastBarPush = millis();
      } else if (t.playing && settings.progressS > 0 &&
                 millis() - lastBarPush >= settings.progressS * 1000UL) {
        drawSpotify();
        epdPush(PUSH_REGION, 0, 208, SCREEN_W, SCREEN_H - 208);
        lastBarPush = millis();
      }
    } else if (t.playing && !app.note.active &&
               (int32_t)(millis() - idleHoldUntil) >= 0) {
      // Music is playing but the panel is on a verse/note (or a different
      // song). Bring Now Playing (back) up. A note keeps priority until it
      // ends; a just-picked verse holds for idleHoldUntil. Debounce skips so a
      // skip-storm settles to one refresh of the song she lands on.
      if (t.id != pendingTrack) {
        pendingTrack = t.id;
        pendingSince = millis();
        pendingInfo = t;
      } else if (millis() - pendingSince >= TRACK_STABLE_MS) {
        commitTrack(t);
      }
    }
  } else if (r == SP_IDLE) {
    app.trackPlaying = false;
  }

  // music stopped long enough -> return to verses (a live note keeps the screen)
  if (app.mode == MODE_SPOTIFY && !app.trackPlaying &&
      millis() - app.lastMusicActive >= settings.idleMin * 60000UL) {
    committedTrack = "";
    pendingTrack = "";
    backToIdleScreen();
  }

  uint32_t interval =
      (active || millis() - app.lastMusicActive < 120000UL)
          ? POLL_ACTIVE_MS : POLL_IDLE_MS;
  if (r == SP_ERROR) interval = 15000;
  if (r == SP_COOLDOWN) interval = max(spotifyCooldownMs() + 500, (uint32_t)5000);
  nextPollAt = millis() + interval;
}

// ------------------------------------------------------------ ticks
static void verseTick() {
  if (app.mode != MODE_VERSE || app.quiet || !assetsOk) return;
  if (millis() - app.verseShownAt >= settings.verseMin * 60000UL)
    showRandomVerse();
}

static void noteTick() {
  if (!app.note.active || app.note.until == 0) return;
  if ((int32_t)(millis() - app.note.until) >= 0) {
    app.note.active = false;
    if (app.mode == MODE_NOTE) {
      if (app.trackPlaying) {          // music is on: let Now Playing retake
        committedTrack = "";
        pendingTrack = "";
      } else {
        showRandomVerse();
      }
    }
  }
}

static void specialTick() {
  static uint32_t lastCheck = 0;
  static int lastDay = -1;
  if (millis() - lastCheck < 30000) return;
  lastCheck = millis();
  if (!timeSynced()) return;
  time_t now = time(nullptr);
  struct tm t;
  localtime_r(&now, &t);
  if (t.tm_mday != lastDay) {           // new day
    lastDay = t.tm_mday;
    app.specialShownToday = false;
  }
  if (app.specialShownToday || app.mode != MODE_VERSE || app.quiet) return;
  if (t.tm_hour < 7 || t.tm_hour >= 12) return;
  for (const SpecialDate& d : SPECIAL_DATES) {
    if (d.month == t.tm_mon + 1 && d.day == t.tm_mday) {
      renderSpecial(d.title, d.message, settings.herName);
      epdPush(PUSH_FULL);
      app.mode = MODE_SPECIAL;
      app.specialShownToday = true;
      specialShownAt = millis();
      return;
    }
  }
}

static void specialTimeout() {
  if (app.mode == MODE_SPECIAL && millis() - specialShownAt >= 90UL * 60000UL)
    showRandomVerse();
}

static void quietTick() {
  bool q = inQuietHours();
  if (q == app.quiet) return;
  app.quiet = q;
  if (app.mode != MODE_VERSE && app.mode != MODE_SPECIAL) return;
  if (q) {
    // goodnight: a verse of peace under a night sky, held all night
    if (!assetsOk) return;
    int id = versesPickRandom("peace");
    Verse v;
    if (id >= 0 && versesGet(id, v)) {
      int bg = pickBgFor(v.text, true);
      renderVerse(v, bg);
      epdPush(PUSH_FULL);
      app.mode = MODE_VERSE;
      app.verseId = id;
      app.bgId = bg;
      app.verseShownAt = millis();
      versesHistoryAdd(id);
    }
  } else {
    showRandomVerse("hope");   // new morning, new mercies
  }
}

static void processPending() {
  Pending& p = app.pending;
  if (p.newNote) {
    p.newNote = false;
    app.note = p.note;
    app.note.active = true;
    showNoteScreen();
  }
  if (p.clearNote) {
    p.clearNote = false;
    if (app.note.active) {
      app.note.active = false;
      if (app.mode == MODE_NOTE) {
        if (app.trackPlaying) {        // music is on: let Now Playing retake
          committedTrack = "";
          pendingTrack = "";
        } else {
          showRandomVerse();
        }
      }
    }
  }
  if (p.showVerseId != -2) {
    int id = p.showVerseId;
    String cat = p.verseCat;
    p.showVerseId = -2;
    p.verseCat = "";
    app.note.active = false;   // an explicit verse pick dismisses any lingering
                               // note, so it can't resurrect via backToIdleScreen
    idleHoldUntil = millis() + 60000;  // keep her pick up even if music is on
    if (id == -1) showRandomVerse(cat);
    else showVerseById(id);
  }
  if (p.showBgId >= 0) {
    int bg = p.showBgId;
    p.showBgId = -1;
    if ((app.mode == MODE_VERSE || app.mode == MODE_NOTE) &&
        app.verseId >= 0 && bg < bgsCount()) {
      app.note.active = false; // a new-scene pick also drops the note and
      idleHoldUntil = millis() + 60000;
      showVerseById(app.verseId, bg);   // re-skins the verse (back to SCRIPTURE)
    }
  }
  if (p.forceRefresh) {
    p.forceRefresh = false;
    switch (app.mode) {
      case MODE_SPOTIFY: drawSpotify(); break;
      case MODE_NOTE:    renderNote(app.note.text, app.note.from); break;
      default: {
        Verse v;
        if (app.verseId >= 0 && versesGet(app.verseId, v))
          renderVerse(v, app.bgId);
        break;
      }
    }
    epdPush(PUSH_FULL);
  }
}

static void wifiTick() {
  if (millis() - lastWifiCheck < 30000) return;
  lastWifiCheck = millis();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("wifi: reconnecting...");
    WiFi.reconnect();
  }
}

// ------------------------------------------------------------ setup/loop
void setup() {
  Serial.begin(115200);
  delay(200);
  randomSeed(esp_random());

  epdInit();
  renderInit();
  renderMessage("Good things are loading...", "");
  epdPush(PUSH_FULL);

  if (!LittleFS.begin(true, "/littlefs", 10, "ffat")) Serial.println("LittleFS mount failed!");
  settings.load();
  bool v = versesBegin();
  bool b = bgsBegin();
  assetsOk = v && b;

  if (!netConnect()) netPortal();   // portal blocks + restarts
  netTimeMdns();
  spotifyBegin();
  webBegin();
  remoteNotesBegin();

  if (assetsOk) {
    showRandomVerse();
  } else {
    renderMessage("Almost there!",
                  "Upload the data folder (see README step 6)");
    epdPush(PUSH_FULL);
  }
  app.lastMusicActive = 0;
}

void loop() {
  webHandle();
  processPending();
  remoteNotesTick();
  spotifyTick();
  verseTick();
  noteTick();
  specialTick();
  specialTimeout();
  quietTick();
  wifiTick();
  delay(2);
}
