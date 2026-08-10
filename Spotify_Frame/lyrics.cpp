#include "lyrics.h"
#include "config.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <algorithm>
#include <ctype.h>
#include <string.h>

// ---- storage: one PSRAM text buffer + a compact timed index (no String churn) --
static char*     buf = nullptr;
static size_t    bufCap = 0;
static LyricLine lines[LYRIC_MAX_LINES];
static int       lineCount = 0;
static int       state = LX_NONE;
static int       g_lastHttp = 0;    // last LrcLib HTTP status (diagnostics)

// ---- pending-fetch target + backoff -------------------------------------------
static bool     fetchPending = false;
static uint32_t fetchDueAt = 0;
static int      fetchTries = 0;
static String   tgtArtist, tgtTrack, tgtAlbum, tgtId;
static long     tgtDur = 0;

// A single LrcLib response bigger than this is refused (never parsed) so the
// internal heap can't spike near the health-guard threshold. The ArduinoJson
// filter already discards everything but syncedLyrics as it streams, so this is
// just a sanity cap — a /api/search hit for a popular track can be tens of KB.
static const int LRC_MAX_BYTES = 120000;

// ------------------------------------------------------------------ helpers
static String urlenc(const String& s) {
  static const char* hex = "0123456789ABCDEF";
  String o;
  o.reserve(s.length() * 3);
  for (size_t i = 0; i < s.length(); i++) {
    uint8_t c = (uint8_t)s[i];
    if (isalnum(c) || c == '-' || c == '_' || c == '.' || c == '~') o += (char)c;
    else { o += '%'; o += hex[c >> 4]; o += hex[c & 0x0F]; }
  }
  return o;
}

// One GET. Returns the HTTP status (or <0 for a network/parse hiccup the caller
// should back off and retry). On 200 fills `synced` / `instrumental`.
static int lrcRequest(const String& url, bool isSearch,
                      String& synced, bool& instrumental) {
  synced = "";
  instrumental = false;
  if (WiFi.status() != WL_CONNECTED) { g_lastHttp = -100; return -1; }

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(LYRIC_FETCH_TIMEOUT_MS);
  http.setTimeout(LYRIC_FETCH_TIMEOUT_MS);
  http.setReuse(false);
  if (!http.begin(client, url)) { g_lastHttp = -101; return -1; }
  http.addHeader("User-Agent", LYRIC_USER_AGENT);
  int code = http.GET();
  g_lastHttp = code;
  Serial.printf("lrc GET -> %d (len %d) %s\n", code, http.getSize(), url.c_str());
  if (code != 200) { http.end(); return code; }        // 404 etc. -> caller decides
  if (http.getSize() > LRC_MAX_BYTES) { http.end(); return 200; }  // too big -> "no lyrics"

  JsonDocument filter;
  if (isSearch) {
    filter[0]["syncedLyrics"] = true;
    filter[0]["instrumental"] = true;
  } else {
    filter["syncedLyrics"] = true;
    filter["instrumental"] = true;
  }
  JsonDocument doc;
  DeserializationError e =
      deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (e) return -2;   // transient parse hiccup

  if (isSearch) {
    for (JsonObject o : doc.as<JsonArray>()) {
      const char* sl = o["syncedLyrics"];
      if (sl && sl[0]) { synced = sl; instrumental = o["instrumental"] | false; break; }
    }
  } else {
    const char* sl = doc["syncedLyrics"];
    if (sl) synced = sl;
    instrumental = doc["instrumental"] | false;
  }
  return 200;
}

// Parse one LRC line: any number of leading [mm:ss.xx] stamps, then the text.
// Metadata tags ([ar:], [ti:], [length:]) have a non-digit first char and are
// skipped; blank-text stamped lines are kept (interludes clear the band).
static void parseOneLine(char* line) {
  uint32_t stamps[24];
  int ns = 0;
  char* p = line;
  for (;;) {
    if (*p != '[') break;
    char* q = p + 1;
    if (!isdigit((unsigned char)*q)) break;
    long mm = 0;
    while (isdigit((unsigned char)*q)) { mm = mm * 10 + (*q - '0'); q++; }
    if (*q != ':') break;
    q++;
    long ss = 0; int sd = 0;
    while (isdigit((unsigned char)*q)) { ss = ss * 10 + (*q - '0'); q++; sd++; }
    if (sd == 0) break;
    long fracMs = 0;
    if (*q == '.' || *q == ':') {
      q++;
      long fv = 0; int fd = 0;
      while (isdigit((unsigned char)*q)) { fv = fv * 10 + (*q - '0'); q++; fd++; }
      if (fd == 1) fracMs = fv * 100;
      else if (fd == 2) fracMs = fv * 10;
      else if (fd >= 3) fracMs = fv;
    }
    if (*q != ']') break;
    q++;
    if (ns < (int)(sizeof(stamps) / sizeof(stamps[0])))
      stamps[ns++] = (uint32_t)(mm * 60000L + ss * 1000L + fracMs);
    p = q;
  }
  if (ns == 0) return;
  while (*p == ' ' || *p == '\t') p++;
  uint16_t off = (uint16_t)(p - buf);
  for (int i = 0; i < ns && lineCount < LYRIC_MAX_LINES; i++) {
    lines[lineCount].time_ms = stamps[i];
    lines[lineCount].off = off;
    lineCount++;
  }
}

static void parseLrc(const String& s) {
  lineCount = 0;
  if (!buf || bufCap == 0) return;
  size_t n = s.length();
  if (n >= bufCap) n = bufCap - 1;
  memcpy(buf, s.c_str(), n);
  buf[n] = 0;

  char* p = buf;
  while (*p && lineCount < LYRIC_MAX_LINES) {
    char* eol = p;
    while (*eol && *eol != '\n' && *eol != '\r') eol++;
    bool more = (*eol != 0);
    *eol = 0;
    parseOneLine(p);
    if (!more) break;
    p = eol + 1;
    while (*p == '\n' || *p == '\r') p++;
  }
  // chorus repeats produce out-of-order stamps — sort so the lookup is monotonic
  std::sort(lines, lines + lineCount,
            [](const LyricLine& a, const LyricLine& b) { return a.time_ms < b.time_ms; });
}

// Full fetch attempt. Returns true when RESOLVED (READY/INSTRUMENTAL/UNAVAILABLE —
// don't retry), false on a transient network/parse error (caller backs off).
static bool doFetch() {
  state = LX_LOADING;
  lineCount = 0;
  String synced;
  bool instrumental = false;

  // /api/get matches on exact metadata; album_name is dropped because single vs.
  // album vs. deluxe/remaster mismatches 404 far too often. artist+track+duration
  // hits reliably for a clean single result; /api/search is the fuzzy fallback.
  String url = "https://lrclib.net/api/get?artist_name=" + urlenc(tgtArtist) +
               "&track_name=" + urlenc(tgtTrack);
  if (tgtDur > 0) url += "&duration=" + String(tgtDur / 1000);

  int code = lrcRequest(url, false, synced, instrumental);
  if (code < 0) return false;                      // network/parse -> retry
  if (code == 404 || (code == 200 && !synced.length() && !instrumental)) {
    // exact match missing (or found but no synced lyrics) -> fuzzy search
    String surl = "https://lrclib.net/api/search?artist_name=" + urlenc(tgtArtist) +
                  "&track_name=" + urlenc(tgtTrack);
    int scode = lrcRequest(surl, true, synced, instrumental);
    if (scode < 0 && code != 200) return false;    // network/parse -> retry
    if (scode == 200) code = 200;
  }
  if (code != 200) state = LX_UNAVAILABLE;
  else if (instrumental && !synced.length()) state = LX_INSTRUMENTAL;
  else if (!synced.length()) state = LX_UNAVAILABLE;
  else { parseLrc(synced); state = (lineCount > 0) ? LX_READY : LX_UNAVAILABLE; }
  Serial.printf("lyrics: '%s' / '%s' -> state=%d lines=%d\n",
                tgtTrack.c_str(), tgtArtist.c_str(), state, lineCount);
  return true;
}

// ------------------------------------------------------------------ public API
void lyricsBegin() {
  buf = (char*)ps_malloc(LYRIC_BUF_BYTES);
  if (!buf) buf = (char*)malloc(LYRIC_BUF_BYTES);
  bufCap = buf ? LYRIC_BUF_BYTES : 0;
}

void lyricsClear() {
  lineCount = 0;
  state = LX_NONE;
  fetchPending = false;
}

void lyricsOnNewTrack(const String& artist, const String& track,
                      const String& album, long durationMs, const String& id) {
  lyricsClear();
  tgtArtist = artist;
  tgtTrack = track;
  tgtAlbum = album;
  tgtDur = durationMs;
  tgtId = id;
  fetchTries = 0;
  fetchPending = true;
  fetchDueAt = millis() + 300;   // let the commit's full refresh settle first
  state = LX_LOADING;
}

void lyricsPoll() {
  if (!fetchPending) return;
  if ((int32_t)(millis() - fetchDueAt) < 0) return;
  fetchPending = false;
  bool resolved = doFetch();
  if (!resolved) {                       // transient failure -> backoff or give up
    if (++fetchTries < LYRIC_MAX_TRIES) {
      fetchPending = true;
      fetchDueAt = millis() + LYRIC_RETRY_MS;
      state = LX_LOADING;
    } else {
      state = LX_UNAVAILABLE;
    }
  }
}

int lyricsState() { return state; }
int lyricsCount() { return lineCount; }
int lyricsLastHttp() { return g_lastHttp; }

int lyricsActiveIndex(uint32_t ms) {
  if (lineCount == 0 || ms < lines[0].time_ms) return -1;
  int lo = 0, hi = lineCount - 1, res = 0;
  while (lo <= hi) {
    int mid = (lo + hi) / 2;
    if (lines[mid].time_ms <= ms) { res = mid; lo = mid + 1; }
    else hi = mid - 1;
  }
  return res;
}

const char* lyricsText(int idx) {
  if (!buf || idx < 0 || idx >= lineCount) return "";
  return buf + lines[idx].off;
}
