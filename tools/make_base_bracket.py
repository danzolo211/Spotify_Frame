#!/usr/bin/env python3
"""
Generate USBC_Base_Bracket.stl  -- a small printable holder that seats a
panel-mount USB-C female jack in the OPEN bottom-center of V_2_Daniel_Weber_Stand.

Why these numbers (all measured from V_2_Daniel_Weber_Stand.stl, in mm):
  * Pocket depth (front-bezel inner face Z=3.2 -> back plane Z=25.4) = ~22.2 mm.
    The bracket is DEPTH mm deep so it wedges: pushing a plug in shoves it toward
    the FRONT bezel (a solid wall), so it can't drift inward. -> POCKET_DEPTH.
  * The back wall is OPEN across the bottom-center (X ~15..138 mm), so the jack
    faces rearward and the cable exits behind the base ("behind the ground surface").
  * Pocket interior is ~103 mm wide; a ~24 mm bracket centered at X=76 sits clear
    of both side walls and rests on the internal shelf (~7.5 mm).

The jack is held by a rectangular aperture in the rear panel (friction) + a drop of
hot glue if you want it permanent. Two side gussets brace the panel to the floor so
plug-in force can't snap it.

*** TUNE THESE to YOUR jack, then re-run:  python tools/make_base_bracket.py ***
"""

# ---- tunables (mm) -------------------------------------------------------
POCKET_DEPTH = 22.0   # front-to-back; keep = pocket depth so it wedges on the bezel
WIDTH        = 24.0   # left-right footprint
HEIGHT       = 16.0   # rear panel height
FLOOR_T      = 3.0    # floor thickness (rests on the pocket shelf)
PANEL_T      = 3.0    # rear panel thickness (where the jack mounts)

APER_W       = 12.0   # jack aperture width  (measure your jack body + ~0.5 mm)
APER_H       = 8.0    # jack aperture height
APER_YC      = 8.0    # aperture center height above the floor

RAIL_T       = 2.5    # side-rail thickness (stiffener + shelf contact)
RAIL_H       = 6.0    # side-rail height
GUSSET_L     = 8.0    # gusset reach forward from the panel
GUSSET_H     = 13.0   # gusset height up the panel

OUT_STL = "USBC_Base_Bracket.stl"
# --------------------------------------------------------------------------

tris = []  # each tri = (v0, v1, v2), CCW seen from outside

def quad(a, b, c, d):
    tris.append((a, b, c)); tris.append((a, c, d))

def box(x0, x1, y0, y1, z0, z1):
    """Closed axis-aligned cuboid with outward normals."""
    p = lambda x, y, z: (x, y, z)
    # bottom (y0, normal -Y)
    quad(p(x0,y0,z0), p(x1,y0,z0), p(x1,y0,z1), p(x0,y0,z1))
    # top (y1, +Y)
    quad(p(x0,y1,z0), p(x0,y1,z1), p(x1,y1,z1), p(x1,y1,z0))
    # front (z0, -Z)
    quad(p(x0,y0,z0), p(x0,y1,z0), p(x1,y1,z0), p(x1,y0,z0))
    # back (z1, +Z)
    quad(p(x0,y0,z1), p(x1,y0,z1), p(x1,y1,z1), p(x0,y1,z1))
    # left (x0, -X)
    quad(p(x0,y0,z0), p(x0,y0,z1), p(x0,y1,z1), p(x0,y1,z0))
    # right (x1, +X)
    quad(p(x1,y0,z0), p(x1,y1,z0), p(x1,y1,z1), p(x1,y0,z1))

def gusset(x0, x1, zf, yb, gl, gh):
    """Right-triangle prism (brace). Triangle in (Z,Y): (zf,yb)-(zf,yb+gh)-(zf-gl,yb).
    Spanned across X in [x0,x1]. zf = panel front face."""
    A = lambda x: (x, yb,      zf)
    B = lambda x: (x, yb+gh,   zf)
    C = lambda x: (x, yb,      zf-gl)
    # two triangular caps
    tris.append((A(x0), C(x0), B(x0)))   # -X cap
    tris.append((A(x1), B(x1), C(x1)))   # +X cap
    # three quad sides
    quad(A(x0), B(x0), B(x1), A(x1))     # vertical face (panel side)
    quad(A(x1), C(x1), C(x0), A(x0))     # bottom face
    quad(B(x0), C(x0), C(x1), B(x1))     # hypotenuse
    # NOTE: overlapping boxes/prisms are fine -- the slicer unions them.

D  = POCKET_DEPTH
hw = WIDTH / 2.0
zp0, zp1 = D - PANEL_T, D            # rear panel spans this Z band
ax0, ax1 = -APER_W/2.0, APER_W/2.0   # aperture X
ay0, ay1 = APER_YC - APER_H/2.0, APER_YC + APER_H/2.0  # aperture Y

# floor (full depth, rests on shelf)
box(-hw, hw, 0.0, FLOOR_T, 0.0, D)
# rear panel built as 4 bars framing the aperture (leaves a clean rectangular hole)
box(-hw, ax0, 0.0, HEIGHT, zp0, zp1)          # left of aperture
box(ax1,  hw, 0.0, HEIGHT, zp0, zp1)          # right of aperture
box(ax0, ax1, 0.0, ay0,    zp0, zp1)          # below aperture
box(ax0, ax1, ay1, HEIGHT, zp0, zp1)          # above aperture
# side rails (stiffen + rest on shelf)
box(-hw, -hw+RAIL_T, 0.0, RAIL_H, 0.0, D)
box( hw-RAIL_T,  hw, 0.0, RAIL_H, 0.0, D)
# side gussets (brace panel to floor; kept at the edges so they clear the jack body)
gusset(-hw, -hw+RAIL_T, zp0, FLOOR_T, GUSSET_L, GUSSET_H)
gusset( hw-RAIL_T,  hw, zp0, FLOOR_T, GUSSET_L, GUSSET_H)

def write_ascii_stl(path, tris):
    def n(a, b, c):
        ux,uy,uz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
        vx,vy,vz = c[0]-a[0], c[1]-a[1], c[2]-a[2]
        nx,ny,nz = uy*vz-uz*vy, uz*vx-ux*vz, ux*vy-uy*vx
        m = (nx*nx+ny*ny+nz*nz) ** 0.5 or 1.0
        return nx/m, ny/m, nz/m
    with open(path, "w") as f:
        f.write("solid usbc_base_bracket\n")
        for a,b,c in tris:
            nx,ny,nz = n(a,b,c)
            f.write(f"  facet normal {nx:.5f} {ny:.5f} {nz:.5f}\n    outer loop\n")
            for v in (a,b,c):
                f.write(f"      vertex {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}\n")
            f.write("    endloop\n  endfacet\n")
        f.write("endsolid usbc_base_bracket\n")

if __name__ == "__main__":
    write_ascii_stl(OUT_STL, tris)
    print(f"wrote {OUT_STL}: {len(tris)} triangles")
    print(f"footprint {WIDTH} x {POCKET_DEPTH} mm, height {HEIGHT} mm, "
          f"aperture {APER_W} x {APER_H} @ y={APER_YC}")
