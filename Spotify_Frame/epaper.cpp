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
static const int CLEAN_MAX_H = 120;
struct CleanRect { int x, y, w, h; };

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

// The two-phase "clean" repaint of a small strip, WITHOUT the rate-limit wait
// and WITHOUT touching the full-refresh budget. Routing changing glyphs through
// white (white->content) is the only way to keep text razor-crisp on this panel;
// timer-only updates use this direct clean path. Callers gate cadence themselves.
static void regionCleanCore(int x, int y, int w, int h) {
  if (w <= 0 || h <= 0) return;
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x >= SCREEN_W || w <= 0) return;
  if (y >= SCREEN_H || h <= 0) return;
  if (w > SCREEN_W - x) w = SCREEN_W - x;
  if (h > SCREEN_H - y) h = SCREEN_H - y;
  if (h > CLEAN_MAX_H) h = CLEAN_MAX_H;   // this helper is for small live regions

  // byte-align x/w for the panel's partial RAM window
  int x0 = x & ~7;
  int x1 = (x + w + 7) & ~7;
  int w0 = x1 - x0;
  if (x0 < 0) x0 = 0;
  if (w0 > SCREEN_W - x0) w0 = SCREEN_W - x0;

  static uint8_t white[(SCREEN_W / 8) * CLEAN_MAX_H];   // all-white scratch (bit1 = white)
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
  lastPushMs = millis();
  refreshes += 2;
}

static void scratchWhiteRect(uint8_t* scratch, int sx, int sy, int sw, int sh,
                             const CleanRect& r) {
  int rx0 = r.x & ~7;
  int rx1 = (r.x + r.w + 7) & ~7;
  int ry0 = r.y;
  int ry1 = r.y + r.h;
  if (rx0 < sx) rx0 = sx;
  if (rx1 > sx + sw) rx1 = sx + sw;
  if (ry0 < sy) ry0 = sy;
  if (ry1 > sy + sh) ry1 = sy + sh;
  if (rx0 >= rx1 || ry0 >= ry1) return;

  int bytesPerRow = sw / 8;
  int startByte = (rx0 - sx) / 8;
  int byteCount = (rx1 - rx0) / 8;
  for (int yy = ry0; yy < ry1; yy++) {
    memset(scratch + (yy - sy) * bytesPerRow + startByte, 0xFF, byteCount);
  }
}

static void regionMaskedCleanCore(int x, int y, int w, int h,
                                  const CleanRect* cleanRects,
                                  int cleanRectCount) {
  if (w <= 0 || h <= 0) return;
  if (x < 0) { w += x; x = 0; }
  if (y < 0) { h += y; y = 0; }
  if (x >= SCREEN_W || w <= 0) return;
  if (y >= SCREEN_H || h <= 0) return;
  if (w > SCREEN_W - x) w = SCREEN_W - x;
  if (h > SCREEN_H - y) h = SCREEN_H - y;
  if (h > CLEAN_MAX_H) h = CLEAN_MAX_H;

  int x0 = x & ~7;
  int x1 = (x + w + 7) & ~7;
  int w0 = x1 - x0;
  if (x0 < 0) x0 = 0;
  if (w0 > SCREEN_W - x0) w0 = SCREEN_W - x0;

  static uint8_t scratch[(SCREEN_W / 8) * CLEAN_MAX_H];
  const uint8_t* buf = canvas.getBuffer();
  const int screenBytesPerRow = SCREEN_W / 8;
  const int bytesPerRow = w0 / 8;
  const int srcByte0 = x0 / 8;

  // Start phase 1 from the current canvas so unchanged controls stay visible.
  for (int row = 0; row < h; row++) {
    uint8_t* dst = scratch + row * bytesPerRow;
    const uint8_t* src = buf + (y + row) * screenBytesPerRow + srcByte0;
    for (int col = 0; col < bytesPerRow; col++) dst[col] = ~src[col];
  }
  for (int i = 0; i < cleanRectCount; i++) {
    scratchWhiteRect(scratch, x0, y, w0, h, cleanRects[i]);
  }

  // Phase 1: clean only the volatile lyric/timer sub-rectangles. The controls
  // are rewritten as their current canvas pixels, not white.
  display.epd2.writeImage(scratch, x0, y, w0, h, false);
  display.refresh(x0, y, w0, h);
  display.epd2.writeImageToPrevious(scratch, x0, y, w0, h, false);

  // Phase 2: paint the real canvas for the whole lower live region.
  const uint8_t* full = canvas.getBuffer();
  display.writeImage(full, 0, 0, SCREEN_W, SCREEN_H, true);
  display.refresh(x0, y, w0, h);
  display.epd2.writeImagePartToPrevious(full, x0, y, SCREEN_W, SCREEN_H,
                                        x0, y, w0, h, true);

  display.epd2.powerOff();
  lastPushMs = millis();
  refreshes += 2;
}

void epdPushRegionClean(int x, int y, int w, int h) {
  uint32_t since = millis() - lastPushMs;
  if (lastPushMs != 0 && since < MIN_REFRESH_GAP_MS) {
    delay(MIN_REFRESH_GAP_MS - since);
  }
  regionCleanCore(x, y, w, h);
  partials += 2;   // counts toward the deep-clean budget, like other pushes
}

// Lyric / Now-Playing-timer strip repaint. Same crisp white->content clean, but it
// deliberately does NOT wait MIN_REFRESH_GAP_MS (the caller spaces lines with a
// non-blocking LYRIC_MIN_GAP_MS skip) and does NOT count toward PARTIALS_BEFORE_FULL
// — so a song never triggers a full-screen flash. Each clean is self-crisping, so
// no periodic full refresh is needed; the next song's commit does a full anyway.
void epdPushLyric(int x, int y, int w, int h) {
  regionCleanCore(x, y, w, h);
}

void epdPushNowPlayingLive() {
  const CleanRect cleanRects[] = {
    {LYRIC_BAND_X, LYRIC_BAND_Y, LYRIC_BAND_W, LYRIC_BAND_H},
    {NP_BAR_STRIP_X, NP_BAR_STRIP_Y, NP_BAR_STRIP_W, NP_BAR_STRIP_H},
  };
  regionMaskedCleanCore(NP_LIVE_STRIP_X, NP_LIVE_STRIP_Y,
                        NP_LIVE_STRIP_W, NP_LIVE_STRIP_H,
                        cleanRects, 2);
}

uint32_t epdRefreshCount() { return refreshes; }
