#pragma once
#include <Arduino.h>
#include "verses.h"

// All render* functions draw into the shared canvas only;
// the caller decides how to push it to the panel.
void renderInit();
void renderVerse(const Verse& v, int bgId);
// true if the verse wraps cleanly into a zone this size (no hard-truncation),
// so the bg picker can keep long verses off the small-canvas scenes
bool renderVerseFits(const String& text, int zw, int zh);
void renderSpotify(const uint8_t* artBits, bool artValid);

// Live lyric line for the Now-Playing screen. renderSetLyric stores the current
// line (empty = blank band; instrumental = a small centered note); renderSpotify
// draws it as part of the full frame, and renderLyricBand repaints ONLY the lyric
// band into the canvas for a partial (epdPushLyric) refresh.
void renderSetLyric(const String& line, bool instrumental);
void renderLyricBand();
void renderNote(const String& text, const String& from);
void renderSpecial(const char* title, const char* msg, const String& forName);
void renderMessage(const String& l1, const String& l2 = "");
void renderSetup(const String& apName, const String& url);
