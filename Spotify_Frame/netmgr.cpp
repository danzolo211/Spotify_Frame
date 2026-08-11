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
  p.begin("gf", false);                          // read-write: may set/clear flags
  bool force = p.getBool("force_setup", false);
  bool pending = p.getBool("wifi_pending", false);
  String ssid = p.getString("wifi_ssid", "");
  String pass = p.getString("wifi_pass", "");

  if (pending) {
    // Credentials she just entered in setup — test ONLY these. On success, lock
    // them in; on failure, reopen the portal with a clear message instead of
    // silently falling back to the built-in network (which would mask a wrong
    // password and leave the frame on the wrong Wi-Fi).
    p.putBool("wifi_pending", false);
    if (tryJoin(ssid, pass, 18000)) {
      p.putBool("wifi_failed", false);
      p.putBool("force_setup", false);
      p.end();
      return true;
    }
    p.putBool("wifi_failed", true);
    p.putBool("force_setup", true);              // arm the portal to reopen
    p.end();
    return false;
  }

  if (force) { p.end(); return false; }          // "re-run setup" was requested
  p.end();
  if (tryJoin(ssid, pass, 20000)) return true;
  return tryJoin(WIFI_SSID, WIFI_PASS, 20000);   // normal boot: fall back to built-in
}

// Clear the saved network and arm the setup portal for the next boot, so the
// frame comes up in first-time "choose your Wi-Fi" mode. Everything else in
// flash (Spotify link, verses, scenes, favorites, settings) is left untouched.
void netForgetWifi() {
  Preferences p;
  p.begin("gf", false);
  p.remove("wifi_ssid");
  p.remove("wifi_pass");
  p.putBool("force_setup", true);
  p.end();
}

// ------------------------------------------------------------- portal
static const char PORTAL_HTML[] PROGMEM = R"html(<!doctype html>
<html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>GraceFrame Setup</title><style>
*{box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
background:#f6f1e7;color:#2b2620;margin:0;display:flex;justify-content:center}
main{width:100%;max-width:430px;padding:28px 22px 36px}
.mark{font-family:Georgia,serif;font-size:34px;line-height:1;margin-bottom:12px}
h1{font-family:Georgia,serif;font-size:30px;margin:0 0 8px}
p{color:#645a4f;line-height:1.45;margin:0 0 14px}
.steps{background:#fffaf0;border:1px solid #d9cbb5;border-radius:14px;padding:14px 16px;margin:18px 0}
.steps b{color:#2b2620}ol{margin:8px 0 0 20px;padding:0;color:#4f463d;line-height:1.45}
label{display:block;margin:16px 0 6px;font-weight:700;color:#2b2620}
input{width:100%;padding:13px 12px;font-size:17px;border:1px solid #c9bda8;
border-radius:10px;background:#fffdf8}
button{margin-top:22px;width:100%;padding:15px;font-size:17px;font-weight:700;border:0;
border-radius:12px;background:#2b2620;color:#f6f1e7}
.hint{font-size:14px;color:#7c7063;margin-top:18px}
.show{font-weight:500;font-size:14px;color:#645a4f;margin-top:9px}
.show input{width:auto;margin-right:7px;vertical-align:middle}</style></head>
<body><main>
<div class=mark>+</div>
<h1>Connect GraceFrame</h1>
<p>Choose the home Wi-Fi network this frame should use.</p>
%BANNER%
<div class=steps><b>If your iPhone says this network has no Internet, tap
"Use Without Internet".</b><ol>
<li>Pick the home Wi-Fi below.</li>
<li>Enter the Wi-Fi password.</li>
<li>Tap Save &amp; Connect, then watch the frame.</li>
</ol></div>
<form method=POST action=/save onsubmit="return !!this.ssid.value.trim()">
<label>Home Wi-Fi</label>
<input name=ssid list=nets placeholder="Network name" autocomplete=off
 autocapitalize=off autocorrect=off spellcheck=false required>
<datalist id=nets>%OPTIONS%</datalist>
<label>Password</label>
<input id=pw name=pass type=password placeholder="Wi-Fi password"
 autocomplete=off autocapitalize=off autocorrect=off spellcheck=false>
<label class=show><input type=checkbox onchange="pw.type=this.checked?'text':'password'">Show password</label>
<button>Save &amp; Connect</button></form>
<p class=hint>GraceFrame uses 2.4 GHz Wi-Fi. If setup comes back with a red
message, the password probably needs a small fix.</p>
</main></body></html>)html";

void netPortal() {
  // AP_STA (not plain AP) so the one network scan below cannot knock the access
  // point offline. The old code scanned in AP mode AND re-scanned on every
  // captive-portal probe — and each scan briefly tears the SoftAP down, which is
  // what made the phone "connect then nothing", hang on Save, and fail to join.
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);                       // keep the AP responsive to the phone
  WiFi.softAP(AP_NAME, nullptr, 1, 0, 4);     // open, channel 1, up to 4 clients
  delay(300);
  IPAddress ip = WiFi.softAPIP();
  renderSetup(AP_NAME, "http://" + ip.toString());
  epdPush(PUSH_FULL);

  // ONE scan up front to fill the network list, then leave the radio alone for
  // the rest of setup so the AP stays rock-solid while she joins and types.
  String options = "";
  int n = WiFi.scanNetworks();                // synchronous, ~2-4s, done before serving
  for (int i = 0; i < n && i < 20; i++) {
    String s = WiFi.SSID(i);
    if (!s.length() || options.indexOf(">" + s + "<") >= 0) continue;  // skip dupes
    options += "<option value=\"" + s + "\">";
  }
  WiFi.scanDelete();

  // Did the last saved network fail to connect? If so, show a clear banner (one
  // shot) instead of silently looping — so she knows to re-check the password.
  Preferences pf;
  pf.begin("gf", false);
  bool failed = pf.getBool("wifi_failed", false);
  pf.putBool("wifi_failed", false);
  pf.end();

  DNSServer dns;
  dns.start(53, "*", ip);                      // wildcard DNS -> everything is us
  WebServer portal(80);

  auto servePortal = [&]() {
    String page(FPSTR(PORTAL_HTML));
    page.replace("%OPTIONS%", options);        // may be empty -> she can type it
    page.replace("%BANNER%", failed ?
      "<p style=\"background:#f6d9d0;border:1px solid #d9a08e;padding:10px 12px;"
      "border-radius:10px;color:#8a3b28;line-height:1.4\">That Wi-Fi name or "
      "password didn&rsquo;t connect. Please check them (passwords are "
      "case-sensitive) and try again.</p>" : "");
    portal.send(200, "text/html; charset=utf-8", page);
  };
  portal.on("/", HTTP_GET, servePortal);
  // every other URL (the OS captive-detection probes) -> bounce to the portal.
  // A 302 to our root is what makes the "Sign in to network" sheet pop reliably
  // on iOS and Android instead of the browser hanging.
  portal.onNotFound([&]() {
    portal.sendHeader("Location", "http://" + ip.toString() + "/", true);
    portal.send(302, "text/plain", "");
  });
  portal.on("/save", HTTP_POST, [&]() {
    String ssid = portal.arg("ssid");
    ssid.trim();
    if (!ssid.length()) {                                  // never save a blank network
      portal.send(200, "text/html",
                  "<!doctype html><html><head><meta charset=utf-8>"
                  "<meta name=viewport content='width=device-width,initial-scale=1'>"
                  "<style>body{font-family:-apple-system,BlinkMacSystemFont,"
                  "'Segoe UI',sans-serif;background:#f6f1e7;color:#2b2620;"
                  "padding:28px 22px}main{max-width:430px;margin:auto}"
                  "a{color:#2b2620;font-weight:700}</style></head><body><main>"
                  "<h2>Please enter the Wi-Fi name.</h2>"
                  "<p><a href='/'>Go back to setup</a></p></main></body></html>");
      return;
    }
    Preferences p;
    p.begin("gf", false);
    p.putString("wifi_ssid", ssid);
    p.putString("wifi_pass", portal.arg("pass"));
    p.putBool("wifi_pending", true);      // TEST these on the next boot
    p.putBool("force_setup", false);
    p.end();
    portal.send(200, "text/html; charset=utf-8",
                "<!doctype html><html><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<style>*{box-sizing:border-box}body{font-family:-apple-system,"
                "BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f6f1e7;"
                "color:#2b2620;margin:0;padding:28px 22px}main{max-width:430px;"
                "margin:auto}.mark{font-family:Georgia,serif;font-size:34px}"
                "h1{font-family:Georgia,serif;font-size:30px;margin:12px 0 8px}"
                "p{color:#645a4f;line-height:1.45}.box{background:#fffaf0;"
                "border:1px solid #d9cbb5;border-radius:14px;padding:14px 16px;"
                "margin-top:18px}b{color:#2b2620}</style></head><body><main>"
                "<div class=mark>+</div><h1>GraceFrame is connecting</h1>"
                "<p>The frame is testing the home Wi-Fi now. Watch the frame, "
                "not this browser page.</p><div class=box><p><b>If your iPhone "
                "asks about no Internet, tap \"Use Without Internet\".</b></p>"
                "<p>That message is normal because your phone is still on the "
                "temporary GraceFrame-Setup network.</p></div>"
                "<p>If the password worked, the frame will leave setup and show "
                "a verse in a few seconds. If setup opens again with a red "
                "message, re-enter the Wi-Fi password.</p></main></body></html>");
    delay(1200);
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
