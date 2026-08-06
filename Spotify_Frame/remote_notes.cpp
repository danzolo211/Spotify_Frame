#include "remote_notes.h"
#include "state.h"
#include "secrets.h"

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <time.h>

#ifndef NOTES_TOPIC
#define NOTES_TOPIC ""
#endif

// How often to check for a new note. Notes are rare and ntfy's poll is cheap,
// but keep it gentle so it never competes with Spotify polling.
static const uint32_t POLL_MS = 12000;

static uint32_t nextPollAt = 0;
static uint32_t sinceUnix = 0;    // only accept messages at/after this time

static bool clockReady() { return time(nullptr) > 1600000000; }

void remoteNotesBegin() {
  nextPollAt = millis() + 5000;   // let Wi-Fi + NTP settle first
  sinceUnix = 0;                  // primed on the first poll once the clock is set
}

void remoteNotesTick() {
  if (sizeof(NOTES_TOPIC) <= 4) return;          // remote notes disabled ("")
  if (WiFi.status() != WL_CONNECTED) return;
  if ((int32_t)(millis() - nextPollAt) < 0) return;
  nextPollAt = millis() + POLL_MS;

  // Prime "since = now" so a reboot never replays hours-old cached notes.
  if (sinceUnix == 0) {
    if (!clockReady()) return;                   // wait for NTP
    sinceUnix = (uint32_t)time(nullptr);
    return;
  }

  String url = String("https://ntfy.sh/") + NOTES_TOPIC +
               "/json?poll=1&since=" + String(sinceUnix);

  WiFiClientSecure client;
  client.setInsecure();
  HTTPClient http;
  http.setConnectTimeout(6000);
  http.setTimeout(8000);
  if (!http.begin(client, url)) return;
  int code = http.GET();
  if (code != 200) { http.end(); return; }
  String payload = http.getString();             // small: a few NDJSON lines
  http.end();

  // ntfy returns one JSON object per line, oldest first. Keep the newest note
  // that carries our payload; apply it once.
  String bestText, bestFrom;
  int bestMinutes = 30;
  uint32_t bestTime = 0;

  int start = 0;
  while (start < (int)payload.length()) {
    int nl = payload.indexOf('\n', start);
    String line = (nl < 0) ? payload.substring(start) : payload.substring(start, nl);
    start = (nl < 0) ? payload.length() : nl + 1;
    line.trim();
    if (!line.length()) continue;

    JsonDocument env;
    if (deserializeJson(env, line)) continue;
    if (String(env["event"] | "") != "message") continue;
    uint32_t mt = env["time"] | 0;

    // Our note travels as a JSON string in the message body.
    JsonDocument body;
    if (deserializeJson(body, String(env["message"] | ""))) continue;
    if ((int)(body["gf"] | 0) != 1) continue;    // marker: ours, not stray traffic
    String text = body["text"] | "";
    if (!text.length()) continue;

    if (mt >= bestTime) {
      bestTime = mt;
      bestText = text;
      bestFrom = body["from"] | "";
      bestMinutes = body["minutes"] | 30;
    }
  }

  if (bestText.length()) {
    if (bestText.length() > 300) bestText = bestText.substring(0, 300);
    app.pending.note.text = bestText;
    app.pending.note.from = bestFrom;
    app.pending.note.until =
        bestMinutes > 0 ? millis() + (uint32_t)bestMinutes * 60000UL : 0;
    app.pending.newNote = true;
    sinceUnix = bestTime + 1;                    // don't replay this one
  }
}
