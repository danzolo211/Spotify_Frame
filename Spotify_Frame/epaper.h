#pragma once
#include <Adafruit_GFX.h>
#include "config.h"

// The whole UI is drawn into this offscreen canvas, then pushed to the
// panel. The same buffer feeds the phone app's live screen mirror.
extern GFXcanvas1 canvas;

enum PushMode { PUSH_FULL, PUSH_FAST, PUSH_REGION };

void epdInit();
// Pushes the canvas to the panel. PUSH_FAST counts toward the partial
// budget and is silently upgraded to a clean PUSH_FULL when the panel
// has earned one. Refreshes are rate-limited to MIN_REFRESH_GAP_MS.
void epdPush(PushMode mode, int x = 0, int y = 0, int w = SCREEN_W, int h = SCREEN_H);

// Repaints a region "cleanly": it blanks the region to white, then paints the
// current canvas into it — back to back. Routing every update through white
// stops the fast-partial waveform from piling up ghosts on changing glyphs
// (the progress digits / play-pause icon). Use for small regions whose content
// changes shape; a plain PUSH_REGION is fine for the monotonic progress bar.
void epdPushRegionClean(int x, int y, int w, int h);

// Plain partial refresh confined to the requested window. Use when pixels only
// need a differential update, such as the progress fill growing to the right.
void epdPushRegionOnly(int x, int y, int w, int h);

// Crisp white->content clean of a small strip for the live-lyric line and the
// Now-Playing timer/bar: no rate-limit wait and no full-refresh budget, so lyric
// playback never causes a full-screen flash. Cadence is gated by the caller.
// Both panel-RAM writes and both refreshes are confined to the requested window.
void epdPushLyric(int x, int y, int w, int h);
uint32_t epdRefreshCount();
