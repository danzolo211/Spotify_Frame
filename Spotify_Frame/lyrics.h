#pragma once
#include <Arduino.h>

// Live synced lyrics from LrcLib (https://lrclib.net). Line-level timing only
// (no per-word data); one current line is shown, advanced in time with the song.

enum LyricsState {
  LX_NONE = 0,      // nothing loaded
  LX_LOADING,       // a fetch is scheduled / in flight for the current track
  LX_READY,         // synced lines parsed and available
  LX_INSTRUMENTAL,  // track is instrumental (LrcLib says so)
  LX_UNAVAILABLE    // no synced lyrics found (or gave up after retries)
};

// One timed line. `off` is a byte offset into the module's PSRAM text buffer, so
// storing lyrics costs one big allocation plus this compact array — no per-line
// String churn on the internal heap (which the health guard watches).
struct LyricLine {
  uint32_t time_ms;
  uint16_t off;
};

void lyricsBegin();                 // allocate the text buffer (call once, in setup)
void lyricsClear();                 // drop the current song's lyrics

// Called from commitTrack: remember the new target and schedule a fetch. Does not
// touch the network itself (that happens in lyricsPoll, off the commit's refresh).
void lyricsOnNewTrack(const String& artist, const String& track,
                      const String& album, long durationMs, const String& id);

// Called every loop: performs a scheduled fetch when due (blocks up to
// LYRIC_FETCH_TIMEOUT_MS per request) and applies backoff on failure.
void lyricsPoll();

int  lyricsState();
int  lyricsCount();                    // parsed line count (diagnostics)
int  lyricsLastHttp();                 // last LrcLib HTTP status (diagnostics)
int  lyricsLastLen();                  // last LrcLib body length (diagnostics)
int  lyricsLastContentLength();        // response Content-Length, or -1 if chunked
const char* lyricsLastRoute();         // get+d/get/search/fail, diagnostics
const char* lyricsLastReason();        // compact reason for the last result
int  lyricsActiveIndex(uint32_t ms);   // last line with time_ms <= ms, else -1
uint32_t lyricsLineTimeMs(int idx);    // timestamp for diagnostics/tests
const char* lyricsText(int idx);       // "" if out of range
