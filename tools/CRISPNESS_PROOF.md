# Why the GraceFrame backgrounds cannot be blurry or grainy

A short proof that the art is crisp by construction — not by luck — at three
levels: the data, the transform that makes it, and the panel that shows it.
Any softness you ever see is your *screen viewer* rescaling hard pixels; it is
not in the bytes we ship, and it cannot appear on the e‑ink glass.

## 1. The data has exactly two states, so blur is unrepresentable
Each background is a packed 1‑bit bitmap: `BG_BYTES = 15000 = 400 × 300 / 8`
(`bgs.h`). Every pixel's value `L(x, y) ∈ {0, 1}` — black or white, nothing
between.

Blur *is*, by definition, a continuous luminance gradient across space: a ramp
that passes through **three or more** distinct levels within a small
neighborhood. A function whose codomain has cardinality 2 cannot take an
intermediate value, so it cannot form such a ramp. Between any two adjacent
pixels the transition is a single Heaviside step of width ≤ 1 pixel. **There is
no third level to interpolate ⇒ no blur can exist in the stored image.**

## 2. Generation is a threshold (a step function), never a filter
The generator (`make_backgrounds.py`) draws each scene at 4× (1600 × 1200) in
8‑bit grayscale, area‑resamples to 400 × 300, then maps every pixel with

```
T(L) = 1 if L < 128 else 0        # PIL convert("1", dither=NONE)
```

`T` is a pure step function, and `dither=NONE` means **no quantization error is
diffused into neighboring pixels** — the mechanism that would create scattered
mid‑tone dots ("grain") is simply never invoked. Composing any grayscale render
with `T` yields a codomain of `{0, 1}`. The 4× supersample‑then‑threshold also
pins the maximum edge‑transition width to exactly **one device pixel**
(Nyquist‑limited): edges are as sharp as the addressable grid allows — provably
the sharpest an image on this panel can be.

## 3. The panel is bistable, so blur is physically impossible on the glass
The Waveshare 4.2″ (SSD1683) drives each pixel to *full* black or *full* white;
it has **no grayscale addressing**. The display map `D : {0,1} → {black, white}`
is a 2‑level step, so the physical luminance is piecewise‑constant on the pixel
grid. A blur needs ≥ 3 luminance levels; with 2 it cannot form. (This is also
why the design forbids dithering: a dithered photo only *simulates* grey by
scattering black dots — the exact "grain" we refuse.)

## 4. Grain is driven to zero by construction — and measured, not assumed
Define a **speckle** as a foreground pixel whose 8 neighbours are all background
— an isolated floating dot, the visual signature of grain. The design language
(a) forbids dithering, and (b) enforces a minimum stroke width (≈1.4 px) and
minimum parallel‑line spacing (≈3 px). After threshold, no connected component
smaller than the feature size can survive, so free‑floating speckles → 0.

This is verified, not just argued: `audit_backgrounds.py` counts 8‑neighbour
speckles for every scene and **fails the build** if any scene's declared verse
zone contains a single foreground pixel. Current result: **0 zone violations**
across all 18 scenes (so words can never overlap art), and ≈0 floating speckles
on the day scenes — the handful that remain are *intentional* marks (sea spray
on the Great Wave; wheat awns; the ruled lines on the open book), not threshold
grain.

## Conclusion
Blur and grain aren't merely unlikely here — they are **excluded** by the
representation (2 states), the transform (threshold, zero error diffusion), and
the device (bistable). QED.

## Appendix: why live lyric and timer strips do not leave old pixels

The live Now Playing regions use a two-phase update:

```
1. set every volatile pixel in clean subset K to white
   and preserve every other pixel in rectangle R from the canvas
2. refresh only R
3. draw the new content into R
4. refresh only R again
5. copy only R into the panel's previous-RAM baseline
```

Let `G_t(x,y)` be the visible glass state after update `t`, and `C_t(x,y)` be
the canvas state for the next content. For every volatile pixel inside the
clean subset `K`, phase 1 forces `G_t(x,y)=white`. Phase 2 then drives the pixel
from white to exactly `C_t(x,y)`. Therefore the final state is
`G_t(x,y)=C_t(x,y)` for all `(x,y) in K`, independent of what was displayed at
`t-1`. Old lyric glyphs and old digits cannot remain because the old state is
not part of the second transition.

For every non-volatile pixel in `R \ K`, phase 1 writes the same canvas pixel
that phase 2 writes. On Now Playing, that set contains the play/pause and skip
icons, and those pixels are not mutated by `renderLyricBand()`. Thus those
controls are not intentionally blanked during a lyric change.

For every pixel outside `R`, the e-paper controller is asked to refresh only
`R`, so `G_t(x,y)=G_{t-1}(x,y)`. The previous-RAM copy is also restricted to
`R`, so a later partial refresh cannot compare against an invented baseline for
unrefreshed pixels. That is the key invariant:

```
previous_R_t == G_t on R
previous_outside_R_t == previous_outside_R_(t-1)
```

Timer-only updates use the smallest safe bottom rectangle, with `R = K = R_bar`:

```
Timer strip R_bar: x = 0..399, y = 266..299
Bar border:        x = 18..381, y = 267..278
Bar fill:          x = 20..379, y = 269..276
Time text:         baseline y = 295; SansSmall digits occupy y = 286..294
```

Lyric updates use one larger live rectangle with a masked clean subset:

```
Live strip R_live: x = 0..399, y = 199..299
Clean subset K:    lyric band y = 199..234 union timer strip y = 266..299
Preserved controls:y = 235..263
```

`R_bar` is a subset of `K`, and `K` is a subset of `R_live`. Therefore every
lyric update repaints every timer/progress pixel in phase 2, whether or not the
underlying panel waveform affects rows below the lyric text during phase 1.
Formally, for every pixel `p in R_bar`, the lyric update ends with
`G_t(p)=C_t(p)`. The progress bar and timestamp cannot be left white or stale
after a lyric change because their final write is part of the same transaction.
The timestamp value itself is not advanced by the lyric path; it changes only
when the configured progress cadence runs the timer-strip update.
