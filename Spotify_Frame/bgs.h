#pragma once
#include <Arduino.h>

#define BG_BYTES 15000   // 400x300 / 8

struct BgInfo {
  String name;
  int16_t zx, zy, zw, zh;   // verse text zone
  bool whiteInk;            // draw the verse in white (night scenes)
  bool night;
  bool special;             // 0 = note frame, 1 = celebration
  String theme;             // optional tag (e.g. "water") for verse affinity
};

bool bgsBegin();
int  bgsCount();
const BgInfo& bgsGet(int i);
bool bgsLoad(int i, uint8_t* buf);            // BG_BYTES, bit 1 = black
int  bgsPickRandom(bool night = false);       // skips specials, avoids repeats
int  bgsPickThemed(const char* theme, bool night);  // matching-theme scene, or -1
int  bgsNoteFrame();                          // index of the note frame
int  bgsCelebration();
