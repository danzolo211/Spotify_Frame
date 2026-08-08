# GraceFrame — Integrated Stand (V_3) Assembly

`V_3_Daniel_Weber_Stand.stl` is the original stand **edited** into an Aura-style,
self-contained frame: deepened 7 mm and given a built-in electronics bay.

Regenerate any time with `python tools/edit_stand.py` (all sizes are parameters at
the top). Preview: `tools/_v3_preview.png` (cutaway + back + side fit schematic).

> **`V_3` is in real millimeters** — import normally (no ×25.4 like the inch original).

## What changed vs V_2
- **+7 mm depth** → cavity ~24 mm (comfortable room for display + ESP + adapter).
- **USB-C port** cut through the back wall, bottom-center (cable exits behind = Aura).
- **Adapter cradle** (bottom-center): holds the GELRHONR right-angle USB-C→2-pin
  adapter, USB-C facing out the port, green terminal pointing up.
- **ESP tray** (mid): the 58×28 mm ESP32-S3 drops in, held against the back wall.
- **Right-side wire-relief channel**: the display is a 103 mm glove-fit in the
  103.6 mm pocket, so the 8 connector wires bend sideways into this channel instead
  of eating cavity depth.

## Parts
- Display: Waveshare 4.2" module (103.0 × 78.5 mm). ESP32-S3 dev board (58 × 28 mm).
- **GELRHONR USB-C-female → 2-pin screw terminal, 5V** (right-angle, solderless).
- 8× female–female jumper leads (display ↔ ESP). Any 5V USB-C charger.

## 1) Print `V_3`
- Orientation: **back face on the bed** (the flat back), so the cavity/trays print
  cleanly and the port needs no support.
- 0.2 mm layers, ≥3 perimeters, ≥25% infill.

## 2) Wire it (do this with power UNPLUGGED)
- e-paper ↔ ESP per `WIRING.md`: **VCC → 3.3V (never 5V)**, GND→GND, DIN→G21,
  CLK→G14, CS→G10, DC→G11, RST→G12, BUSY→G13.
- Adapter → ESP power:
  - Terminal **`+` → ESP `5V`/`VIN` pin**
  - Terminal **`−` → ESP `GND`**
  - ⚠️ **Polarity is on you** — reversed = dead board. Confirm the `+`/`−` printing.
  - ⚠️ 5 V goes to the ESP `5V` pin **only** — never to 3V3 or the panel's VCC.
- The ESP's regulator makes the 3.3 V the panel runs on. Flash via the ESP's own
  USB port before final assembly (the adapter powers it in daily use).

## 3) Assemble (electronics go in before the display)
1. Screw the two power wires into the adapter's terminal; **seat the adapter in the
   cradle**, USB-C nose aligned to the back port. (A dab of hot glue makes it captive.)
2. **Drop the ESP into its tray.**
3. Mount the display so its **connector/header is on the RIGHT edge**; tuck the 8
   jumper wires into the **right relief channel** so they bend back flat.
   - Set the firmware rotation so the image matches this orientation
     (`display.setRotation(...)` in `epaper.cpp`).
4. **Press the display into the front bezel** until flush; confirm nothing behind it
   is proud of the ~24 mm cavity.
5. Plug a USB-C charger into the back port → power on.

## Fit notes (measured, with margin)
Cavity ~24 mm. Adapter uses ~15 mm (≈9 mm to the display); ESP + pins/jumpers ~13 mm
(≈11 mm to the display). If your adapter is deeper than 15 mm or the module thicker
than ~4 mm, there's still headroom; if ever tight, **trim the ESP header pins**.

## Fallback (no reprint)
If you'd rather not reprint the stand, the earlier **`USBC_Base_Bracket.stl`** drops
into the existing base as a separate holder — same idea, no frame changes.

## Safety recap
- e-paper **VCC = 3.3 V only**; 5 V destroys the panel.
- Wire everything **unplugged**, then power.
- Adapter 5 V → ESP **5V/VIN** pin only; mind **polarity**.
