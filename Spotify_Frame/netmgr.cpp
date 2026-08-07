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
  WiFi.setAutoReconnect(true);   // SDK also rejoins on its own after a drop
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
<html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>GraceFrame Setup</title><style>
body{font-family:Georgia,serif;background:#f6f1e7;color:#2b2620;margin:0;
display:flex;justify-content:center}main{max-width:380px;padding:28px 22px}
h1{font-size:26px;margin:10px 0 2px}p{color:#6b6156;line-height:1.45}
label{display:block;margin:16px 0 6px;font-weight:bold}
input{width:100%;padding:12px;font-size:16px;border:1px solid #c9bda8;
border-radius:10px;background:#fffdf8;box-sizing:border-box}
button{margin-top:22px;width:100%;padding:14px;font-size:17px;border:0;
border-radius:12px;background:#2b2620;color:#f6f1e7}
.cross{font-size:30px}.hint{font-size:14px;color:#8a7f70;margin-top:18px}
.show{font-weight:normal;font-size:14px;color:#6b6156;margin-top:8px}
.show input{width:auto;margin-right:6px;vertical-align:middle}</style></head>
<body><main>
<div class=cross>&#10013;&#65039;</div>
<h1>GraceFrame</h1><p>Choose your home Wi-Fi so the frame can connect.</p>
<form method=POST action=/save onsubmit="return !!this.ssid.value.trim()">
<label>Network name</label>
<input name=ssid list=nets placeholder="Your Wi-Fi name" autocomplete=off
 autocapitalize=off autocorrect=off spellcheck=false required>
<datalist id=nets>%OPTIONS%</datalist>
<label>Password</label>
<input id=pw name=pass type=password placeholder="Wi-Fi password"
 autocomplete=off autocapitalize=off autocorrect=off spellcheck=false>
<label class=show><input type=checkbox onchange="pw.type=this.checked?'text':'password'">Show password</label>
<button>Save &amp; Connect</button></form>
<p class=hint>Pick your network from the list, or type it (needed for hidden
networks). The frame uses <b>2.4&nbsp;GHz</b> Wi-Fi &mdash; if your network lists
a separate 5&nbsp;GHz name, choose the 2.4&nbsp;GHz one. If this page comes back
after saving, the password was likely mistyped &mdash; just try again.</p>
</main></body></html>)html";

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
    if (n == WIFI_SCAN_FAILED) WiFi.scanNetworks(true);   // kick off another scan
    if (n > 0) {
      options = "";
      for (int i = 0; i < min(n, 20); i++) {
        String s = WiFi.SSID(i);
        if (!s.length() || options.indexOf(">" + s + "<") >= 0) continue;  // skip dupes
        options += "<option value=\"" + s + "\">";        // datalist suggestion
      }
    }
    String page(FPSTR(PORTAL_HTML));
    page.replace("%OPTIONS%", options);                    // may be empty -> type it
    portal.send(200, "text/html", page);
  });
  portal.on("/save", HTTP_POST, [&]() {
    String ssid = portal.arg("ssid");
    ssid.trim();
    if (!ssid.length()) {                                  // never save a blank network
      portal.send(200, "text/html",
                  "<meta name=viewport content='width=device-width,initial-scale=1'>"
                  "<body style='font-family:serif;padding:24px'>"
                  "<h2>Please enter your Wi-Fi name.</h2>"
                  "<p><a href='/'>Go back</a></p></body>");
      return;
    }
    Preferences p;
    p.begin("gf", false);
    p.putString("wifi_ssid", ssid);
    p.putString("wifi_pass", portal.arg("pass"));
    p.end();
    portal.send(200, "text/html",
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<body style='font-family:serif;padding:24px;color:#2b2620'>"
                "<h2>Saved! GraceFrame is connecting…</h2>"
                "<p>If this setup network reappears in a minute, the password was "
                "likely mistyped — rejoin <b>GraceFrame-Setup</b> and try again.</p>"
                "</body>");
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

// After the frame drops and rejoins Wi-Fi (e.g. she reboots her router), the
// mDNS responder needs to be restarted or graceframe.local stops resolving.
void netReannounce() {
  MDNS.end();
  if (MDNS.begin(MDNS_NAME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.printf("mdns: re-announced http://%s.local\n", MDNS_NAME);
  }
}
