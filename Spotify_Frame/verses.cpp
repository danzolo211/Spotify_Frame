#include "verses.h"
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <time.h>

static uint32_t* offsets = nullptr;
static uint32_t nVerses = 0;
static uint8_t* favBits = nullptr;
static uint32_t favBytes = 0;
static String translation = "NIV";

#define RECENT_N 60
static int recent[RECENT_N];
static int recentPos = 0;

#define HIST_N 24
static HistEntry hist[HIST_N];
static int histCount = 0;

static void* bigAlloc(size_t n) {
  void* p = ps_malloc(n);
  if (!p) p = malloc(n);
  return p;
}

bool versesBegin() {
  File idx = LittleFS.open("/verses.idx", "r");
  if (!idx) {
    Serial.println("verses.idx missing — run tools/fetch_verses.py + upload data");
    return false;
  }
  idx.read((uint8_t*)&nVerses, 4);
  if (nVerses == 0 || nVerses > 20000) { idx.close(); return false; }
  offsets = (uint32_t*)bigAlloc(nVerses * 4);
  idx.read((uint8_t*)offsets, nVerses * 4);
  idx.close();

  favBytes = (nVerses + 7) / 8;
  favBits = (uint8_t*)bigAlloc(favBytes);
  memset(favBits, 0, favBytes);
  File ff = LittleFS.open("/favs.bin", "r");
  if (ff) { ff.read(favBits, min((uint32_t)ff.size(), favBytes)); ff.close(); }

  for (int i = 0; i < RECENT_N; i++) recent[i] = -1;
  File mf = LittleFS.open("/verses_meta.json", "r");
  if (mf) {
    JsonDocument doc;
    if (!deserializeJson(doc, mf)) translation = doc["translation"].as<String>();
    mf.close();
  }
  Serial.printf("verses: %u loaded (%s)\n", nVerses, translation.c_str());
  return true;
}

int versesCount() { return (int)nVerses; }
String versesTranslation() { return translation; }

bool versesGet(int id, Verse& out) {
  if (id < 0 || (uint32_t)id >= nVerses) return false;
  File f = LittleFS.open("/verses.jsonl", "r");
  if (!f) return false;
  f.seek(offsets[id]);
  String line = f.readStringUntil('\n');
  f.close();
  JsonDocument doc;
  if (deserializeJson(doc, line)) return false;
  out.id = id;
  out.ref = doc["r"].as<String>();
  out.text = doc["t"].as<String>();
  out.cat = doc["c"].as<String>();
  return true;
}

static bool isRecent(int id) {
  for (int i = 0; i < RECENT_N; i++)
    if (recent[i] == id) return true;
  return false;
}

bool versesIsFav(int id) {
  if (id < 0 || (uint32_t)id >= nVerses) return false;
  return favBits[id >> 3] & (1 << (id & 7));
}

void versesSetFav(int id, bool fav) {
  if (id < 0 || (uint32_t)id >= nVerses) return;
  if (fav) favBits[id >> 3] |= (1 << (id & 7));
  else     favBits[id >> 3] &= ~(1 << (id & 7));
  File f = LittleFS.open("/favs.bin", "w");
  if (f) { f.write(favBits, favBytes); f.close(); }
}

int versesFavCount() {
  int n = 0;
  for (uint32_t i = 0; i < nVerses; i++)
    if (favBits[i >> 3] & (1 << (i & 7))) n++;
  return n;
}

int versesFavAt(int want) {
  int n = 0;
  for (uint32_t i = 0; i < nVerses; i++)
    if (favBits[i >> 3] & (1 << (i & 7))) {
      if (n == want) return (int)i;
      n++;
    }
  return -1;
}

int versesPickRandom(const String& cat) {
  if (nVerses == 0) return -1;
  int favCount = versesFavCount();
  // favorites get a strong say
  if (favCount > 0 && (int)random(100) < 25) {
    for (int tries = 0; tries < 12; tries++) {
      int id = versesFavAt(random(favCount));
      if (id >= 0 && !isRecent(id)) {
        if (cat.length()) {
          Verse v;
          if (!versesGet(id, v) || v.cat != cat) continue;
        }
        return id;
      }
    }
  }
  for (int tries = 0; tries < 240; tries++) {
    int id = random(nVerses);
    if (isRecent(id)) continue;
    if (cat.length()) {
      Verse v;
      if (!versesGet(id, v) || v.cat != cat) continue;
    }
    return id;
  }
  return random(nVerses);   // library nearly exhausted — anything goes
}

void versesHistoryAdd(int id) {
  recent[recentPos] = id;
  recentPos = (recentPos + 1) % RECENT_N;
  // shift history (newest first)
  for (int i = min(histCount, HIST_N - 1); i > 0; i--) hist[i] = hist[i - 1];
  hist[0] = { id, time(nullptr) };
  if (histCount < HIST_N) histCount++;
}

const HistEntry* versesHistory(int& n) {
  n = histCount;
  return hist;
}
