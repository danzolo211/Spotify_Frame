#include "epaper.h"
#include <SPI.h>
#include <GxEPD2_BW.h>

GFXcanvas1 canvas(SCREEN_W, SCREEN_H);

#if defined(PANEL_GDEY042T81)
static GxEPD2_BW<GxEPD2_420_GDEY042T81, GxEPD2_420_GDEY042T81::HEIGHT>
  display(GxEPD2_420_GDEY042T81(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));
#elif defined(PANEL_GDEW042T2)
static GxEPD2_BW<GxEPD2_420, GxEPD2_420::HEIGHT>
  display(GxEPD2_420(EPD_CS, EPD_DC, EPD_RST, EPD_BUSY));
#else
#error "Pick a panel in config.h"
#endif

static uint16_t partials = 0;
static uint32_t lastFullMs = 0;
static uint32_t lastPushMs = 0;
static uint32_t refreshes = 0;

void epdInit() {
  SPI.begin(EPD_SCK, -1, EPD_MOSI, EPD_CS);
  display.init(115200, true, 2, false);   // short reset pulse for Waveshare
  display.setRotation(0);
  lastFullMs = millis();
}

void epdPush(PushMode mode, int x, int y, int w, int h) {
  // rate limit — protects the panel from anything pathological
  uint32_t since = millis() - lastPushMs;
  if (lastPushMs != 0 && since < MIN_REFRESH_GAP_MS) {
    delay(MIN_REFRESH_GAP_MS - since);
  }
  // upgrade to a clean full refresh when the budget says so
  if (mode != PUSH_FULL &&
      (partials >= PARTIALS_BEFORE_FULL ||
       millis() - lastFullMs >= FULL_EVERY_MS)) {
    mode = PUSH_FULL;
  }
  // canvas: bit 1 = ink; GxEPD2 buffer: bit 1 = white  -> invert
  const uint8_t* buf = canvas.getBuffer();
  display.writeImage(buf, 0, 0, SCREEN_W, SCREEN_H, true);   // -> "current" RAM
  switch (mode) {
    case PUSH_FULL:
      display.refresh(false);
      partials = 0;
      lastFullMs = millis();
      break;
    case PUSH_FAST:
      display.refresh(true);
      partials++;
      break;
    case PUSH_REGION:
      display.refresh(x, y, w, h);
      partials++;
      break;
  }
  // Copy what's now on the glass into the panel's "previous" RAM bank. This
  // panel (SSD1683) computes a partial refresh as the transition previous->
  // current; without syncing it here, the next partial diffs against stale RAM
  // and ghosts — that's what jumbled the progress digits and doubled the
  // play/pause icon.
  display.epd2.writeImageToPrevious(buf, 0, 0, SCREEN_W, SCREEN_H, true);
  // powerOff (NOT hibernate): stops the panel driving voltage to prevent
  // fading, but KEEPS the RAM. hibernate() deep-sleeps + resets on next use,
  // which would wipe the baseline we just set and bring the ghosting back.
  display.epd2.powerOff();
  lastPushMs = millis();
  refreshes++;
}

uint32_t epdRefreshCount() { return refreshes; }
