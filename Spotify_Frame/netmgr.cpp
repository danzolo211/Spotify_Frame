#include "netmgr.h"
#include "config.h"
#include "secrets.h"
#include "render.h"
#include "epaper.h"

#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>

static bool tryJoin(const String& ssid, const String& pass, uint32_t ms) {
  if (!ssid.length()) return false;
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid.c_str(), pass.c_str());
  Serial.printf("wifi: joining %s", ssid.c_str());
  uint32_t t0 = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t0 < ms) {
    delay(300);
    Serial.print(".");
  }
  Serial.println(WiFi.status() == WL_CONNECTED
                 ? " ok " + WiFi.localIP().toString() : " failed");
  return WiFi.status() == WL_CONNECTED;
}

bool netConnect() {
  Preferences p;
  p.begin("gf", true);
  String ssid = p.getString("wifi_ssid", "");
  String pass = p.getString("wifi_pass", "");
  p.end();
  if (tryJoin(ssid, pass, 20000)) return true;
  return tryJoin(WIFI_SSID, WIFI_PASS, 20000);
}

// ------------------------------------------------------------- portal
static const char PORTAL_HTML[] PROGMEM = R"html(<!doctype html>
<html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>GraceFrame Setup</title><style>
body{font-family:Georgia,serif;background:#f6f1e7;color:#2b2620;margin:0;
display:flex;justify-content:center}main{max-width:380px;padding:28px 22px}
h1{font-size:26px;margin:10px 0 2px}p{color:#6b6156}
label{display:block;margin:16px 0 6px;font-weight:bold}
select,input{width:100%;padding:12px;font-size:16px;border:1px solid #c9bda8;
border-radius:10px;background:#fffdf8;box-sizing:border-box}
button{margin-top:22px;width:100%;padding:14px;font-size:17px;border:0;
border-radius:12px;background:#2b2620;color:#f6f1e7}
.cross{font-size:30px}</style></head><body><main>
<div class=cross>&#10013;&#65039;</div>
<h1>GraceFrame</h1><p>Connect your frame to Wi-Fi.</p>
<form method=POST action=/save>
<label>Network</label><select name=ssid>%OPTIONS%</select>
<label>Password</label><input name=pass type=password placeholder="Wi-Fi password">
<button>Save &amp; Restart</button></form></main></body></html>)html";

void netPortal() {
  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_NAME);
  IPAddress ip = WiFi.softAPIP();
  renderSetup(AP_NAME, "http://" + ip.toString());
  epdPush(PUSH_FULL);

  DNSServer dns;
  dns.start(53, "*", ip);
  WebServer portal(80);

  WiFi.scanNetworks(true);
  String options = "";

  portal.onNotFound([&]() {
    int n = WiFi.scanComplete();
    if (n > 0) {
      options = "";
      for (int i = 0; i < min(n, 20); i++) {
        String s = WiFi.SSID(i);
        if (!s.length()) continue;
        options += "<option>" + s + "</option>";
      }
    }
    if (!options.length())
      options = "<option>" + String(WIFI_SSID) + "</option>";
    String page(FPSTR(PORTAL_HTML));
    page.replace("%OPTIONS%", options);
    portal.send(200, "text/html", page);
  });
  portal.on("/save", HTTP_POST, [&]() {
    Preferences p;
    p.begin("gf", false);
    p.putString("wifi_ssid", portal.arg("ssid"));
    p.putString("wifi_pass", portal.arg("pass"));
    p.end();
    portal.send(200, "text/html",
                "<h2 style='font-family:serif'>Saved! GraceFrame is restarting...</h2>");
    delay(1500);
    ESP.restart();
  });
  portal.begin();
  Serial.println("portal: waiting for setup...");
  while (true) {
    dns.processNextRequest();
    portal.handleClient();
    delay(5);
  }
}

void netTimeMdns() {
  configTzTime(TIMEZONE, "pool.ntp.org", "time.nist.gov", "time.google.com");
  if (MDNS.begin(MDNS_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mdns: http://%s.local\n", MDNS_NAME);
  }
}
