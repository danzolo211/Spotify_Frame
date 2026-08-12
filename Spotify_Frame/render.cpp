#include "render.h"
#include "epaper.h"
#include "bgs.h"
#include "state.h"
#include "util.h"
#include "config.h"

#include "font_ScriptLg.h"
#include "font_ScriptMd.h"
#include "font_ScriptSm.h"
#include "font_SerifIt.h"
#include "font_SerifRefIt.h"
#include "font_SansBold.h"
#include "font_SansMed.h"
#include "font_SansSmall.h"

#define INK 1
#define PAPER 0

static uint8_t* bgBuf = nullptr;

void renderInit() {
  bgBuf = (uint8_t*)ps_malloc(BG_BYTES);
  if (!bgBuf) bgBuf = (uint8_t*)malloc(BG_BYTES);
}

// ---------------------------------------------------------------- helpers
static uint16_t textWidth(const GFXfont* f, const String& s) {
  int16_t x1, y1;
  uint16_t w, h;
  canvas.setFont(f);
  canvas.getTextBounds(s, 0, 120, &x1, &y1, &w, &h);
  return w;
}

static void drawCentered(const GFXfont* f, const String& s, int cx, int baseline,
                         uint16_t color) {
  int16_t x1, y1;
  uint16_t w, h;
  canvas.setFont(f);
  canvas.setTextColor(color);
  canvas.getTextBounds(s, 0, baseline, &x1, &y1, &w, &h);
  canvas.setCursor(cx - w / 2 - (x1 - 0), baseline);
  canvas.print(s);
}

static bool centeredTextFits(const GFXfont* f, const String& s, int cx,
                             int baseline, int zw, int zh) {
  int16_t x1, y1;
  uint16_t w, h;
  canvas.setFont(f);
  canvas.getTextBounds(s, 0, baseline, &x1, &y1, &w, &h);
  int x = cx - (int)w / 2 - x1;
  canvas.getTextBounds(s, x, baseline, &x1, &y1, &w, &h);
  return x1 >= 0 && y1 >= 0 && x1 + (int)w <= zw && y1 + (int)h <= zh;
}

// greedy word wrap; returns line count or -1 if it doesn't fit
static int wrapText(const String& text, const GFXfont* f, int maxW,
                    String* lines, int maxLines) {
  int n = 0;
  String cur = "";
  int start = 0;
  while (start <= (int)text.length()) {
    int sp = text.indexOf(' ', start);
    String word = (sp < 0) ? text.substring(start)
                           : text.substring(start, sp);
    start = (sp < 0) ? text.length() + 1 : sp + 1;
    if (!word.length()) continue;
    String tryLine = cur.length() ? cur + " " + word : word;
    if (textWidth(f, tryLine) <= maxW) {
      cur = tryLine;
    } else {
      if (!cur.length()) return -1;          // single word too wide
      if (n >= maxLines) return -1;
      lines[n++] = cur;
      cur = word;
      if (textWidth(f, cur) > maxW) return -1;
    }
  }
  if (cur.length()) {
    if (n >= maxLines) return -1;
    lines[n++] = cur;
  }
  return n;
}

static String fitEllipsis(const GFXfont* f, String s, int maxW) {
  if (textWidth(f, s) <= maxW) return s;
  while (s.length() > 1) {
    s.remove(s.length() - 1);
    if (textWidth(f, s + "...") <= maxW) return s + "...";
  }
  return s;
}

static int wrapTwoLineLyric(const String& text, String* out, int maxW) {
  out[0] = "";
  out[1] = "";
  int line = 0;
  int start = 0;
  while (start <= (int)text.length()) {
    int sp = text.indexOf(' ', start);
    String word = (sp < 0) ? text.substring(start) : text.substring(start, sp);
    start = (sp < 0) ? text.length() + 1 : sp + 1;
    if (!word.length()) continue;
    String tryLine = out[line].length() ? out[line] + " " + word : word;
    if (textWidth(&SansSmall, tryLine) <= maxW) {
      out[line] = tryLine;
      continue;
    }
    if (line == 0 && out[0].length()) {
      line = 1;
      out[1] = textWidth(&SansSmall, word) <= maxW
                 ? word : fitEllipsis(&SansSmall, word, maxW);
      continue;
    }
    if (line == 0) {
      out[0] = fitEllipsis(&SansSmall, word, maxW);
      line = 1;
      continue;
    }
    out[1] = fitEllipsis(&SansSmall, tryLine, maxW);
    return out[0].length() ? 2 : 1;
  }
  return out[1].length() ? 2 : (out[0].length() ? 1 : 0);
}

static void diamond(int cx, int cy, int r, uint16_t color) {
  canvas.fillTriangle(cx - r, cy, cx, cy - r, cx + r, cy, color);
  canvas.fillTriangle(cx - r, cy, cx, cy + r, cx + r, cy, color);
}

static void heart(int cx, int cy, int s, uint16_t color) {
  canvas.fillCircle(cx - s / 2, cy - s / 4, s / 2, color);
  canvas.fillCircle(cx + s / 2, cy - s / 4, s / 2, color);
  canvas.fillTriangle(cx - s, cy, cx + s, cy, cx, cy + s, color);
}

static bool verseLayoutFits(const GFXfont* f, String* lines, int nLines,
                            const String& ref, int zw, int zh) {
  const int refBlock = SerifRefIt.yAdvance + 8;
  int block = nLines * f->yAdvance + 8 + refBlock;
  if (block > zh) return false;
  int top = (zh - block) / 2;
  if (top < 0) top = 0;
  int cx = zw / 2;
  int ascent = (int)(f->yAdvance * 0.72);
  for (int i = 0; i < nLines; i++) {
    int baseline = top + i * f->yAdvance + ascent;
    if (!centeredTextFits(f, lines[i], cx, baseline, zw, zh)) return false;
  }
  int refY = top + nLines * f->yAdvance + 8
             + (int)(SerifRefIt.yAdvance * 0.72);
  return centeredTextFits(&SerifRefIt, ref, cx, refY, zw, zh);
}

// ---------------------------------------------------------------- verse
#define MAX_LINES 9

void renderVerse(const Verse& v, int bgId) {
  const BgInfo& bg = bgsGet(bgId);
  canvas.fillScreen(bg.whiteInk ? INK : PAPER);
  if (bgBuf && bgsLoad(bgId, bgBuf)) {
    canvas.fillScreen(PAPER);
    canvas.drawBitmap(0, 0, bgBuf, SCREEN_W, SCREEN_H, INK);
  }
  uint16_t ink = bg.whiteInk ? PAPER : INK;

  String text = v.text;
  if (ADD_QUOTES && !text.startsWith("\"")) text = "\"" + text + "\"";

  const int zx = bg.zx + 6, zy = bg.zy, zw = bg.zw - 12, zh = bg.zh;
  const int cx = zx + zw / 2;
  const int refBlock = SerifRefIt.yAdvance + 8;

  static const GFXfont* chain[] = { &ScriptLg, &ScriptMd, &ScriptSm, &SerifIt };
  String lines[MAX_LINES];
  const GFXfont* font = &SerifIt;
  int nLines = 0, lineH = SerifIt.yAdvance;
  for (const GFXfont* f : chain) {
    int lh = f->yAdvance;
    int maxLines = (zh - refBlock - 4) / lh;
    if (maxLines < 1) continue;
    if (maxLines > MAX_LINES) maxLines = MAX_LINES;
    int n = wrapText(text, f, zw, lines, maxLines);
    if (n > 0 && verseLayoutFits(f, lines, n, v.ref, zw, zh)) {
      font = f; nLines = n; lineH = lh; break;
    }
  }
  if (nLines == 0) {
    // Bundled verses are proved by tools/audit_backgrounds.py. If a future verse
    // is added without running the audit, fail visibly instead of cutting text.
    font = &SansSmall;
    lineH = SansSmall.yAdvance;
    lines[0] = "Verse too long for this scene";
    nLines = 1;
  }

  int block = nLines * lineH + 8 + refBlock;
  int top = zy + (zh - block) / 2;
  if (top < zy) top = zy;
  int ascent = (int)(lineH * 0.72);
  for (int i = 0; i < nLines; i++)
    drawCentered(font, lines[i], cx, top + i * lineH + ascent, ink);

  // reference with flourish
  int refY = top + nLines * lineH + 8 + (int)(SerifRefIt.yAdvance * 0.72);
  uint16_t rw = textWidth(&SerifRefIt, v.ref);
  drawCentered(&SerifRefIt, v.ref, cx, refY, ink);
  int ly = refY - 4;
  int leftEnd = cx - (int)rw / 2 - 14;
  int rightStart = cx + (int)rw / 2 + 14;
  if (leftEnd - zx >= 12) {
    int leftStart = max(zx, leftEnd - 24);
    canvas.drawFastHLine(leftStart, ly, leftEnd - leftStart, ink);
    diamond(leftEnd + 5, ly, 3, ink);
  }
  if (zx + zw - rightStart >= 12) {
    int rightEnd = min(zx + zw, rightStart + 24);
    canvas.drawFastHLine(rightStart, ly, rightEnd - rightStart, ink);
    diamond(rightStart - 5, ly, 3, ink);
  }
}

// Does this verse fit a text zone of (zw x zh) using the same font chain and
// word-wrap the real renderer uses? (mirrors the loop in renderVerse). Lets the
// firmware pair long verses only with roomy backgrounds instead of truncating.
bool renderVerseFits(const String& text0, const String& ref, int zw, int zh) {
  String text = text0;
  if (ADD_QUOTES && !text.startsWith("\"")) text = "\"" + text + "\"";
  const int refBlock = SerifRefIt.yAdvance + 8;
  if (textWidth(&SerifRefIt, ref) > zw) return false;
  static const GFXfont* chain[] = { &ScriptLg, &ScriptMd, &ScriptSm, &SerifIt };
  String lines[MAX_LINES];
  for (const GFXfont* f : chain) {
    int lh = f->yAdvance;
    int maxLines = (zh - refBlock - 4) / lh;
    if (maxLines < 1) continue;
    if (maxLines > MAX_LINES) maxLines = MAX_LINES;
    int n = wrapText(text, f, zw, lines, maxLines);
    if (n > 0 && verseLayoutFits(f, lines, n, ref, zw, zh)) return true;
  }
  return false;
}

// ---------------------------------------------------------------- spotify
static void letterSpaced(const GFXfont* f, const String& s, int x, int baseline,
                         int extra, uint16_t color) {
  canvas.setFont(f);
  canvas.setTextColor(color);
  int pen = x;
  for (unsigned i = 0; i < s.length(); i++) {
    if (s[i] == ' ') { pen += 6 + extra; continue; }
    String ch(s[i]);
    canvas.setCursor(pen, baseline);
    canvas.print(ch);
    pen += textWidth(f, ch) + extra;
  }
}

// ---- live lyric line -------------------------------------------------------
static String g_lyric = "";
static bool   g_lyricInstrumental = false;

void renderSetLyric(const String& line, bool instrumental) {
  g_lyric = line;
  g_lyricInstrumental = instrumental;
}

// a small centered music note drawn with primitives (our Latin-1 fonts have no
// U+266A), shown when a track is instrumental
static void lyricNote(int cx, int cy) {
  canvas.fillCircle(cx - 4, cy + 5, 4, INK);      // note head
  canvas.fillRect(cx - 1, cy - 7, 2, 13, INK);    // stem
  canvas.fillRect(cx - 1, cy - 7, 7, 3, INK);     // flag
}

// Repaint ONLY the lyric band in the canvas: clear it to paper, then draw the
// current line centered (single line, ellipsized so it can never spill sideways).
// The panel push for lyric changes is confined to this same band, so progress,
// timestamps, and transport controls stay visually stable.
void renderLyricBand() {
  canvas.fillRect(LYRIC_BAND_X, LYRIC_BAND_Y, LYRIC_BAND_W, LYRIC_BAND_H, PAPER);
  if (!settings.lyricsOn) return;                 // lyrics off -> band stays blank
  if (g_lyricInstrumental) { lyricNote(SCREEN_W / 2, LYRIC_BAND_Y + 17); return; }
  String s = utf8ToLatin1(g_lyric);
  s.trim();
  if (!s.length()) return;                          // blank band (interlude / no line yet)
  const int maxW = LYRIC_BAND_W - 24;
  if (textWidth(&SansMed, s) <= maxW) {
    drawCentered(&SansMed, s, SCREEN_W / 2, LYRIC_BAND_Y + 24, INK);
    return;
  }
  if (textWidth(&SansSmall, s) <= maxW) {
    drawCentered(&SansSmall, s, SCREEN_W / 2, LYRIC_BAND_Y + 24, INK);
    return;
  }
  String lines[2];
  int n = wrapTwoLineLyric(s, lines, maxW);
  if (n <= 0) return;
  drawCentered(&SansSmall, lines[0], SCREEN_W / 2, LYRIC_BAND_Y + 15, INK);
  if (n > 1)
    drawCentered(&SansSmall, lines[1], SCREEN_W / 2, LYRIC_BAND_Y + 32, INK);
}

static const int BAR_L = 18, BAR_R = 382, BAR_Y = 267, BAR_H = 12;
static const int TIME_BASELINE = BAR_Y + BAR_H + 16;

int spotifyProgressFillWidth() {
  float frac = app.trackDuration > 0
               ? (float)app.trackProgress / app.trackDuration : 0;
  frac = constrain(frac, 0.0f, 1.0f);
  return (int)(NP_FILL_MAX_W * frac);
}

String spotifyElapsedTimeText() {
  return mmss(app.trackProgress);
}

void renderSpotifyProgressBarOnly() {
  canvas.fillRect(NP_BAR_BOX_X, NP_BAR_BOX_Y, NP_BAR_BOX_W, NP_BAR_BOX_H, PAPER);
  canvas.drawRoundRect(BAR_L, BAR_Y, BAR_R - BAR_L, BAR_H, BAR_H / 2, INK);
  int fw = spotifyProgressFillWidth();
  if (fw > 2)
    canvas.fillRoundRect(NP_FILL_X, NP_FILL_Y, fw, NP_FILL_H, NP_FILL_H / 2, INK);
}

void renderSpotifyElapsedTimeOnly() {
  canvas.fillRect(NP_TIME_LEFT_X, NP_TIME_LEFT_Y,
                  NP_TIME_LEFT_W, NP_TIME_LEFT_H, PAPER);
  canvas.setFont(&SansSmall);
  canvas.setTextColor(INK);
  canvas.setCursor(BAR_L, TIME_BASELINE);
  canvas.print(spotifyElapsedTimeText());
}

void renderSpotifyProgressStrip() {
  canvas.fillRect(NP_BAR_STRIP_X, NP_BAR_STRIP_Y,
                  NP_BAR_STRIP_W, NP_BAR_STRIP_H, PAPER);
  renderSpotifyProgressBarOnly();
  renderSpotifyElapsedTimeOnly();
  canvas.setFont(&SansSmall);
  canvas.setTextColor(INK);
  String dur = mmss(app.trackDuration);
  canvas.setCursor(BAR_R - textWidth(&SansSmall, dur), TIME_BASELINE);
  canvas.print(dur);
}

void renderSpotify(const uint8_t* artBits, bool artValid) {
  canvas.fillScreen(PAPER);
  // header
  letterSpaced(&SansSmall, "NOW PLAYING", 18, 22, 3, INK);
  heart(374, 16, 7, INK);
  canvas.drawFastHLine(18, 32, 364, INK);

  // album art
  const int ART = 152, AX = 18, AY = 44;
  canvas.drawRect(AX - 2, AY - 2, ART + 4, ART + 4, INK);
  if (artValid && artBits)
    canvas.drawBitmap(AX, AY, artBits, ART, ART, INK);
  else {
    // placeholder: quiet music note
    canvas.drawCircle(AX + 62, AY + 100, 13, INK);
    canvas.drawCircle(AX + 62, AY + 100, 12, INK);
    canvas.fillCircle(AX + 62, AY + 100, 11, INK);
    canvas.fillRect(AX + 71, AY + 40, 4, 60, INK);
    canvas.fillRect(AX + 71, AY + 40, 26, 10, INK);
  }

  // title (up to 2 lines) + artist
  const int TX = 186, TW = 382 - TX;
  String title = utf8ToLatin1(app.trackTitle);
  String artist = utf8ToLatin1(app.trackArtist);
  String tl[2];
  int n = wrapText(title, &SansBold, TW, tl, 2);
  if (n <= 0) { tl[0] = fitEllipsis(&SansBold, title, TW); n = 1; }
  else for (int i = 0; i < n; i++) tl[i] = fitEllipsis(&SansBold, tl[i], TW);
  canvas.setFont(&SansBold);
  canvas.setTextColor(INK);
  int ty = 84;
  for (int i = 0; i < n; i++) {
    canvas.setCursor(TX, ty);
    canvas.print(tl[i]);
    ty += SansBold.yAdvance;
  }
  canvas.setFont(&SansMed);
  canvas.setCursor(TX, ty + 6);
  canvas.print(fitEllipsis(&SansMed, artist, TW));

  // transport row
  int cy = 249, cxp = 200;
  // prev / next (decorative, mirrors her phone)
  canvas.fillTriangle(160, cy, 170, cy - 7, 170, cy + 7, INK);
  canvas.fillRect(156, cy - 7, 3, 14, INK);
  canvas.fillTriangle(240, cy, 230, cy - 7, 230, cy + 7, INK);
  canvas.fillRect(242, cy - 7, 3, 14, INK);
  canvas.drawCircle(cxp, cy, 14, INK);
  canvas.drawCircle(cxp, cy, 13, INK);
  if (app.trackPlaying) {
    canvas.fillRect(cxp - 5, cy - 6, 3, 12, INK);
    canvas.fillRect(cxp + 2, cy - 6, 3, 12, INK);
  } else {
    canvas.fillTriangle(cxp - 4, cy - 6, cxp - 4, cy + 6, cxp + 7, cy, INK);
  }

  // progress bar + times
  renderSpotifyProgressStrip();

  // live lyric line (drawn last; disjoint band, so order is immaterial)
  renderLyricBand();
}

// ---------------------------------------------------------------- note
void renderNote(const String& text, const String& from) {
  int bgId = bgsNoteFrame();
  const BgInfo& bg = bgsGet(bgId);
  canvas.fillScreen(PAPER);
  if (bgBuf && bgsLoad(bgId, bgBuf))
    canvas.drawBitmap(0, 0, bgBuf, SCREEN_W, SCREEN_H, INK);

  const int zx = bg.zx + 6, zy = bg.zy, zw = bg.zw - 12, zh = bg.zh;
  const int cx = zx + zw / 2;
  letterSpaced(&SansSmall, "A NOTE FOR YOU", cx - 66, zy + 10, 3, INK);

  String body = utf8ToLatin1(text);
  static const GFXfont* chain[] = {
    &ScriptLg, &ScriptMd, &ScriptSm, &SerifIt, &SansSmall
  };
  String lines[MAX_LINES];
  const GFXfont* font = &SerifIt;
  int nLines = 0, lineH = SerifIt.yAdvance;
  int fromBlock = from.length() ? SerifRefIt.yAdvance + 8 : 0;
  for (const GFXfont* f : chain) {
    int maxLines = (zh - 26 - fromBlock) / f->yAdvance;
    if (maxLines < 1) continue;
    int n = wrapText(body, f, zw, lines, min(maxLines, MAX_LINES));
    if (n > 0) { font = f; nLines = n; lineH = f->yAdvance; break; }
  }
  if (nLines == 0) {   // longer than the whole chain: fill the zone with the
    font = &SansSmall; // smallest font and ellipsize, rather than collapsing a
    lineH = SansSmall.yAdvance;                     // whole note to one "..." line
    int maxLines = max(1, (zh - 26 - fromBlock) / lineH);
    if (maxLines > MAX_LINES) maxLines = MAX_LINES;
    String t = body;
    while (nLines <= 0 && t.length() > 8) {
      t.remove(t.length() - 8);
      nLines = wrapText(t + "...", font, zw, lines, maxLines);
    }
    if (nLines <= 0) { lines[0] = fitEllipsis(&SansSmall, body, zw); nLines = 1; }
  }

  int block = nLines * lineH + fromBlock;
  int top = zy + 26 + (zh - 26 - block) / 2;
  int ascent = (int)(lineH * 0.72);
  for (int i = 0; i < nLines; i++)
    drawCentered(font, lines[i], cx, top + i * lineH + ascent, INK);
  if (from.length()) {
    String f = "- " + utf8ToLatin1(from);
    drawCentered(&SerifRefIt, f, cx,
                 top + nLines * lineH + 6 + (int)(SerifRefIt.yAdvance * 0.72), INK);
  }
}

// ---------------------------------------------------------------- special
void renderSpecial(const char* title, const char* msg, const String& forName) {
  int bgId = bgsCelebration();
  const BgInfo& bg = bgsGet(bgId);
  canvas.fillScreen(PAPER);
  if (bgBuf && bgsLoad(bgId, bgBuf))
    canvas.drawBitmap(0, 0, bgBuf, SCREEN_W, SCREEN_H, INK);

  const int zx = bg.zx, zy = bg.zy, zw = bg.zw, zh = bg.zh;
  const int cx = zx + zw / 2;
  String t(title), m(msg);
  String tl[2], ml[4];
  const GFXfont* tf = &ScriptLg;
  int tn = wrapText(t, tf, zw - 10, tl, 2);
  if (tn <= 0) { tf = &ScriptMd; tn = wrapText(t, tf, zw - 10, tl, 2); }
  if (tn <= 0) { tl[0] = fitEllipsis(&ScriptMd, t, zw - 10); tn = 1; }
  const GFXfont* mf = &ScriptSm;
  int mn = wrapText(m, mf, zw - 10, ml, 4);
  if (mn <= 0) { mf = &SerifIt; mn = wrapText(m, mf, zw - 10, ml, 4); }
  if (mn <= 0) { ml[0] = fitEllipsis(&SerifIt, m, zw - 10); mn = 1; }

  int block = tn * tf->yAdvance + 10 + mn * mf->yAdvance + 24;
  int top = zy + (zh - block) / 2;
  if (top < zy) top = zy;
  int y = top;
  for (int i = 0; i < tn; i++) {
    drawCentered(tf, tl[i], cx, y + (int)(tf->yAdvance * 0.72), INK);
    y += tf->yAdvance;
  }
  y += 10;
  for (int i = 0; i < mn; i++) {
    drawCentered(mf, ml[i], cx, y + (int)(mf->yAdvance * 0.72), INK);
    y += mf->yAdvance;
  }
  y += 8;
  heart(cx, y + 6, 6, INK);
  if (forName.length())
    drawCentered(&SerifRefIt, "for " + forName, cx, y + 26, INK);
}

// ---------------------------------------------------------------- misc
void renderMessage(const String& l1, const String& l2) {
  canvas.fillScreen(PAPER);
  // small cross mark
  canvas.fillRect(SCREEN_W / 2 - 3, 74, 6, 46, INK);
  canvas.fillRect(SCREEN_W / 2 - 16, 88, 32, 6, INK);
  drawCentered(&SansBold, l1, SCREEN_W / 2, 168, INK);
  if (l2.length()) drawCentered(&SansMed, l2, SCREEN_W / 2, 200, INK);
  drawCentered(&ScriptSm, "GraceFrame", SCREEN_W / 2, 262, INK);
}

void renderSetup(const String& apName, const String& url) {
  canvas.fillScreen(PAPER);
  drawCentered(&ScriptLg, "Welcome to GraceFrame", SCREEN_W / 2, 64, INK);
  canvas.drawFastHLine(60, 84, 280, INK);
  drawCentered(&SansBold, "Let's get connected", SCREEN_W / 2, 124, INK);
  drawCentered(&SansMed, "1. On your phone, join the Wi-Fi network:", SCREEN_W / 2, 158, INK);
  drawCentered(&SansBold, apName, SCREEN_W / 2, 186, INK);
  drawCentered(&SansMed, "2. A setup page will open (or visit " + url + ")",
               SCREEN_W / 2, 218, INK);
  drawCentered(&SansMed, "3. Choose your home Wi-Fi and save", SCREEN_W / 2, 246, INK);
}

void renderConnected(const String& ssid, const String& ip, const String& host) {
  canvas.fillScreen(PAPER);
  drawCentered(&ScriptLg, "GraceFrame is online", SCREEN_W / 2, 62, INK);
  canvas.drawFastHLine(70, 82, 260, INK);
  drawCentered(&SansBold, "Connected to Wi-Fi", SCREEN_W / 2, 122, INK);
  drawCentered(&SansMed, fitEllipsis(&SansMed, ssid, 330), SCREEN_W / 2, 154, INK);
  drawCentered(&SansMed, ip, SCREEN_W / 2, 190, INK);
  drawCentered(&SansMed, host, SCREEN_W / 2, 222, INK);
  drawCentered(&ScriptSm, "Ready for Emily", SCREEN_W / 2, 270, INK);
}
