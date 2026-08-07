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

// Link/auth state, so the app can honestly show whether her credentials work
// (not just whether something was typed in).
#define SP_LINK_NONE     0   // no credentials entered
#define SP_LINK_OK       1   // Spotify accepted them — a token was obtained
#define SP_LINK_FAILED   2   // Spotify rejected them (wrong id/secret/token)
#define SP_LINK_UNKNOWN  3   // configured but not verified yet (or network down)

void spotifyBegin();
bool spotifyConfigured();
int  spotifyLinkState();     // one of SP_LINK_* above
int  spotifyPoll(Track& t);
bool spotifyFetchArt(const String& url);       // fills the art bitmap
const uint8_t* spotifyArtBits();               // ART_PX*ART_PX/8, bit1=black
void spotifySetCreds(const String& id, const String& secret,
                     const String& refresh);   // persisted to flash
uint32_t spotifyCooldownMs();                  // suggested extra wait
