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

The live lyric band and elapsed-time box use the same two-phase update:

```
1. set every pixel in rectangle R to white
2. refresh only R
3. draw the new content into R
4. refresh only R again
5. copy only R into the panel's previous-RAM baseline
```

Let `G_t(x,y)` be the visible glass state after update `t`, and `C_t(x,y)` be
the canvas state for the next content. For every pixel inside the strip
rectangle `R`, phase 1 forces `G_t(x,y)=white`. Phase 2 then drives the pixel
from white to exactly `C_t(x,y)`. Therefore the final state is
`G_t(x,y)=C_t(x,y)` for all `(x,y) in R`, independent of what was displayed at
`t-1`. Old glyphs cannot remain because the old state is not part of the second
transition.

For every pixel outside `R`, the clean helper writes neither current RAM nor
previous RAM, and the e-paper controller is asked to refresh only `R`. Therefore
`G_t(x,y)=G_{t-1}(x,y)` outside `R`. That is the key invariant:

```
previous_R_t == G_t on R
previous_outside_R_t == previous_outside_R_(t-1)
```

The lyric and progress rectangles are disjoint in the firmware constants:

```
Lyric band R_lyric: x = 0..399, y = 199..234
Transport icons:    y = 235..263
Progress bar box:   x = 16..383, y = 266..279
Elapsed time box:   x = 16..95,  y = 282..299
```

The full bottom strip contains the full timer/bar draw area:

```
Bar border: x = 18..381, y = 267..278
Bar fill:   x = 20..379, y = 269..276
Time text:  baseline y = 295; SansSmall digits occupy y = 286..294
```

`R_lyric` is disjoint from every progress rectangle, separated by the transport
icon rows. A lyric update uses `R = R_lyric`; it cannot blank, repaint, or
visibly flash the progress bar, timestamps, play/pause button, or skip arrows
because the clean helper writes only `R_lyric` into current RAM, previous RAM,
and the partial-refresh window.

Normal timer ticks also minimize flashing. The progress tick uses one masked
two-phase update over the bottom progress window. Its clean set is the small
elapsed-time box plus only the moving edge of the progress fill. Phase 1 copies
the previous displayed progress strip, not the future canvas, then whites only
the clean set. Phase 2 writes the final canvas. Therefore the fill cannot jump
ahead during the clean phase, and unchanged bar/frame pixels do not get a white
blink. If Spotify seeks backward and the bar must shrink, the firmware cleans
the fill interior so old black pixels are erased.

The coordinate invariant is explicit in `config.h`: lyrics are rows 199..234
and the progress/timestamp strip is rows 266..299. Because the lyric partial
push is confined to `LYRIC_BAND_*`, it cannot address the timestamp or progress
pixels at all. Progress ticks are also held away from lyric-line changes by
`PROGRESS_LYRIC_GUARD_MS`, so a legitimate timestamp clean pass is not scheduled
on top of the lyric transition and mistaken for lyric-induced erasing.
