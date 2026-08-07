#include "spotify.h"
#include "secrets.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <TJpg_Decoder.h>
#include <Preferences.h>
#include "mbedtls/base64.h"

static String clientId, clientSecret, refreshToken;
static String accessToken;
static uint32_t tokenExpiresAt = 0;
static uint32_t cooldownUntil = 0;
static int linkState = SP_LINK_UNKNOWN;

static bool refreshAccessToken();   // fwd decl (spotifySetCreds verifies now)

static uint8_t* gray = nullptr;      // ART_PX^2 grayscale work buffer
static uint8_t* artBits = nullptr;   // packed 1bpp result
static int artOffX = 0, artOffY = 0;

static void* bigAlloc(size_t n) {
  void* p = ps_malloc(n);
  if (!p) p = malloc(n);
  return p;
}

static String b64(const String& in) {
  size_t olen = 0, need = 4 * ((in.length() + 2) / 3) + 1;
  unsigned char* out = (unsigned char*)malloc(need);
  mbedtls_base64_encode(out, need, &olen,
                        (const unsigned char*)in.c_str(), in.length());
  String r = String((char*)out).substring(0, olen);
  free(out);
  return r;
}

void spotifyBegin() {
  gray = (uint8_t*)bigAlloc(ART_PX * ART_PX);
  artBits = (uint8_t*)bigAlloc(ART_PX * ART_PX / 8);
  if (artBits) memset(artBits, 0, ART_PX * ART_PX / 8);
  Preferences p;
  p.begin("gf", true);
  clientId = p.getString("sp_id", SP_CLIENT_ID);
  clientSecret = p.getString("sp_secret", SP_CLIENT_SECRET);
  refreshToken = p.getString("sp_refresh", SP_REFRESH_TOKEN);
  p.end();
}

bool spotifyConfigured() {
  return clientId.length() > 10 && refreshToken.length() > 10;
}

int spotifyLinkState() {
  if (!spotifyConfigured()) return SP_LINK_NONE;
  return linkState;
}

void spotifySetCreds(const String& id, const String& secret,
                     const String& refresh) {
  Preferences p;
  p.begin("gf", false);
  if (id.length()) { p.putString("sp_id", id); clientId = id; }
  if (secret.length()) { p.putString("sp_secret", secret); clientSecret = secret; }
  if (refresh.length()) { p.putString("sp_refresh", refresh); refreshToken = refresh; }
  p.end();
  accessToken = "";
  tokenExpiresAt = 0;
  linkState = SP_LINK_UNKNOWN;
  // Verify right away so the app can say "linked ✓" or "credentials rejected"
  // within a moment of her pressing Save — no waiting for the next poll.
  if (spotifyConfigured()) refreshAccessToken();
}

uint32_t spotifyCooldownMs() {
  int32_t left = (int32_t)(cooldownUntil - millis());
  return left > 0 ? (uint32_t)left : 0;
}

static bool refreshAccessToken() {
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(8000);
  http.begin(client, "https://accounts.spotify.com/api/token");
  http.addHeader("Content-Type", "application/x-www-form-urlencoded");
  http.addHeader("Authorization",
                 "Basic " + b64(clientId + ":" + clientSecret));
  int code = http.POST("grant_type=refresh_token&refresh_token=" + refreshToken);
  if (code != 200) {
    Serial.printf("spotify token HTTP %d\n", code);
    http.end();
    // 400/401 mean Spotify actively rejected the id/secret/refresh token —
    // that's a "wrong credentials" state the app should surface. Other codes
    // (5xx, -1 connection) are transient; leave the state unknown, don't accuse.
    if (code == 400 || code == 401) linkState = SP_LINK_FAILED;
    return false;
  }
  JsonDocument doc;
  DeserializationError e = deserializeJson(doc, http.getString());
  http.end();
  if (e) return false;               // transient parse hiccup — don't mark failed
  accessToken = doc["access_token"].as<String>();
  tokenExpiresAt = millis() + (uint32_t)(doc["expires_in"] | 3600) * 1000UL - 60000UL;
  if (accessToken.length() > 0) { linkState = SP_LINK_OK; return true; }
  linkState = SP_LINK_FAILED;        // 200 but no token — treat as bad creds
  return false;
}

static void ensureToken() {
  if (accessToken.length() == 0 || (int32_t)(millis() - tokenExpiresAt) >= 0)
    refreshAccessToken();
}

int spotifyPoll(Track& t) {
  if (!spotifyConfigured()) return SP_ERROR;
  if (spotifyCooldownMs() > 0) return SP_COOLDOWN;   // rollover-safe cooldown
  ensureToken();
  if (!accessToken.length()) return SP_ERROR;

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(8000);
  const char* retryAfter[] = { "Retry-After" };
  http.collectHeaders(retryAfter, 1);
  http.begin(client, "https://api.spotify.com/v1/me/player/currently-playing");
  http.addHeader("Authorization", "Bearer " + accessToken);
  int code = http.GET();
  if (code == 204) { http.end(); return SP_IDLE; }
  if (code == 429) {
    long wait = http.header("Retry-After").toInt();
    cooldownUntil = millis() + (wait > 0 ? wait : 30) * 1000UL;
    http.end();
    Serial.printf("spotify 429, cooling %lds\n", wait);
    return SP_COOLDOWN;
  }
  if (code == 401) { accessToken = ""; http.end(); return SP_ERROR; }
  if (code != 200) {
    Serial.printf("spotify HTTP %d\n", code);
    http.end();
    return SP_ERROR;
  }

  // filter: the raw payload is huge (available_markets etc.)
  JsonDocument filter;
  filter["is_playing"] = true;
  filter["progress_ms"] = true;
  filter["item"]["id"] = true;
  filter["item"]["name"] = true;
  filter["item"]["duration_ms"] = true;
  filter["item"]["artists"][0]["name"] = true;
  filter["item"]["album"]["images"][0]["url"] = true;
  filter["item"]["album"]["images"][0]["width"] = true;

  JsonDocument doc;
  DeserializationError e =
      deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (e) return SP_ERROR;
  if (doc["item"].isNull()) return SP_IDLE;

  t.id = doc["item"]["id"].as<String>();
  t.playing = doc["is_playing"].as<bool>();
  t.progress = doc["progress_ms"].as<long>();
  t.duration = doc["item"]["duration_ms"].as<long>();
  t.title = doc["item"]["name"].as<String>();
  t.artist = "";
  for (JsonObject a : doc["item"]["artists"].as<JsonArray>()) {
    if (t.artist.length()) t.artist += ", ";
    t.artist += a["name"].as<String>();
    if (t.artist.length() > 60) break;
  }
  t.artUrl = "";
  for (JsonObject img : doc["item"]["album"]["images"].as<JsonArray>()) {
    t.artUrl = img["url"].as<String>();       // widest first...
    if (img["width"].as<int>() <= 320) break; // ...stop at ~300px
  }
  return SP_OK;
}

// ------------------------------------------------------------- album art
static bool jpgToGray(int16_t x, int16_t y, uint16_t w, uint16_t h, uint16_t* bmp) {
  for (int j = 0; j < h; j++)
    for (int i = 0; i < w; i++) {
      int px = x + i + artOffX, py = y + j + artOffY;
      if (px < 0 || py < 0 || px >= ART_PX || py >= ART_PX) continue;
      uint16_t c = bmp[j * w + i];
      uint8_t r = ((c >> 11) & 0x1F) << 3;
      uint8_t g = ((c >> 5) & 0x3F) << 2;
      uint8_t b = (c & 0x1F) << 3;
      gray[py * ART_PX + px] = (uint8_t)((r * 30 + g * 59 + b * 11) / 100);
    }
  return true;
}

static void ditherArt() {          // Floyd-Steinberg -> 1bpp, bit1 = black
  memset(artBits, 0, ART_PX * ART_PX / 8);
  for (int y = 0; y < ART_PX; y++)
    for (int x = 0; x < ART_PX; x++) {
      int idx = y * ART_PX + x;
      int old = gray[idx];
      int nw = (old < 128) ? 0 : 255;
      int err = old - nw;
      if (nw == 0) artBits[idx >> 3] |= (0x80 >> (idx & 7));
      if (x + 1 < ART_PX)
        gray[idx + 1] = constrain(gray[idx + 1] + err * 7 / 16, 0, 255);
      if (x > 0 && y + 1 < ART_PX)
        gray[idx + ART_PX - 1] = constrain(gray[idx + ART_PX - 1] + err * 3 / 16, 0, 255);
      if (y + 1 < ART_PX)
        gray[idx + ART_PX] = constrain(gray[idx + ART_PX] + err * 5 / 16, 0, 255);
      if (x + 1 < ART_PX && y + 1 < ART_PX)
        gray[idx + ART_PX + 1] = constrain(gray[idx + ART_PX + 1] + err * 1 / 16, 0, 255);
    }
}

static bool downloadJpeg(const String& url, uint8_t** buf, size_t* len) {
  *buf = nullptr;
  *len = 0;
  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(8000);
  if (!http.begin(client, url)) return false;
  if (http.GET() != 200) { http.end(); return false; }
  int sz = http.getSize();
  if (sz <= 0) sz = 90000;
  uint8_t* b = (uint8_t*)bigAlloc(sz);
  if (!b) { http.end(); return false; }
  WiFiClient* s = http.getStreamPtr();
  size_t got = 0;
  uint32_t t0 = millis();
  while (http.connected() && got < (size_t)sz && millis() - t0 < 8000) {
    size_t a = s->available();
    if (a) {
      got += s->readBytes(b + got, min(a, (size_t)sz - got));
      t0 = millis();
    } else delay(2);
  }
  http.end();
  if (got <= 100) { free(b); return false; }   // free on failure — was a leak
  *buf = b;
  *len = got;
  return true;
}

bool spotifyFetchArt(const String& url) {
  if (!gray || !artBits || !url.length()) return false;
  memset(gray, 255, ART_PX * ART_PX);
  uint8_t* jpg = nullptr;
  size_t jlen = 0;
  if (!downloadJpeg(url, &jpg, &jlen)) return false;

  uint16_t jw = 0, jh = 0;
  TJpgDec.getJpgSize(&jw, &jh, jpg, jlen);
  uint8_t scale = 1;
  while (jw / scale > ART_PX && scale < 8) scale *= 2;
  artOffX = (ART_PX - jw / scale) / 2;
  artOffY = (ART_PX - jh / scale) / 2;
  TJpgDec.setJpgScale(scale);
  TJpgDec.setCallback(jpgToGray);
  TJpgDec.drawJpg(0, 0, jpg, jlen);
  free(jpg);
  ditherArt();
  return true;
}

const uint8_t* spotifyArtBits() { return artBits; }
