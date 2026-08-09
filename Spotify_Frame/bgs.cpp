#include "bgs.h"
#include <ArduinoJson.h>
#include <LittleFS.h>

#define MAX_BGS 64
static BgInfo bgs[MAX_BGS];
static int nBgs = 0;
static int noteIdx = 0, celebIdx = 1;

#define BG_RECENT 8
static int bgRecent[BG_RECENT];
static int bgRecentPos = 0;

bool bgsBegin() {
  File f = LittleFS.open("/bg/index.json", "r");
  if (!f) {
    Serial.println("bg/index.json missing — run tools/make_backgrounds.py + upload data");
    return false;
  }
  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, f);
  f.close();
  if (e) return false;
  for (JsonObject o : doc.as<JsonArray>()) {
    if (nBgs >= MAX_BGS) break;
    BgInfo& b = bgs[nBgs];
    b.name = o["name"].as<String>();
    JsonArray z = o["zone"];
    b.zx = z[0]; b.zy = z[1]; b.zw = z[2]; b.zh = z[3];
    b.whiteInk = (strcmp(o["ink"] | "black", "white") == 0);
    b.night = b.special = false;
    b.theme = "";
    for (JsonVariant t : o["tags"].as<JsonArray>()) {
      if (t == "night") b.night = true;
      else if (t == "special") b.special = true;
      else b.theme = t.as<String>();     // e.g. "water" -> verse-theme affinity
    }
    if (b.name == "note-flourish") noteIdx = nBgs;
    if (b.name == "celebration") celebIdx = nBgs;
    nBgs++;
  }
  for (int i = 0; i < BG_RECENT; i++) bgRecent[i] = -1;
  Serial.printf("backgrounds: %d loaded\n", nBgs);
  return nBgs > 0;
}

int bgsCount() { return nBgs; }
const BgInfo& bgsGet(int i) { return bgs[constrain(i, 0, nBgs - 1)]; }
int bgsNoteFrame() { return noteIdx; }
int bgsCelebration() { return celebIdx; }

bool bgsLoad(int i, uint8_t* buf) {
  if (i < 0 || i >= nBgs) return false;
  char path[24];
  snprintf(path, sizeof(path), "/bg/%03d.bin", i);
  File f = LittleFS.open(path, "r");
  if (!f) return false;
  size_t got = f.read(buf, BG_BYTES);
  f.close();
  return got == BG_BYTES;
}

int bgsPickRandom(bool night) {
  for (int tries = 0; tries < 80; tries++) {
    int i = random(nBgs);
    const BgInfo& b = bgs[i];
    if (b.special) continue;
    if (night && !b.night) continue;
    if (!night && b.night && tries < 40) continue;  // night scenes mostly at night
    bool rec = false;
    for (int r = 0; r < BG_RECENT; r++)
      if (bgRecent[r] == i) rec = true;
    if (rec && tries < 60) continue;
    bgRecent[bgRecentPos] = i;
    bgRecentPos = (bgRecentPos + 1) % BG_RECENT;
    return i;
  }
  return 2 % nBgs;
}

// Pick a non-special scene whose theme matches (e.g. a water/wave scene for a
// water verse) at the right day/night polarity; -1 when there is no such scene.
int bgsPickThemed(const char* theme, bool night) {
  for (int tries = 0; tries < 60; tries++) {
    int i = random(nBgs);
    const BgInfo& b = bgs[i];
    if (b.special || b.night != night) continue;
    if (b.theme != theme) continue;
    return i;
  }
  return -1;
}
