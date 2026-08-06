#include "webapi.h"
#include "state.h"
#include "verses.h"
#include "bgs.h"
#include "spotify.h"
#include "epaper.h"
#include "config.h"
#include "util.h"

#include <WebServer.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <time.h>

static WebServer server(80);

static void sendJson(JsonDocument& doc) {
  String out;
  serializeJson(doc, out);
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", out);
}

static void sendOk() {
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", "{\"ok\":true}");
}

static bool readBody(JsonDocument& doc) {
  if (!server.hasArg("plain")) return false;
  return deserializeJson(doc, server.arg("plain")) == DeserializationError::Ok;
}

static const char* modeName(Mode m) {
  switch (m) {
    case MODE_SPOTIFY: return "spotify";
    case MODE_VERSE:   return "verse";
    case MODE_NOTE:    return "note";
    case MODE_SPECIAL: return "special";
    default:           return "boot";
  }
}

// ----------------------------------------------------------- handlers
static void hStatus() {
  JsonDocument doc;
  doc["mode"] = modeName(app.mode);
  doc["quiet"] = app.quiet;

  Verse v;
  if (app.verseId >= 0 && versesGet(app.verseId, v)) {
    JsonObject jv = doc["verse"].to<JsonObject>();
    jv["id"] = v.id;
    jv["ref"] = v.ref;
    jv["text"] = v.text;
    jv["cat"] = v.cat;
    jv["fav"] = versesIsFav(v.id);
  }
  if (app.bgId >= 0) {
    JsonObject jb = doc["bg"].to<JsonObject>();
    jb["i"] = app.bgId;
    jb["name"] = bgsGet(app.bgId).name;
  }
  if (app.mode == MODE_VERSE) {
    uint32_t elapsed = (millis() - app.verseShownAt) / 1000;
    uint32_t total = settings.verseMin * 60U;
    doc["next_verse_s"] = elapsed < total ? total - elapsed : 0;
  }
  JsonObject jt = doc["track"].to<JsonObject>();
  jt["id"] = app.trackId;
  jt["title"] = app.trackTitle;
  jt["artist"] = app.trackArtist;
  jt["playing"] = app.trackPlaying;
  jt["progress"] = app.trackProgress;
  jt["duration"] = app.trackDuration;

  JsonObject jn = doc["note"].to<JsonObject>();
  jn["active"] = app.note.active;
  jn["text"] = app.note.text;
  jn["from"] = app.note.from;

  JsonObject js = doc["settings"].to<JsonObject>();
  js["verse_min"] = settings.verseMin;
  js["idle_min"] = settings.idleMin;
  js["progress_s"] = settings.progressS;
  js["quiet_start"] = settings.quietStart;
  js["quiet_end"] = settings.quietEnd;
  js["her_name"] = settings.herName;

  JsonObject jd = doc["device"].to<JsonObject>();
  jd["rssi"] = WiFi.RSSI();
  jd["heap"] = ESP.getFreeHeap();
  jd["uptime_s"] = millis() / 1000;
  jd["refreshes"] = epdRefreshCount();
  jd["verses"] = versesCount();
  jd["favs"] = versesFavCount();
  jd["bgs"] = bgsCount();
  jd["translation"] = versesTranslation();
  jd["spotify_ok"] = spotifyConfigured();
  time_t now = time(nullptr);
  struct tm tmv;
  localtime_r(&now, &tmv);
  char buf[24];
  strftime(buf, sizeof(buf), "%H:%M", &tmv);
  jd["time"] = buf;
  sendJson(doc);
}

static void hScreen() {
  server.sendHeader("Cache-Control", "no-store");
  server.send_P(200, "application/octet-stream",
                (const char*)canvas.getBuffer(), SCREEN_W * SCREEN_H / 8);
}

static void hVerseNext() {
  JsonDocument doc;
  readBody(doc);
  app.pending.showVerseId = -1;
  app.pending.verseCat = doc["cat"] | "";
  sendOk();
}

static void hVerseShow() {
  JsonDocument doc;
  if (!readBody(doc) || doc["id"].isNull()) {
    server.send(400, "application/json", "{\"err\":\"id required\"}");
    return;
  }
  app.pending.showVerseId = doc["id"].as<int>();
  sendOk();
}

static void hVerses() {
  String q = server.arg("q");
  q.toLowerCase();
  String cat = server.arg("cat");
  bool favOnly = server.arg("fav") == "1";
  int offset = server.arg("offset").toInt();
  int limit = server.arg("limit").toInt();
  if (limit <= 0 || limit > 40) limit = 30;

  JsonDocument doc;
  JsonArray items = doc["items"].to<JsonArray>();
  int matched = 0;

  File f = LittleFS.open("/verses.jsonl", "r");
  if (!f) { server.send(500, "application/json", "{\"err\":\"no data\"}"); return; }
  int id = -1;
  while (f.available()) {
    id++;
    String line = f.readStringUntil('\n');
    if (favOnly && !versesIsFav(id)) continue;
    if (q.length()) {
      String low = line;
      low.toLowerCase();
      if (low.indexOf(q) < 0) continue;
    }
    if (cat.length() && line.indexOf("\"c\":\"" + cat + "\"") < 0) continue;
    if (matched >= offset && matched < offset + limit) {
      JsonDocument vd;
      if (!deserializeJson(vd, line)) {
        JsonObject o = items.add<JsonObject>();
        o["i"] = id;
        o["r"] = vd["r"];
        String t = vd["t"].as<String>();
        if (t.length() > 110) t = t.substring(0, 107) + "...";
        o["s"] = t;
        o["c"] = vd["c"];
        o["f"] = versesIsFav(id);
      }
    }
    matched++;
  }
  f.close();
  doc["total"] = matched;
  doc["offset"] = offset;
  sendJson(doc);
}

static void hVerseGet() {
  Verse v;
  if (!versesGet(server.arg("id").toInt(), v)) {
    server.send(404, "application/json", "{\"err\":\"not found\"}");
    return;
  }
  JsonDocument doc;
  doc["id"] = v.id;
  doc["ref"] = v.ref;
  doc["text"] = v.text;
  doc["cat"] = v.cat;
  doc["fav"] = versesIsFav(v.id);
  sendJson(doc);
}

static void hFav() {
  JsonDocument doc;
  if (!readBody(doc)) { server.send(400, "text/plain", "bad body"); return; }
  versesSetFav(doc["id"].as<int>(), doc["fav"].as<bool>());
  sendOk();
}

static void hHistory() {
  JsonDocument doc;
  JsonArray arr = doc["items"].to<JsonArray>();
  int n;
  const HistEntry* h = versesHistory(n);
  for (int i = 0; i < n; i++) {
    Verse v;
    if (!versesGet(h[i].id, v)) continue;
    JsonObject o = arr.add<JsonObject>();
    o["i"] = v.id;
    o["r"] = v.ref;
    o["at"] = (uint32_t)h[i].at;
    o["f"] = versesIsFav(v.id);
  }
  sendJson(doc);
}

static void hBgs() {
  JsonDocument doc;
  JsonArray arr = doc["items"].to<JsonArray>();
  for (int i = 0; i < bgsCount(); i++) {
    const BgInfo& b = bgsGet(i);
    JsonObject o = arr.add<JsonObject>();
    o["i"] = i;
    o["name"] = b.name;
    o["night"] = b.night;
    o["special"] = b.special;
  }
  doc["current"] = app.bgId;
  sendJson(doc);
}

static void hBgBin() {
  int i = server.arg("i").toInt();
  char path[24];
  snprintf(path, sizeof(path), "/bg/%03d.bin", i);
  File f = LittleFS.open(path, "r");
  if (!f) { server.send(404, "text/plain", "no bg"); return; }
  server.sendHeader("Cache-Control", "max-age=86400");
  server.streamFile(f, "application/octet-stream");
  f.close();
}

static void hBgShow() {
  JsonDocument doc;
  if (!readBody(doc)) { server.send(400, "text/plain", "bad body"); return; }
  app.pending.showBgId = doc["i"].as<int>();
  sendOk();
}

static void hNote() {
  JsonDocument doc;
  if (!readBody(doc) || !doc["text"].as<String>().length()) {
    server.send(400, "application/json", "{\"err\":\"text required\"}");
    return;
  }
  String text = doc["text"].as<String>();
  if (text.length() > 300) text = text.substring(0, 300);
  app.pending.note.text = text;
  app.pending.note.from = doc["from"] | "";
  int minutes = doc["minutes"] | 30;
  app.pending.note.until =
      minutes > 0 ? millis() + (uint32_t)minutes * 60000UL : 0;
  app.pending.newNote = true;
  sendOk();
}

static void hNoteClear() {
  app.pending.clearNote = true;
  sendOk();
}

static void hSettingsGet() {
  JsonDocument doc;
  doc["verse_min"] = settings.verseMin;
  doc["idle_min"] = settings.idleMin;
  doc["progress_s"] = settings.progressS;
  doc["quiet_start"] = settings.quietStart;
  doc["quiet_end"] = settings.quietEnd;
  doc["her_name"] = settings.herName;
  sendJson(doc);
}

static void hSettingsPost() {
  JsonDocument doc;
  if (!readBody(doc)) { server.send(400, "text/plain", "bad body"); return; }
  if (!doc["verse_min"].isNull())
    settings.verseMin = constrain(doc["verse_min"].as<int>(), 2, 240);
  if (!doc["idle_min"].isNull())
    settings.idleMin = constrain(doc["idle_min"].as<int>(), 1, 60);
  if (!doc["progress_s"].isNull())
    settings.progressS = constrain(doc["progress_s"].as<int>(), 0, 120);
  if (!doc["quiet_start"].isNull())
    settings.quietStart = constrain(doc["quiet_start"].as<int>(), 0, 23);
  if (!doc["quiet_end"].isNull())
    settings.quietEnd = constrain(doc["quiet_end"].as<int>(), 0, 23);
  if (!doc["her_name"].isNull())
    settings.herName = doc["her_name"].as<String>();
  settings.save();
  sendOk();
}

static void hSpotifyCreds() {
  JsonDocument doc;
  if (!readBody(doc)) { server.send(400, "text/plain", "bad body"); return; }
  spotifySetCreds(doc["id"] | "", doc["secret"] | "", doc["refresh"] | "");
  sendOk();
}

static void hRefresh() {
  app.pending.forceRefresh = true;
  sendOk();
}

static void hIndex() {
  File f = LittleFS.open("/www/index.html", "r");
  if (!f) {
    server.send(200, "text/html",
                "<h2>GraceFrame is running, but the web app files are missing."
                "<br>Upload the LittleFS data folder.</h2>");
    return;
  }
  server.streamFile(f, "text/html");
  f.close();
}

void webBegin() {
  server.on("/api/status", HTTP_GET, hStatus);
  server.on("/api/screen", HTTP_GET, hScreen);
  server.on("/api/verse/next", HTTP_POST, hVerseNext);
  server.on("/api/verse/show", HTTP_POST, hVerseShow);
  server.on("/api/verses", HTTP_GET, hVerses);
  server.on("/api/verse", HTTP_GET, hVerseGet);
  server.on("/api/fav", HTTP_POST, hFav);
  server.on("/api/history", HTTP_GET, hHistory);
  server.on("/api/bgs", HTTP_GET, hBgs);
  server.on("/api/bg", HTTP_GET, hBgBin);
  server.on("/api/bg/show", HTTP_POST, hBgShow);
  server.on("/api/note", HTTP_POST, hNote);
  server.on("/api/note/clear", HTTP_POST, hNoteClear);
  server.on("/api/settings", HTTP_GET, hSettingsGet);
  server.on("/api/settings", HTTP_POST, hSettingsPost);
  server.on("/api/spotify", HTTP_POST, hSpotifyCreds);
  server.on("/api/refresh", HTTP_POST, hRefresh);
  server.on("/", HTTP_GET, hIndex);
  server.serveStatic("/manifest.json", LittleFS, "/www/manifest.json", "max-age=86400");
  server.serveStatic("/sw.js", LittleFS, "/www/sw.js", "no-store");
  server.serveStatic("/icon.png", LittleFS, "/www/icon.png", "max-age=86400");
  server.serveStatic("/icon-512.png", LittleFS, "/www/icon-512.png", "max-age=86400");
  server.onNotFound(hIndex);   // SPA fallback
  server.begin();
  Serial.println("web: started");
}

void webHandle() {
  server.handleClient();
}
