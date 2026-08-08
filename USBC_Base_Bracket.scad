// USB-C base bracket for V_2_Daniel_Weber_Stand
// Holds a panel-mount USB-C female jack in the open bottom-center of the stand.
// Edit the numbers, then render (F6) and export STL.  Identical defaults to
// tools/make_base_bracket.py -- use whichever you prefer.
//
// Orientation when installed: +Z points to the REAR (the jack faces out the open
// back of the base); the FRONT face (Z=0) butts the solid front bezel so plugging
// a cable in can't push the bracket inward. Print with the FLOOR on the bed.

/* ---- tune to YOUR jack (mm) ---- */
pocket_depth = 22.0;  // front-to-back; keep == stand pocket depth so it wedges
width        = 24.0;
height       = 16.0;
floor_t      = 3.0;
panel_t      = 3.0;

aper_w   = 12.0;      // jack aperture width  (jack body + ~0.5 mm)
aper_h   = 8.0;       // jack aperture height
aper_yc  = 8.0;       // aperture center above the floor

screw_holes   = false; // set true if your jack mounts with 2 screws
screw_spacing = 16.0;  // center-to-center
screw_dia     = 2.2;   // M2 clearance

rail_t = 2.5; rail_h = 6.0;      // side rails
gusset_l = 8.0; gusset_h = 13.0; // panel-to-floor braces
$fn = 32;

module gusset(cx)
  // right-triangle brace on the panel front face, spanning rail width at x=cx
  translate([cx - rail_t/2, floor_t, pocket_depth - panel_t])
    rotate([0,90,0])
      linear_extrude(rail_t)
        polygon([[0,0],[0,-gusset_l],[gusset_h,0]]);

difference() {
  union() {
    // floor (rests on the stand's internal shelf)
    translate([-width/2, 0, 0]) cube([width, floor_t, pocket_depth]);
    // rear panel (solid; aperture cut below)
    translate([-width/2, 0, pocket_depth - panel_t]) cube([width, height, panel_t]);
    // side rails
    translate([-width/2, 0, 0]) cube([rail_t, rail_h, pocket_depth]);
    translate([ width/2 - rail_t, 0, 0]) cube([rail_t, rail_h, pocket_depth]);
    // gussets at the outer edges (clear of the central jack body)
    gusset(-width/2 + rail_t/2);
    gusset( width/2 - rail_t/2);
  }
  // jack aperture through the rear panel
  translate([-aper_w/2, aper_yc - aper_h/2, pocket_depth - panel_t - 0.5])
    cube([aper_w, aper_h, panel_t + 1.0]);
  // optional screw holes
  if (screw_holes)
    for (sx = [-screw_spacing/2, screw_spacing/2])
      translate([sx, aper_yc, pocket_depth - panel_t - 0.5])
        cylinder(d = screw_dia, h = panel_t + 1.0);
}
