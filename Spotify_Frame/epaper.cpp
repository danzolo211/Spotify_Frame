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

  // byte-align the partial window in x (the panel addresses partial windows on
  // 8-pixel boundaries); harmless for full/fast, used by PUSH_REGION.
  int x0 = x & ~7;
  int x1 = (x + w + 7) & ~7;
  int w0 = x1 - x0;
  if (x0 < 0) x0 = 0;
  if (w0 > SCREEN_W - x0) w0 = SCREEN_W - x0;

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
      display.refresh(x0, y, w0, h);
      partials++;
      break;
  }
  // Sync the panel's "previous" RAM bank so it MIRRORS the glass — no more, no
  // less. This panel (SSD1683) computes a partial refresh as the transition
  // previous->current; the baseline must match what is physically on the glass.
  // A full/fast refresh changed the whole glass, so copy the whole buffer. But
  // a PUSH_REGION only changed ONE window; copying the whole buffer here would
  // tell the panel that areas we never repainted (e.g. the elapsed digits on a
  // bar-only tick) already match the canvas, so the next partial would diff
  // against a baseline that isn't on the glass and ghost — exactly what left
  // the "background" of old digits and jumbled 8 -> 3. Copy just the window we
  // actually refreshed and the baseline stays honest.
  if (mode == PUSH_REGION)
    display.epd2.writeImagePartToPrevious(buf, x0, y, SCREEN_W, SCREEN_H,
                                          x0, y, w0, h, true);
  else
    display.epd2.writeImageToPrevious(buf, 0, 0, SCREEN_W, SCREEN_H, true);
  // powerOff (NOT hibernate): stops the panel driving voltage to prevent
  // fading, but KEEPS the RAM. hibernate() deep-sleeps + resets on next use,
  // which would wipe the baseline we just set and bring the ghosting back.
  display.epd2.powerOff();
  lastPushMs = millis();
  refreshes++;
}

void epdPushRegionClean(int x, int y, int w, int h) {
  uint32_t since = millis() - lastPushMs;
  if (lastPushMs != 0 && since < MIN_REFRESH_GAP_MS) {
    delay(MIN_REFRESH_GAP_MS - since);
  }
  // byte-align x/w for the panel's partial RAM window
  int x0 = x & ~7;
  int x1 = (x + w + 7) & ~7;
  int w0 = x1 - x0;
  if (w0 > SCREEN_W) w0 = SCREEN_W;
  if (h > 100) h = 100;   // this helper is for small strips only

  static uint8_t white[(SCREEN_W / 8) * 100];   // all-white scratch (bit1 = white)
  memset(white, 0xFF, sizeof(white));

  const uint8_t* buf = canvas.getBuffer();

  // Phase 1 — blank the region to white. Set BOTH RAM banks to white so the
  // next transition baselines from a clean white, not the old glyphs.
  display.epd2.writeImage(white, x0, y, w0, h, false);
  display.refresh(x0, y, w0, h);
  display.epd2.writeImageToPrevious(white, x0, y, w0, h, false);

  // Phase 2 — paint the real content, a clean white->content transition.
  display.writeImage(buf, 0, 0, SCREEN_W, SCREEN_H, true);
  display.refresh(x0, y, w0, h);
  // Sync ONLY this window into "previous" (mirror the glass). Writing the whole
  // buffer would poison the baseline for regions we didn't repaint here (e.g.
  // the progress bar), reintroducing ghosting on the next partial elsewhere.
  display.epd2.writeImagePartToPrevious(buf, x0, y, SCREEN_W, SCREEN_H,
                                        x0, y, w0, h, true);

  display.epd2.powerOff();
  partials += 2;
  lastPushMs = millis();
  refreshes += 2;
}

uint32_t epdRefreshCount() { return refreshes; }
