#pragma once
#include <Arduino.h>

struct Verse {
  int id = -1;
  String ref, text, cat;
};

struct HistEntry {
  int id;
  time_t at;
};

bool versesBegin();
int  versesCount();
bool versesGet(int id, Verse& out);
// Weighted random: avoids the last ~60 shown, favorites drawn ~4x as often,
// optional category filter ("" = any).
int  versesPickRandom(const String& cat = "");
bool versesIsFav(int id);
void versesSetFav(int id, bool fav);
int  versesFavCount();
int  versesFavAt(int n);            // n-th favorite id, -1 past end
void versesHistoryAdd(int id);
const HistEntry* versesHistory(int& n);
String versesTranslation();
