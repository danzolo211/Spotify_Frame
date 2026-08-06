#pragma once
#include <Arduino.h>

#define ART_PX 152          // album art square; multiple of 8

struct Track {
  String id, title, artist, artUrl;
  long progress = 0, duration = 1;
  bool playing = false;
};

// poll result
#define SP_OK        0      // track filled in
#define SP_IDLE     -1      // nothing playing / no active device
#define SP_ERROR    -2      // network/auth hiccup (retry later)
#define SP_COOLDOWN -3      // rate limited; wait

void spotifyBegin();
bool spotifyConfigured();
int  spotifyPoll(Track& t);
bool spotifyFetchArt(const String& url);       // fills the art bitmap
const uint8_t* spotifyArtBits();               // ART_PX*ART_PX/8, bit1=black
void spotifySetCreds(const String& id, const String& secret,
                     const String& refresh);   // persisted to flash
uint32_t spotifyCooldownMs();                  // suggested extra wait
