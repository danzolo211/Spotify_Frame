/* =====================================================================
   SpotifyFrame.ino  (v2 - reviewed & bug-fixed)
   ESP32-S3  +  Waveshare 4.2" e-paper (400x300 B/W)  Spotify Now-Playing

   FIXES over the first draft:
     [1] Album-art size is now 152 (a multiple of 8). At 150 the 1-bit
         bitmap rows were byte-misaligned -> art printed sheared and read
         past the end of the buffer. 152 makes the packed bitmap exactly
         match what drawBitmap() expects.
     [2] Uses drawBitmap() (exists in Adafruit_GFX) instead of
         drawInvertedBitmap() (does NOT exist -> would fail to compile).
         Our packing sets bit=1 for BLACK = what drawBitmap(...BLACK) wants.
     [3] The /currently-playing JSON is huge (album/track carry a giant
         "available_markets" list). We parse it through an ArduinoJson
         Filter so only needed fields are kept -> low RAM, no reboots.
     [4] Progress bar no longer partial-refreshes every 5 s (ghosting +
         flicker). It moves ~every 20 s, panel hibernates between updates,
         and a clean full refresh happens on each new track.

   LIBRARIES: GxEPD2, Adafruit GFX, ArduinoJson (v7), TJpg_Decoder.
   Board "ESP32S3 Dev Module". Tools: PSRAM="OPI PSRAM", Flash=16MB,
   USB CDC On Boot=Enabled.

   NOTE: this file has your Wi-Fi password and Spotify secret in plain
   text. Keep it private - don't paste it publicly as-is.
   ===================================================================== */

#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <TJpg_Decoder.h>
#include "mbedtls/base64.h"

#include <GxEPD2_BW.h>
#include <Fonts/FreeSansBold12pt7b.h>
#include <Fonts/FreeSansBold9pt7b.h>
#include <Fonts/FreeSans9pt7b.h>

// ========================= 1. CONFIG =================================
const char* WIFI_SSID = "Benelli";
const char* WIFI_PASS = "Deborah16";

const char* SP_CLIENT_ID     = "2f7e6a8183a541f995487860b88ff79d";
const char* SP_CLIENT_SECRET = "4f086d35e1934051b6ebd647667d1a8d";
const char* SP_REFRESH_TOKEN = "AQCr5jaTFlJFN8l4T4QuhQkI16KstZtyi7brPjCA7KgJLKBHGVJTK0Q1_hnyQfAg2mlvQrL9c1Kom1JZszKqTGKC-Hy69yUhY_vDn1VYbaKjLMplgaRdIgx7cpASAgG8kHc";

const uint32_t POLL_MS      = 5000;    // ask Spotify this often (>=4000)
const uint32_t BAR_EVERY_MS = 20000;   // move the progress bar this often
const uint32_t FULL_EVERY_MS= 900000;  // force a clean full refresh (15 min)

// ========================= 2. E-PAPER PINS ==========================
#define EPD_CS   10
#define EPD_DC   11
#define EPD_RST  12
#define EPD_BUSY 13
#define EPD_SCK  14
#define EPD_MOSI 21   // MISO unused (-1)

// ----- Pick the class that matches YOUR panel. -----
// The 4.2" you bought (400x300, B/W, "4 gray") is almost certainly the V2
// (SSD1683 / GDEY042T81) -> line below. If the screen stays BLANK or looks
// scrambled, comment this out and use the older GxEPD2_420 line instead.
GxEPD2_BW<GxEPD2_420_GDEY042T81, GxEPD2_420_GDEY042T81::HEIGHT>
  display(GxEPD2_420_GDEY042T81(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));
// Older V1 (UC8176 / GDEW042T2) alternative:
// GxEPD2_BW<GxEPD2_420, GxEPD2_420::HEIGHT>
//   display(GxEPD2_420(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));

// ========================= 3. LAYOUT ================================
const int ART   = 152;     // album art square (MUST be a multiple of 8)
const int ART_X = 18;
const int ART_Y = 24;
const int TXT_X = ART_X + ART + 16;
const int BAR_Y = 262;
const int BAR_H = 14;
const int BAR_L = 18;
const int BAR_R = 382;

// ========================= 4. STATE =================================
String   accessToken;
uint32_t tokenExpiresAt = 0;
String   lastTrackId    = "";
String   curTitle, curArtist;
long     curProgress = 0, curDuration = 1;
bool     curPlaying  = false;

uint8_t* gray    = nullptr;         // ART*ART grayscale (PSRAM)
uint8_t* artBits = nullptr;         // ART*ART/8 packed 1-bpp (PSRAM)

// ========================= 5. HELPERS ===============================
String b64(const String& in){
  size_t olen=0, need=4*((in.length()+2)/3)+1;
  unsigned char* out=(unsigned char*)malloc(need);
  mbedtls_base64_encode(out,need,&olen,(const unsigned char*)in.c_str(),in.length());
  String r=String((char*)out).substring(0,olen); free(out); return r;
}

void connectWiFi(){
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("Wi-Fi");
  uint32_t t0=millis();
  while (WiFi.status()!=WL_CONNECTED && millis()-t0<20000){ delay(400); Serial.print("."); }
  Serial.println(WiFi.status()==WL_CONNECTED ? " ok "+WiFi.localIP().toString() : " FAILED");
}

bool refreshAccessToken(){
  WiFiClientSecure client; client.setInsecure();
  HTTPClient http;
  http.begin(client, "https://accounts.spotify.com/api/token");
  http.addHeader("Content-Type","application/x-www-form-urlencoded");
  http.addHeader("Authorization","Basic "+b64(String(SP_CLIENT_ID)+":"+SP_CLIENT_SECRET));
  int code=http.POST("grant_type=refresh_token&refresh_token="+String(SP_REFRESH_TOKEN));
  if (code!=200){ Serial.printf("token HTTP %d\n",code); http.end(); return false; }
  JsonDocument doc; deserializeJson(doc, http.getString()); http.end();
  accessToken=doc["access_token"].as<String>();
  tokenExpiresAt=millis()+(uint32_t)doc["expires_in"].as<int>()*1000UL-60000UL;
  Serial.println("token ok");
  return accessToken.length()>0;
}

void ensureToken(){
  if (accessToken.length()==0 || (int32_t)(millis()-tokenExpiresAt)>=0) refreshAccessToken();
}

// returns 1=new track, 0=same, -1=nothing playing, -2=error
int fetchNowPlaying(String& artUrl){
  ensureToken();
  WiFiClientSecure client; client.setInsecure();
  HTTPClient http;
  http.begin(client, "https://api.spotify.com/v1/me/player/currently-playing");
  http.addHeader("Authorization","Bearer "+accessToken);
  int code=http.GET();
  if (code==204){ http.end(); return -1; }
  if (code!=200){ Serial.printf("nowplaying HTTP %d\n",code); http.end(); accessToken=""; return -2; }

  // Keep only the fields we use -> tiny RAM footprint.
  JsonDocument filter;
  filter["is_playing"]=true; filter["progress_ms"]=true;
  filter["item"]["id"]=true; filter["item"]["name"]=true; filter["item"]["duration_ms"]=true;
  filter["item"]["artists"][0]["name"]=true;
  filter["item"]["album"]["images"][0]["url"]=true;
  filter["item"]["album"]["images"][0]["width"]=true;

  JsonDocument doc;
  DeserializationError e=deserializeJson(doc, http.getStream(), DeserializationOption::Filter(filter));
  http.end();
  if (e){ Serial.println("json err"); return -2; }
  if (doc["item"].isNull()) return -1;

  String id  = doc["item"]["id"].as<String>();
  curPlaying = doc["is_playing"].as<bool>();
  curProgress= doc["progress_ms"].as<long>();
  curDuration= doc["item"]["duration_ms"].as<long>();
  curTitle   = doc["item"]["name"].as<String>();
  curArtist  = doc["item"]["artists"][0]["name"].as<String>();

  artUrl="";
  for (JsonObject img : doc["item"]["album"]["images"].as<JsonArray>()){
    artUrl=img["url"].as<String>();
    if (img["width"].as<int>()<=320) break;   // widest first; stop near 300px
  }
  bool isNew=(id!=lastTrackId); lastTrackId=id;
  return isNew?1:0;
}

bool downloadJpeg(const String& url, uint8_t** buf, size_t* len){
  WiFiClientSecure client; client.setInsecure();
  HTTPClient http; http.begin(client, url);
  if (http.GET()!=200){ http.end(); return false; }
  int sz=http.getSize(); if (sz<=0) sz=90000;
  uint8_t* b=(uint8_t*)ps_malloc(sz); if(!b){ http.end(); return false; }
  WiFiClient* s=http.getStreamPtr(); size_t got=0; uint32_t t0=millis();
  while (http.connected() && got<(size_t)sz && millis()-t0<8000){
    size_t a=s->available();
    if (a){ got+=s->readBytes(b+got, min(a,(size_t)sz-got)); t0=millis(); } else delay(2);
  }
  http.end(); *buf=b; *len=got; return got>100;
}

bool jpgToGray(int16_t x,int16_t y,uint16_t w,uint16_t h,uint16_t* bmp){
  for (int j=0;j<h;j++) for (int i=0;i<w;i++){
    int px=x+i,py=y+j; if(px>=ART||py>=ART) continue;
    uint16_t c=bmp[j*w+i];
    uint8_t r=((c>>11)&0x1F)<<3,g=((c>>5)&0x3F)<<2,bl=(c&0x1F)<<3;
    gray[py*ART+px]=(uint8_t)((r*30+g*59+bl*11)/100);
  }
  return true;
}

void ditherArt(){                     // Floyd-Steinberg -> 1bpp, bit=1 is black
  for (int i=0;i<ART*ART/8;i++) artBits[i]=0;
  for (int y=0;y<ART;y++) for (int x=0;x<ART;x++){
    int idx=y*ART+x, old=gray[idx], nw=(old<128)?0:255, err=old-nw;
    if (nw==0) artBits[idx>>3] |= (0x80>>(idx&7));
    if (x+1<ART)             gray[idx+1]     = constrain(gray[idx+1]     +err*7/16,0,255);
    if (x>0 && y+1<ART)      gray[idx+ART-1] = constrain(gray[idx+ART-1] +err*3/16,0,255);
    if (y+1<ART)             gray[idx+ART]   = constrain(gray[idx+ART]   +err*5/16,0,255);
    if (x+1<ART && y+1<ART)  gray[idx+ART+1] = constrain(gray[idx+ART+1] +err*1/16,0,255);
  }
}

bool prepareArt(const String& url){
  memset(gray,255,ART*ART);
  uint8_t* jpg=nullptr; size_t jlen=0;
  if (!downloadJpeg(url,&jpg,&jlen)) return false;
  TJpgDec.setJpgScale(2);             // 300px source -> 150px (fits in 152)
  TJpgDec.setCallback(jpgToGray);
  TJpgDec.drawJpg(0,0,jpg,jlen);
  free(jpg); ditherArt(); return true;
}

// ========================= 6. DRAWING ===============================
String fitText(const String& s,int maxpx){
  int16_t x1,y1; uint16_t w,h; display.getTextBounds(s,0,0,&x1,&y1,&w,&h);
  if (w<=maxpx) return s; String o=s;
  while (o.length()>1){ o.remove(o.length()-1);
    display.getTextBounds(o+"...",0,0,&x1,&y1,&w,&h); if(w<=maxpx) return o+"..."; }
  return o;
}
String mmss(long ms){ long s=ms/1000; char b[10]; sprintf(b,"%ld:%02ld",s/60,s%60); return String(b); }

void drawTransport(int cx,int cy){    // small play/pause glyph like the reference
  if (curPlaying){                     // playing -> pause bars
    display.fillRect(cx-6,cy-7,4,14,GxEPD_BLACK);
    display.fillRect(cx+2,cy-7,4,14,GxEPD_BLACK);
  } else {                             // paused -> play triangle
    display.fillTriangle(cx-5,cy-7,cx-5,cy+7,cx+7,cy,GxEPD_BLACK);
  }
}

void drawStatic(){
  int txtW=BAR_R-TXT_X;
  display.drawBitmap(ART_X,ART_Y,artBits,ART,ART,GxEPD_BLACK);   // fix [2]
  display.setTextColor(GxEPD_BLACK);
  display.setFont(&FreeSansBold12pt7b);
  display.setCursor(TXT_X,ART_Y+34); display.print(fitText(curTitle,txtW));
  display.setFont(&FreeSans9pt7b);
  display.setCursor(TXT_X,ART_Y+64); display.print(fitText(curArtist,txtW));
  drawTransport((BAR_L+BAR_R)/2, BAR_Y-34);
}

void drawBar(){
  float f=curDuration>0?(float)curProgress/curDuration:0; f=constrain(f,0,1);
  display.drawRoundRect(BAR_L,BAR_Y,BAR_R-BAR_L,BAR_H,BAR_H/2,GxEPD_BLACK);
  int fw=(int)((BAR_R-BAR_L-4)*f);
  if (fw>0) display.fillRoundRect(BAR_L+2,BAR_Y+2,fw,BAR_H-4,(BAR_H-4)/2,GxEPD_BLACK);
  display.setFont(&FreeSans9pt7b); display.setTextColor(GxEPD_BLACK);
  display.setCursor(BAR_L,BAR_Y-6); display.print(mmss(curProgress));
  int16_t x1,y1; uint16_t w,h; String t=mmss(curDuration);
  display.getTextBounds(t,0,0,&x1,&y1,&w,&h);
  display.setCursor(BAR_R-w,BAR_Y-6); display.print(t);
}

void fullRender(){
  display.setFullWindow();
  display.firstPage();
  do { display.fillScreen(GxEPD_WHITE); drawStatic(); drawBar(); } while (display.nextPage());
  display.hibernate();
}

void barRefresh(){
  display.setPartialWindow(0,BAR_Y-52,400,BAR_H+58);   // covers bar + glyph + times
  display.firstPage();
  do { display.fillScreen(GxEPD_WHITE); drawTransport((BAR_L+BAR_R)/2,BAR_Y-34); drawBar(); }
  while (display.nextPage());
  display.hibernate();
}

void showMessage(const char* msg){
  display.setFullWindow();
  display.firstPage();
  do { display.fillScreen(GxEPD_WHITE); display.setTextColor(GxEPD_BLACK);
       display.setFont(&FreeSansBold12pt7b); display.setCursor(30,150); display.print(msg); }
  while (display.nextPage());
  display.hibernate();
}

// ========================= 7. SETUP / LOOP ==========================
void setup(){
  Serial.begin(115200); delay(300);
  gray   =(uint8_t*)ps_malloc(ART*ART);
  artBits=(uint8_t*)ps_malloc(ART*ART/8); memset(artBits,0,ART*ART/8);

  SPI.begin(EPD_SCK,-1,EPD_MOSI,EPD_CS);
  display.init(115200,true,2,false);     // "2" = short reset pulse for Waveshare
  display.setRotation(0);                // if image is upside-down, use 2

  showMessage("Connecting...");
  connectWiFi(); refreshAccessToken();
  showMessage("Waiting for Spotify...");
}

void loop(){
  static uint32_t lastPoll=0, lastBar=0, lastFull=0;
  if (WiFi.status()!=WL_CONNECTED) connectWiFi();
  if (millis()-lastPoll < POLL_MS) return;
  lastPoll=millis();

  String artUrl; int r=fetchNowPlaying(artUrl);

  if (r==1){                                   // new track -> full redraw
    if (artUrl.length()) prepareArt(artUrl); else memset(artBits,0,ART*ART/8);
    fullRender(); lastBar=lastFull=millis();
  } else if (r==0){                            // same track
    if (millis()-lastFull >= FULL_EVERY_MS){   // periodic clean refresh
      fullRender(); lastBar=lastFull=millis();
    } else if (millis()-lastBar >= BAR_EVERY_MS){
      barRefresh(); lastBar=millis();
    }
  } else if (r==-1){                           // nothing playing
    if (lastTrackId!="__idle__"){ lastTrackId="__idle__"; showMessage("Nothing playing"); }
  }
}
