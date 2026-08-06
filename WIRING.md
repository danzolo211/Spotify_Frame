# GraceFrame — Wiring

**Parts:** ESP32-S3 Dev Module · Waveshare 4.2" e-Paper Module (400×300, B/W)
· USB-C power adapter (5V) · the 8-wire cable that comes with the display.

## Connections

The Waveshare cable colors are standard, but double-check the labels printed
on the display's driver board — the label wins over the color.

| e-Paper pin | Wire color (typical) | ESP32-S3 pin | Purpose            |
|-------------|----------------------|--------------|--------------------|
| **VCC**     | gray / red           | **3.3V**     | power (NOT 5V!)    |
| **GND**     | brown / black        | **GND**      | ground             |
| **DIN**     | blue                 | **GPIO 21**  | SPI data (MOSI)    |
| **CLK**     | yellow               | **GPIO 14**  | SPI clock          |
| **CS**      | orange               | **GPIO 10**  | chip select        |
| **DC**      | green                | **GPIO 11**  | data/command       |
| **RST**     | white                | **GPIO 12**  | reset              |
| **BUSY**    | purple               | **GPIO 13**  | busy signal        |

If your board revision has a 9th **PWR** pin: connect it to **3.3V** as well.

```
        ESP32-S3 DevKit                     Waveshare 4.2" e-Paper
       ┌───────────────┐                   ┌──────────────────────┐
  USB-C│               │3V3 ─────────────── VCC   (+ PWR if present)
 power │               │GND ─────────────── GND
  in   │               │G21 ─────────────── DIN
       │               │G14 ─────────────── CLK
       │               │G10 ─────────────── CS
       │               │G11 ─────────────── DC
       │               │G12 ─────────────── RST
       │               │G13 ─────────────── BUSY
       └───────────────┘                   └──────────────────────┘
```

## Rules that save screens

1. **VCC to 3.3V, never 5V.** 5V will cook the panel.
2. Wire everything **with the power unplugged**, then plug in USB-C.
3. Seat the flat ribbon (FPC) between panel and driver board gently — flip
   the little black latch up, slide the ribbon in, press the latch down.
4. Keep the display flat; never press on the glass.
5. If the screen stays **blank or scrambled** after flashing: your panel is
   probably the older revision — open `GraceFrame/config.h` and switch
   `PANEL_GDEY042T81` → `PANEL_GDEW042T2` (two lines), re-upload.
6. If the image is **upside-down** for your frame build, change
   `display.setRotation(0)` to `2` in `epaper.cpp`.

Power draw is tiny (e-ink only sips power while refreshing), so any USB-C
phone charger works.
