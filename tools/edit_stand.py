#!/usr/bin/env python3
"""
Edit V_2_Daniel_Weber_Stand.stl -> V_3_Daniel_Weber_Stand.stl (millimeters).

Integrated Aura-style electronics bay:
  * USB-C PORT through the back wall (bottom-center) for the GELRHONR
    right-angle USB-C-female->2-pin adapter (female faces out the back).
  * ADAPTER CRADLE: tray fused to the back wall, terminal points up.
  * ESP HOLDER: tray fused to the back wall, board drops in.
  * WIRE RELIEF: a channel carved into the connector-side wall so the display's
    ribbon/jumpers can bend back (the module is a glove-fit widthwise).

Measured stand geometry (mm, point-in-mesh): BACK_OUT=0.13 BACK_IN=3.07
SHELF_Y=7.3  SIDE_L=24.7 SIDE_R=128.3  CAV_TOP=89  clear cavity depth ~17mm.

REAL part sizes (from datasheet/photos):
  Display module 103.0 x 78.5 mm (active 84.8 x 63.6).  ESP32-S3 58 x 28 mm.
  Adapter 24 mm tall x 10 mm terminal (right-angle); depth ~15mm EST.

Output STL is real millimeters (import normally; no x25.4).
"""
import trimesh, numpy as np

SRC, OUT, ENG = "V_2_Daniel_Weber_Stand.stl", "V_3_Daniel_Weber_Stand.stl", "manifold"

# ---- deepen the frame for a comfortable electronics bay ----
DEEPEN = 7.0     # mm added to the back (cavity ~17 -> ~24mm)
ZCUT   = 12.0    # everything behind this Z moves back; front rim/seat stay put

# ---- measured stand geometry (mm); back faces shift back by DEEPEN ----
BACK_OUT, BACK_IN = 0.13 - DEEPEN, 3.07 - DEEPEN   # -> -6.87, -3.93
SHELF_Y = 7.3
SIDE_L, SIDE_R = 24.7, 128.3
CX = (SIDE_L + SIDE_R) / 2.0            # 76.5

# ---- adapter (GELRHONR right-angle; confirm DEPTH) ----
ADP_W, ADP_H, ADP_D = 13.0, 24.0, 15.0  # X, Y, Z(depth)  DEPTH must be < ~16
USB_OPEN_W, USB_OPEN_H = 10.0, 5.0      # port cut
PORT_Y = 14.0                           # low on the back (USB-C is at the L's foot)

# ---- ESP32-S3 dev board ----
ESP_L, ESP_W, ESP_T = 58.0, 28.0, 5.0   # X, Y, tray depth (board seats; pins go forward)
ESP_CY = 60.0

# ---- display + wire relief ----
DISP_W, DISP_H = 103.0, 78.5
CONN_SIDE = "right"          # which display edge the 8-pin connector sits on
RELIEF_W = 12.0             # channel width into the side wall
RELIEF_Y0, RELIEF_Y1 = 26.0, 78.0

WALL, CLR = 2.2, 0.6

def box(x0,x1,y0,y1,z0,z1):
    T=np.eye(4); T[:3,3]=[(x0+x1)/2,(y0+y1)/2,(z0+z1)/2]
    return trimesh.creation.box(extents=[x1-x0,y1-y0,z1-z0], transform=T)

def tray(cx,cy,iw,ih,back_z,depth,wall=WALL,lip=1.2):
    x0,x1=cx-iw/2,cx+iw/2; y0,y1=cy-ih/2,cy+ih/2; zf=back_z+depth
    P=[box(x0-wall,x1+wall,y0-wall,y1+wall,BACK_IN-1.0,back_z+wall)]      # back plate
    P+=[box(x0-wall,x0,y0-wall,y1+wall,back_z,zf), box(x1,x1+wall,y0-wall,y1+wall,back_z,zf)]  # L/R
    P+=[box(x0-wall,x1+wall,y0-wall,y0,back_z,zf), box(x0-wall,x1+wall,y1,y1+wall,back_z,zf)]  # B/T
    if lip>0:
        P+=[box(x0-wall,x1+wall,y0-wall,y0+lip,zf-wall,zf), box(x0-wall,x1+wall,y1-lip,y1+wall,zf-wall,zf)]
    return P

def deepen(m):
    """Extend the frame back by DEEPEN mm: translate everything behind ZCUT,
    which stretches the side/top/bottom walls and moves the back wall back;
    the display seat and front rim (Z>=ZCUT) stay exactly put."""
    V=m.vertices.copy()
    V[V[:,2] < ZCUT, 2] -= DEEPEN
    return trimesh.Trimesh(vertices=V, faces=m.faces.copy(), process=True)

def main():
    m=trimesh.load(SRC); m.apply_scale(25.4)
    m=deepen(m)
    adds=[]
    adds+=tray(CX, SHELF_Y+ADP_H/2+0.8, ADP_W+CLR, ADP_H+CLR, BACK_IN, ADP_D, lip=1.0)  # adapter
    adds+=tray(CX, ESP_CY, ESP_L+CLR, ESP_W+CLR, BACK_IN, ESP_T, lip=1.6)               # ESP
    body=trimesh.boolean.union([m]+adds, engine=ENG)

    cuts=[]
    # USB-C port through back wall + cradle back plate
    cuts.append(box(CX-USB_OPEN_W/2, CX+USB_OPEN_W/2, PORT_Y-USB_OPEN_H/2, PORT_Y+USB_OPEN_H/2,
                    BACK_OUT-1.0, BACK_IN+1.5))
    # wire-relief channel in the connector-side wall (behind the front rim only)
    if CONN_SIDE=="right":
        cuts.append(box(SIDE_R-4.0, SIDE_R+RELIEF_W, RELIEF_Y0, RELIEF_Y1, BACK_IN, 18.0))
    else:
        cuts.append(box(SIDE_L-RELIEF_W, SIDE_L+4.0, RELIEF_Y0, RELIEF_Y1, BACK_IN, 18.0))
    body=trimesh.boolean.difference([body]+cuts, engine=ENG)

    body.export(OUT)
    print(f"{OUT}: faces={len(body.faces)} watertight={body.is_watertight} "
          f"vol={body.volume:.0f} bounds={np.round(body.bounds,1).tolist()}")

if __name__=="__main__":
    main()
