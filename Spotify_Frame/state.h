#pragma once
#include <Arduino.h>

enum Mode : uint8_t { MODE_BOOT, MODE_SPOTIFY, MODE_VERSE, MODE_NOTE, MODE_SPECIAL };

struct Settings {
  uint16_t verseMin;
  uint16_t idleMin;
  uint16_t progressS;
  uint8_t quietStart, quietEnd;
  String herName;
  void load();
  void save();
};

struct NoteState {
  bool active = false;
  String text, from;
  uint32_t until = 0;      // millis deadline; 0 = until dismissed
};

// Actions requested by the web app; executed on the main loop.
struct Pending {
  int showVerseId = -2;    // -2 none, -1 random, >=0 specific
  String verseCat;
  int showBgId = -1;       // pin a background for the current verse
  bool forceRefresh = false;
  bool newNote = false;
  NoteState note;
  bool clearNote = false;
};

struct AppState {
  Mode mode = MODE_BOOT;
  int verseId = -1;
  int bgId = -1;
  uint32_t verseShownAt = 0;
  uint32_t lastMusicActive = 0;
  NoteState note;
  Pending pending;
  bool quiet = false;
  bool specialShownToday = false;
  // last known track (for the app's Now screen)
  String trackTitle, trackArtist, trackId;
  bool trackPlaying = false;
  long trackProgress = 0, trackDuration = 1;
};

extern AppState app;
extern Settings settings;
