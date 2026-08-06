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
uint32_t epdRefreshCount();
