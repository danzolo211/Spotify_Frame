// ============================================================
//  GraceFrame — everything you might want to personalize
// ============================================================
#pragma once
#include <Arduino.h>

// ---------- her ----------
// The name shown on greetings & special days (change any time in the app).
#define HER_NAME        "Emily"
#define ADD_QUOTES      true          // wrap verses in quotation marks

// Special dates: {month, day, title, message} — shown from 7am to noon.
// Keep messages warm and encouraging. Add/remove your own.
struct SpecialDate {
  uint8_t month, day;
  const char* title;
  const char* message;
};
static const SpecialDate SPECIAL_DATES[] = {
  { 1,  1, "Happy New Year",   "A fresh page, and grace for every line of it." },
  { 7, 10, "The Day We Met",   "I'm so grateful for the day we met!! I was never the same since." },
  { 8, 15, "Happy Birthday!",  "The world shone a little brighter since the day you were born." },
};


// POSIX timezone string (default: US Eastern).
// Central: "CST6CDT,M3.2.0,M11.1.0"  Mountain: "MST7MDT,M3.2.0,M11.1.0"
// Pacific: "PST8PDT,M3.2.0,M11.1.0"  Arizona:  "MST7"
#define TIMEZONE        "EST5EDT,M3.2.0,M11.1.0"

// ---------- behavior defaults (all changeable live in the app) ----------
#define DEF_VERSE_MIN    20   // minutes between verses
#define DEF_IDLE_MIN     3    // minutes of Spotify silence before verses return
#define DEF_PROGRESS_S   10   // Now-Playing timer update seconds (0 = frozen).
                              // The elapsed time is interpolated locally between
                              // Spotify polls, so it stays truthful even though
                              // the panel only repaints this often. Each update
                              // cleans and repaints only the bottom strip through
                              // white: crisp digits/bar, no full-screen flash.
                              // Cadence is floored to 10s to keep blinking gentle.
#define MIN_PROGRESS_S   10
#define DEF_QUIET_START  23   // hour the screen goes still for the night
#define DEF_QUIET_END    7

// ---------- e-ink protection ----------
#define PARTIALS_BEFORE_FULL  30     // fast refreshes before a deep clean
#define FULL_EVERY_MS         1800000UL // ...or at most every 30 minutes
#define MIN_REFRESH_GAP_MS    3000   // never refresh faster than this
#define TRACK_STABLE_MS       2500   // song must survive this long to be drawn
                                     // (skip-storms never touch the panel)

// ---------- Spotify polling ----------
#define POLL_ACTIVE_MS   5000
#define POLL_IDLE_MS     5000    // how fast music is noticed when nothing's on
                                 // (kept snappy so Now Playing appears promptly)

// ---------- live synced lyrics (LrcLib) ----------
// A single current line, centered under the album art, advanced in time with the
// song. Each line change uses a masked clean refresh over the lower live
// Now-Playing region: the lyric and timer strips are carried through white
// (full-refresh crispness, no ghosting), while the play/pause and skip controls
// are preserved from the canvas. Timer-only ticks still use the small bottom
// strip and only advance on the configured cadence. See lyrics.cpp and
// epdPushLyric() in epaper.cpp for why the clean path is mandatory on this panel.
#define LYRIC_BAND_X    0
#define LYRIC_BAND_Y    199
#define LYRIC_BAND_W    400
#define LYRIC_BAND_H    36
#define NP_LIVE_STRIP_X 0
#define NP_LIVE_STRIP_Y LYRIC_BAND_Y
#define NP_LIVE_STRIP_W 400
#define NP_LIVE_STRIP_H (300 - LYRIC_BAND_Y)
#define NP_BAR_STRIP_X  0
#define NP_BAR_STRIP_Y  266
#define NP_BAR_STRIP_W  400
#define NP_BAR_STRIP_H  34

#define LYRIC_MIN_GAP_MS        900      // min ms between clean strip repaints
#define LYRIC_FETCH_TIMEOUT_MS  8000     // body-read cap (matches the Spotify client;
                                         // 3s was too short to read a ~10KB TLS body and
                                         // the parse timed out -> "no lyrics")
#define LYRIC_MAX_LINES         240      // hard bound on stored lines
#define LYRIC_BUF_BYTES         12288    // PSRAM text buffer for one song's lyrics
#define DEF_LYRIC_LEAD_MS       1100     // paint this early so the e-ink transition
                                         // finishes at the lyric timestamp
#define LYRIC_MAX_TRIES         3        // fetch attempts before giving up (backoff)
#define LYRIC_RETRY_MS          10000    // wait between failed fetch attempts
#define LYRIC_USER_AGENT        "GraceFrame/1.0 (https://github.com/graceframe)"

// ---------- network ----------
#define MDNS_NAME        "graceframe"   // app lives at http://graceframe.local
#define AP_NAME          "GraceFrame-Setup"

// ---------- e-paper wiring (ESP32-S3) ----------
#define EPD_CS    10
#define EPD_DC    11
#define EPD_RST   12
#define EPD_BUSY  13
#define EPD_SCK   14
#define EPD_MOSI  21

// ---------- panel ----------
// Waveshare 4.2" V2 (SSD1683 / GDEY042T81) is the default.
// If the screen stays blank or scrambled, comment the first line and
// uncomment the second (older UC8176 / GDEW042T2 panel).
#define PANEL_GDEY042T81
// #define PANEL_GDEW042T2

#define SCREEN_W 400
#define SCREEN_H 300
