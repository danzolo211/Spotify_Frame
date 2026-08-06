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
// Keep messages warm and encouraging. Uncomment / add your own.
struct SpecialDate {
  uint8_t month, day;
  const char* title;
  const char* message;
};
static const SpecialDate SPECIAL_DATES[] = {
  { 1,  1, "Happy New Year",   "A fresh page, and grace for every line of it." },
  { 7, 10, "The Day We Met",   "I'm so grateful for the day we met!! I was never the same since." },
  { 8, 15, "Happy Birthday!",  "The world shown a little brighter since the day you were born." },
};


// POSIX timezone string (default: US Eastern).
// Central: "CST6CDT,M3.2.0,M11.1.0"  Mountain: "MST7MDT,M3.2.0,M11.1.0"
// Pacific: "PST8PDT,M3.2.0,M11.1.0"  Arizona:  "MST7"
#define TIMEZONE        "EST5EDT,M3.2.0,M11.1.0"

// ---------- behavior defaults (all changeable live in the app) ----------
#define DEF_VERSE_MIN    20   // minutes between verses
#define DEF_IDLE_MIN     3    // minutes of Spotify silence before verses return
#define DEF_PROGRESS_S   10   // progress-bar update seconds (0 = frozen bar).
                              // The elapsed time is interpolated locally between
                              // Spotify polls, so it stays truthful even though
                              // the panel only repaints the bar this often.
                              // (Also changeable live in the app's Settings.)
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
#define POLL_IDLE_MS     15000   // how fast music is noticed when nothing's on

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
