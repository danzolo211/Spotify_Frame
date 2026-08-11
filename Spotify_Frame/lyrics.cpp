#include "lyrics.h"
#include "config.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <esp_heap_caps.h>
#include <algorithm>
#include <ctype.h>
#include <stdlib.h>
#include <string.h>

// ---- storage: PSRAM buffers + a compact timed index ----------------------------
static char*     buf = nullptr;      // final LRC text (lyricsText reads from here)
static size_t    bufCap = 0;
static char*     httpBuf = nullptr;  // raw HTTP body scratch (parsed in place)
static size_t    httpCap = 0;
static LyricLine lines[LYRIC_MAX_LINES];
static int       lineCount = 0;
static int       state = LX_NONE;
static int       g_lastHttp = 0;     // last LrcLib HTTP status (diagnostics)
static int       g_lastLen = 0;      // last LrcLib body length (diagnostics)
static int       g_lastContentLength = 0;
static char      g_lastRoute[12] = "";
static char      g_lastReason[18] = "";

// ---- pending-fetch target + backoff -------------------------------------------
static bool     fetchPending = false;
static uint32_t fetchDueAt = 0;
static int      fetchTries = 0;
static String   tgtArtist, tgtTrack, tgtAlbum, tgtId;
static long     tgtDur = 0;

// A response bigger than this is refused (never read). A /api/get result is ~10KB;
// only a bloated multi-result /api/search exceeds it (rare, since /api/get hits).
static const int    LRC_MAX_BYTES = 45000;
static const size_t LYRIC_HTTP_BYTES = LRC_MAX_BYTES + 2048;

// Route ALL of ArduinoJson's allocations to PSRAM. The internal heap fragments
// badly during a TLS session, so any large-ish INTERNAL allocation (this is why
// HTTPClient::getString() returned "" -> the intermittent len=0) is unreliable.
// PSRAM has 8MB and doesn't fragment like that.
struct PsramAllocator : ArduinoJson::Allocator {
  void* allocate(size_t n) override { void* p = ps_malloc(n); return p ? p : malloc(n); }
  void  deallocate(void* p) override { heap_caps_free(p); }
  void* reallocate(void* p, size_t n) override {
    void* q = heap_caps_realloc(p, n, MALLOC_CAP_SPIRAM);
    return q ? q : realloc(p, n);
  }
};
static PsramAllocator psramAlloc;

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

static String trimmedCopy(String s) {
  s.trim();
  return s;
}

static bool containsIgnoreCase(String s, const char* needle) {
  s.toLowerCase();
  return s.indexOf(needle) >= 0;
}

static void addUnique(String* arr, int& n, int maxN, const String& v) {
  String s = trimmedCopy(v);
  if (!s.length()) return;
  for (int i = 0; i < n; i++)
    if (arr[i].equalsIgnoreCase(s)) return;
  if (n < maxN) arr[n++] = s;
}

static void setDiag(const char* route, const char* reason) {
  strlcpy(g_lastRoute, route ? route : "", sizeof(g_lastRoute));
  strlcpy(g_lastReason, reason ? reason : "", sizeof(g_lastReason));
}

static String withoutTrailingDashInfo(String s) {
  int dash = s.lastIndexOf(" - ");
  if (dash < 0) return trimmedCopy(s);
  String tail = s.substring(dash + 3);
  if (containsIgnoreCase(tail, "remaster") ||
      containsIgnoreCase(tail, "radio edit") ||
      containsIgnoreCase(tail, "single version") ||
      containsIgnoreCase(tail, "album version") ||
      containsIgnoreCase(tail, "mono") ||
      containsIgnoreCase(tail, "stereo") ||
      containsIgnoreCase(tail, "explicit") ||
      containsIgnoreCase(tail, "clean")) {
    return trimmedCopy(s.substring(0, dash));
  }
  return trimmedCopy(s);
}

static String withoutTrailingParenInfo(String s) {
  s = trimmedCopy(s);
  int close = s.endsWith(")") ? s.lastIndexOf(')') : -1;
  int open = close >= 0 ? s.lastIndexOf('(', close) : -1;
  if (open < 0 || close < 0 || close != (int)s.length() - 1) return s;
  String tail = s.substring(open + 1, close);
  if (containsIgnoreCase(tail, "feat") ||
      containsIgnoreCase(tail, "with ") ||
      containsIgnoreCase(tail, "remaster") ||
      containsIgnoreCase(tail, "radio edit") ||
      containsIgnoreCase(tail, "single version") ||
      containsIgnoreCase(tail, "album version") ||
      containsIgnoreCase(tail, "mono") ||
      containsIgnoreCase(tail, "stereo") ||
      containsIgnoreCase(tail, "explicit") ||
      containsIgnoreCase(tail, "clean")) {
    return trimmedCopy(s.substring(0, open));
  }
  return s;
}

static void makeTrackVariants(String* tracks, int& nTracks) {
  addUnique(tracks, nTracks, 4, tgtTrack);
  String noDash = withoutTrailingDashInfo(tgtTrack);
  addUnique(tracks, nTracks, 4, noDash);
  addUnique(tracks, nTracks, 4, withoutTrailingParenInfo(tgtTrack));
  addUnique(tracks, nTracks, 4, withoutTrailingParenInfo(noDash));
}

static void makeArtistVariants(String* artists, int& nArtists) {
  addUnique(artists, nArtists, 3, tgtArtist);
  int comma = tgtArtist.indexOf(',');
  if (comma > 0) addUnique(artists, nArtists, 3, tgtArtist.substring(0, comma));
  int amp = tgtArtist.indexOf(" & ");
  if (amp > 0) addUnique(artists, nArtists, 3, tgtArtist.substring(0, amp));
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

static void parseBufferedLrc() {
  lineCount = 0;
  if (!buf || bufCap == 0) return;

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

static void parseLrc(const char* s) {
  lineCount = 0;
  if (!buf || bufCap == 0 || !s) return;
  size_t n = strlen(s);
  if (n >= bufCap) n = bufCap - 1;
  memcpy(buf, s, n);
  buf[n] = 0;
  parseBufferedLrc();
}

static bool hex4(const char* p, uint16_t& out) {
  uint16_t v = 0;
  for (int i = 0; i < 4; i++) {
    char c = p[i];
    uint8_t n;
    if (c >= '0' && c <= '9') n = c - '0';
    else if (c >= 'a' && c <= 'f') n = c - 'a' + 10;
    else if (c >= 'A' && c <= 'F') n = c - 'A' + 10;
    else return false;
    v = (uint16_t)((v << 4) | n);
  }
  out = v;
  return true;
}

static bool appendUtf8(uint32_t cp, size_t& out) {
  if (!buf || out >= bufCap - 1) return false;
  auto put = [&](uint8_t b) -> bool {
    if (out >= bufCap - 1) return false;
    buf[out++] = (char)b;
    return true;
  };
  if (cp <= 0x7F) return put((uint8_t)cp);
  if (cp <= 0x7FF) return put(0xC0 | (cp >> 6)) && put(0x80 | (cp & 0x3F));
  if (cp <= 0xFFFF) return put(0xE0 | (cp >> 12)) &&
                           put(0x80 | ((cp >> 6) & 0x3F)) &&
                           put(0x80 | (cp & 0x3F));
  return put(0xF0 | (cp >> 18)) &&
         put(0x80 | ((cp >> 12) & 0x3F)) &&
         put(0x80 | ((cp >> 6) & 0x3F)) &&
         put(0x80 | (cp & 0x3F));
}

// Pull a JSON string field directly out of the response body, decoding escapes
// into `buf`. This avoids allocating/parsing a giant /api/search array, and it
// also survives a capped search body as long as the first complete syncedLyrics
// string is inside the cap.
static int extractStringFieldToBuf(const char* key) {
  if (!httpBuf || !buf || bufCap == 0) return -1;
  char pat[36];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char* p = httpBuf;
  while ((p = strstr(p, pat)) != nullptr) {
    p += strlen(pat);
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p != ':') continue;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (strncmp(p, "null", 4) == 0) { p += 4; continue; }
    if (*p != '"') continue;
    p++;

    size_t out = 0;
    while (*p) {
      unsigned char ch = (unsigned char)*p++;
      if (ch == '"') {
        buf[out] = 0;
        return out > 0 ? 1 : 0;
      }
      if (ch != '\\') {
        if (out >= bufCap - 1) { buf[out] = 0; return 2; }
        buf[out++] = (char)ch;
        continue;
      }
      char esc = *p++;
      if (!esc) break;
      switch (esc) {
        case '"': case '\\': case '/':
          if (out >= bufCap - 1) { buf[out] = 0; return 2; }
          buf[out++] = esc;
          break;
        case 'b':
          if (out < bufCap - 1) buf[out++] = '\b';
          break;
        case 'f':
          if (out < bufCap - 1) buf[out++] = '\f';
          break;
        case 'n':
          if (out < bufCap - 1) buf[out++] = '\n';
          break;
        case 'r':
          if (out < bufCap - 1) buf[out++] = '\r';
          break;
        case 't':
          if (out < bufCap - 1) buf[out++] = '\t';
          break;
        case 'u': {
          uint16_t u1;
          if (!hex4(p, u1)) { buf[out] = 0; return -1; }
          p += 4;
          uint32_t cp = u1;
          if (u1 >= 0xD800 && u1 <= 0xDBFF && p[0] == '\\' && p[1] == 'u') {
            uint16_t u2;
            if (hex4(p + 2, u2) && u2 >= 0xDC00 && u2 <= 0xDFFF) {
              cp = 0x10000UL + (((uint32_t)u1 - 0xD800) << 10) + ((uint32_t)u2 - 0xDC00);
              p += 6;
            }
          }
          if (!appendUtf8(cp, out)) { buf[out] = 0; return 2; }
          break;
        }
        default:
          if (out >= bufCap - 1) { buf[out] = 0; return 2; }
          buf[out++] = esc;
          break;
      }
    }
    buf[out] = 0;
    return -1;  // saw the field, but the capped body ended before the close quote
  }
  return 0;
}

static bool jsonBoolFieldTrue(const char* key) {
  if (!httpBuf) return false;
  char pat[36];
  snprintf(pat, sizeof(pat), "\"%s\"", key);
  const char* p = strstr(httpBuf, pat);
  if (!p) return false;
  p += strlen(pat);
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
  if (*p != ':') return false;
  p++;
  while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
  return strncmp(p, "true", 4) == 0;
}

// Read the response body into the PSRAM scratch buffer (NOT getString(), which
// needs a big contiguous INTERNAL block and returns "" under TLS fragmentation).
static size_t readBody(HTTPClient& http, int clen) {
  if (!httpBuf || httpCap == 0) return 0;
  Stream* st = http.getStreamPtr();
  if (!st) return 0;
  size_t cap = httpCap - 1;
  size_t total = 0;
  uint32_t last = millis();
  while (total < cap) {
    if (clen >= 0 && (int)total >= clen) break;
    int avail = st->available();
    if (avail > 0) {
      size_t n = (size_t)avail;
      if (n > cap - total) n = cap - total;
      int r = st->readBytes((char*)httpBuf + total, n);
      if (r > 0) { total += (size_t)r; last = millis(); }
    } else {
      if (millis() - last > (uint32_t)LYRIC_FETCH_TIMEOUT_MS) break;
      if (!http.connected() && clen < 0) break;
      delay(2);
    }
  }
  httpBuf[total] = 0;
  return total;
}

// One request. Returns: 1 = found synced (parsed into lines), 2 = instrumental,
// 0 = no match here (try the next endpoint), -1 = network/read error (stop+retry).
static int lrcRequest(const String& url, bool isSearch, const char* route) {
  setDiag(route, "start");
  if (WiFi.status() != WL_CONNECTED) { g_lastHttp = -100; setDiag(route, "wifi"); return -1; }
  g_lastLen = 0;
  g_lastContentLength = 0;

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(LYRIC_FETCH_TIMEOUT_MS);
  http.setReuse(false);
  if (!http.begin(client, url)) { g_lastHttp = -101; setDiag(route, "begin"); return -1; }
  http.addHeader("User-Agent", LYRIC_USER_AGENT);
  int code = http.GET();
  g_lastHttp = code;
  if (code != 200) {
    g_lastContentLength = http.getSize();
    http.end();
    Serial.printf("lrc GET -> %d %s\n", code, url.c_str());
    setDiag(route, code == 404 ? "404" : "http");
    if (code == 404) return 0;             // clean no-match -> try next endpoint
    return (code < 0) ? -1 : 0;            // connection error stops; other HTTP -> skip
  }
  int clen = http.getSize();
  g_lastContentLength = clen;
  if (clen > LRC_MAX_BYTES) { http.end(); setDiag(route, "too-big"); return 0; }

  size_t total = readBody(http, clen);
  http.end();
  g_lastLen = (int)total;
  Serial.printf("lrc 200 len=%d %s\n", (int)total, url.c_str());
  if (total == 0) { setDiag(route, "empty"); return -1; }

  int ex = extractStringFieldToBuf("syncedLyrics");
  if (ex > 0) {
    parseBufferedLrc();
    if (lineCount > 0) { setDiag(route, ex == 2 ? "ready-trunc" : "ready"); return 1; }
    setDiag(route, "bad-lrc");
    return 0;
  }
  if (ex < 0) {
    setDiag(route, isSearch ? "partial" : "json-cut");
    return isSearch ? 0 : -1;
  }
  if (jsonBoolFieldTrue("instrumental")) { setDiag(route, "instrumental"); return 2; }
  setDiag(route, "no-sync");
  return 0;
}

// Full fetch attempt. Returns true when RESOLVED (don't retry), false on a
// transient network error (caller backs off and retries).
static bool doFetch() {
  state = LX_LOADING;
  lineCount = 0;
  int result = 0;          // 0 = none yet, 1 = found, 2 = instrumental
  bool netdown = false;

  // album_name is omitted (single vs. album vs. deluxe mismatches 404 constantly).
  // Try exact Spotify strings first, then conservative cleanup variants. A
  // NETWORK failure stops the chain (LrcLib unreachable); a clean 404 just moves
  // to the next endpoint.
  String artists[3];
  String tracks[4];
  int nArtists = 0, nTracks = 0;
  makeArtistVariants(artists, nArtists);
  makeTrackVariants(tracks, nTracks);

  for (int a = 0; a < nArtists && result == 0 && !netdown; a++) {
    for (int tr = 0; tr < nTracks && result == 0 && !netdown; tr++) {
      String get = "https://lrclib.net/api/get?artist_name=" + urlenc(artists[a]) +
                   "&track_name=" + urlenc(tracks[tr]);
    // 1) exact match INCLUDING duration -> best-timed version when it lines up
      if (tgtDur > 0) {
        int r = lrcRequest(get + "&duration=" + String((tgtDur + 500) / 1000), false, "get+d");
        if (r > 0) result = r; else if (r < 0) netdown = true;
      }
    // 2) loose match on artist+track -> LrcLib's best version. Rescues songs whose
    //    Spotify length differs from LrcLib's beyond the exact tolerance (After
    //    Hours, singles/edits) -- a small ~10KB reply.
      if (result == 0 && !netdown) {
        int r = lrcRequest(get, false, "get");
        if (r > 0) result = r; else if (r < 0) netdown = true;
      }
    }
  }
  // 3) fuzzy search, last resort (auto-skips when too big to hold).
  if (result == 0 && !netdown) {
    for (int a = 0; a < nArtists && result == 0 && !netdown; a++) {
      for (int tr = 0; tr < nTracks && result == 0 && !netdown; tr++) {
        int r = lrcRequest("https://lrclib.net/api/search?artist_name=" + urlenc(artists[a]) +
                           "&track_name=" + urlenc(tracks[tr]), true, "search");
        if (r > 0) result = r; else if (r < 0) netdown = true;
      }
    }
  }

  if (result == 0 && netdown) return false;   // unreachable -> retry
  state = (result == 1) ? LX_READY : (result == 2) ? LX_INSTRUMENTAL : LX_UNAVAILABLE;
  Serial.printf("lyrics: '%s' / '%s' -> state=%d lines=%d\n",
                tgtTrack.c_str(), tgtArtist.c_str(), state, lineCount);
  return true;
}

// ------------------------------------------------------------------ public API
static void* psAlloc(size_t n) { void* p = ps_malloc(n); return p ? p : malloc(n); }

void lyricsBegin() {
  buf = (char*)psAlloc(LYRIC_BUF_BYTES);
  bufCap = buf ? LYRIC_BUF_BYTES : 0;
  httpBuf = (char*)psAlloc(LYRIC_HTTP_BYTES);
  httpCap = httpBuf ? LYRIC_HTTP_BYTES : 0;
}

void lyricsClear() {
  lineCount = 0;
  state = LX_NONE;
  fetchPending = false;
  g_lastHttp = 0;
  g_lastLen = 0;
  g_lastContentLength = 0;
  setDiag("", "");
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
int lyricsLastLen() { return g_lastLen; }
int lyricsLastContentLength() { return g_lastContentLength; }
const char* lyricsLastRoute() { return g_lastRoute; }
const char* lyricsLastReason() { return g_lastReason; }

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

uint32_t lyricsLineTimeMs(int idx) {
  if (idx < 0 || idx >= lineCount) return 0;
  return lines[idx].time_ms;
}
