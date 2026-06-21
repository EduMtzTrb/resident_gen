# -*- coding: utf-8 -*-
# MaCAD S.3 - Double-L Residential Massing Generator
# GHPython component / Rhino 8 Script Editor (Python 3)
#
# Generates a massing made from two offset L-shapes sharing a central
# circulation core.  Four residential bars (two per L) surround the core.
#
# MASSING-ONLY — do not connect Residential_Breps to the interior
# layout generator until that component supports four-bar configurations.
#
# INPUTS:
#   building_length   building_width   wing_width   gap_width
#   floors            floor_height     pilotis_height   slab_thickness
#   column_size       grid_x           grid_y
#   core_width        core_depth       offset_distance
#
# OUTPUTS:
#   Ground_Breps   Column_Breps   Residential_Breps   Core_Brep
#   Floor_Breps    Preview_Colors Layer_Names          BGR_Category
#   Bar_Id

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System.Drawing as sd
from Grasshopper.Kernel import GH_RuntimeMessageLevel as RML

# ----------------------------------------------------------------------
# Tolerance
# ----------------------------------------------------------------------
TOL = 0.001
try:
    if sc.doc is not None and sc.doc.ModelAbsoluteTolerance > 0:
        TOL = sc.doc.ModelAbsoluteTolerance
except:
    pass
EPS = TOL * 5.0

# Minimum face-segment overlap depth for a real bar/core connection.
# Fixed at 0.10 m — deliberately independent of model tolerance so the
# auto-extension threshold stays at gap_width + 2*CONN regardless of the
# Rhino document unit or tolerance setting.
CONN = 0.10

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def warn(msg):
    try:
        ghenv.Component.AddRuntimeMessage(RML.Warning, msg)
    except:
        pass

def dflt(v, d):
    return d if v is None else v

def box_brep(x0, x1, y0, y1, z0, z1):
    if x1 < x0: x0, x1 = x1, x0
    if y1 < y0: y0, y1 = y1, y0
    if z1 < z0: z0, z1 = z1, z0
    if min(x1 - x0, y1 - y0, z1 - z0) < EPS:
        return None
    return rg.Box(
        rg.Plane.WorldXY,
        rg.Interval(x0, x1),
        rg.Interval(y0, y1),
        rg.Interval(z0, z1)
    ).ToBrep()

def aabb(b):
    return b.GetBoundingBox(True)

def linspace(a, b, n):
    if n <= 1: return [0.5 * (a + b)]
    s = (b - a) / float(n - 1)
    return [a + i * s for i in range(n)]

# ----------------------------------------------------------------------
# Inputs — safe defaults
# ----------------------------------------------------------------------
building_length  = float(dflt(building_length,  24.0))
building_width   = float(dflt(building_width,   24.0))
wing_width       = float(dflt(wing_width,        6.0))
gap_width        = float(dflt(gap_width,         4.0))
floors           = int(dflt(floors,              4))
floor_height     = float(dflt(floor_height,      3.0))
pilotis_height   = float(dflt(pilotis_height,    3.5))
slab_thickness   = float(dflt(slab_thickness,    0.3))
column_size      = float(dflt(column_size,       0.5))
grid_x           = int(dflt(grid_x,             4))
grid_y           = int(dflt(grid_y,             4))
core_width       = float(dflt(core_width,        4.0))
core_depth       = float(dflt(core_depth,        4.0))
offset_distance  = float(dflt(offset_distance,   6.0))

floors  = max(1, floors)
grid_x  = max(2, grid_x)
grid_y  = max(2, grid_y)

# ----------------------------------------------------------------------
# Grasshopper compatibility warning
# ----------------------------------------------------------------------
warn(
    "Double-L mode is massing-only.\n"
    "Do not connect these Residential_Breps to the current interior layout generator yet."
)

# ----------------------------------------------------------------------
# Derived level constants
# ----------------------------------------------------------------------
t          = slab_thickness
ph         = max(pilotis_height, 0.1)
fh         = floor_height
ground_top = t
base_z     = ground_top + ph       # pilotis: separation category only
roof_top   = base_z + floors * fh

L  = building_length   # horizontal bar X-span
W  = building_width    # vertical bar Y-span
ww = wing_width        # cross-section width of every bar
gw = gap_width         # gap between the two L-shapes (= core zone width)
od = offset_distance   # vertical shift applied to L-shape B only (can be negative)

# ----------------------------------------------------------------------
# Bar footprints — two mirrored L-shapes, L-shape B offset in Y by od
#
#   Top view (Y increases upward, od = 0 shown):
#
#   L-shape A                         L-shape B
#
#   Bar 0 ════════════════╗       ╔════════════════ Bar 2
#   x:[0, L]              ║       ║                x:[L+gw, 2L+gw]
#   y:[W, W+ww]           ║       ║                y:[W+od, W+od+ww]
#                    Bar 1 ║       ║ Bar 3
#                x:[L-ww, L]     x:[L+gw, L+gw+ww]
#                y:[0, W]        y:[od, W+od]
#
#   Elbow A: y = W       (L-shape A, unchanged)
#   Elbow B: y = W + od  (L-shape B, shifted by offset_distance)
#   When od = 0 the arrangement is the same mirrored configuration as before.
# ----------------------------------------------------------------------
bar_footprints = [
    (0.0,        L,            W,        W + ww),        # Bar 0: horizontal wing, L-A
    (L - ww,     L,            0.0,      W),              # Bar 1: vertical wing,   L-A
    (L + gw,     2.0*L + gw,   W + od,   W + od + ww),  # Bar 2: horizontal wing, L-B
    (L + gw,     L + gw + ww,  od,       W + od),         # Bar 3: vertical wing,   L-B
]

# ----------------------------------------------------------------------
# Core geometry
#
#   Core X: centred on the gap between L-shape A and L-shape B.
#     core_cx = L + gw/2
#
#   Core Y: centred between the two elbows.
#     left_elbow_y  = W          (L-shape A elbow)
#     right_elbow_y = W + od     (L-shape B elbow, offset)
#     core_cy = 0.5 * (W + W+od) = W + od/2
#
#   The core must overlap into all four bars by at least CONN:
#     X: half_cw > gw/2 + CONN        (reaches left bars past x=L
#                                       and right bars past x=L+gw)
#     Y: half_cd > abs(od)/2 + CONN   (reaches both elbows from the centre)
#       → minimum core_depth = abs(od) + 2*CONN
#
#   Auto-extension fires and issues a warning only when the requested
#   dimension is smaller than the minimum.
# ----------------------------------------------------------------------
core_cx = L + gw * 0.5
left_elbow_y  = W
right_elbow_y = W + od
core_cy = 0.5 * (left_elbow_y + right_elbow_y)   # = W + od/2

half_cw = core_width  * 0.5
half_cd = core_depth  * 0.5

# X auto-extension: must reach both bars' inner faces with CONN margin.
min_half_cw = gw * 0.5 + CONN
if half_cw < min_half_cw:
    warn(
        "core_width %.2f is too narrow to reach all four bars across gap_width %.2f "
        "(need >= %.2f); enlarged to %.2f."
        % (core_width, gw, 2.0 * min_half_cw, 2.0 * min_half_cw)
    )
    half_cw = min_half_cw

# Y auto-extension: must span from left elbow to right elbow with CONN margin each side.
min_half_cd = abs(od) * 0.5 + CONN
if half_cd < min_half_cd:
    warn(
        "core_depth %.2f is too shallow to reach all four bars with offset_distance %.2f "
        "(need >= %.2f); enlarged to %.2f."
        % (core_depth, od, 2.0 * min_half_cd, 2.0 * min_half_cd)
    )
    half_cd = min_half_cd

core_x0 = core_cx - half_cw
core_x1 = core_cx + half_cw
core_y0 = core_cy - half_cd
core_y1 = core_cy + half_cd

# ----------------------------------------------------------------------
# Output initialisation
# ----------------------------------------------------------------------
Ground_Breps      = []
Column_Breps      = []
Residential_Breps = []
Core_Brep         = []
Floor_Breps       = []
Bar_Id            = []

# ----------------------------------------------------------------------
# Residential bars — one Brep per bar per floor
# Bar loop is identical to Task 3; core does not alter Residential_Breps.
# ----------------------------------------------------------------------
invalid_res = 0
for fi in range(floors):
    z0 = base_z + fi * fh
    z1 = z0 + fh
    for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
        b = box_brep(bx0, bx1, by0, by1, z0, z1)
        if b is None or not b.IsValid or not b.IsSolid:
            warn("Bar %d floor %d: invalid Brep." % (bid, fi))
            invalid_res += 1
            continue
        Residential_Breps.append(b)
        Bar_Id.append(bid)

# ----------------------------------------------------------------------
# Core — one continuous solid from ground to roof
#
# z0 = 0.0      (top face of Ground_Breps, where pilotis columns begin)
# z1 = roof_top (top of the building)
# Core_Brep count = 1  (replaces the previous per-floor approach)
# Separate core slabs in Floor_Breps and the core ground slab in
# Ground_Breps are unaffected.
# ----------------------------------------------------------------------
invalid_core = 0
cb = box_brep(core_x0, core_x1, core_y0, core_y1, 0.0, roof_top)
if cb is None or not cb.IsValid or not cb.IsSolid:
    warn("Core: invalid Brep — check core_width, core_depth.")
    invalid_core += 1
else:
    Core_Brep.append(cb)

# ----------------------------------------------------------------------
# Floor slabs — four bar slabs + one core slab per floor
#
# Order within each floor: Bar 0, Bar 1, Bar 2, Bar 3, Core.
# slab_z0 = base_z + fi*fh         (bottom face of this floor)
# slab_z1 = slab_z0 + t            (slab top, t = slab_thickness)
# Overlap at core/bar joints is intentional; no Boolean ops at this stage.
# ----------------------------------------------------------------------
invalid_slab = 0
for fi in range(floors):
    slab_z0 = base_z + fi * fh
    slab_z1 = slab_z0 + t
    for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
        sb = box_brep(bx0, bx1, by0, by1, slab_z0, slab_z1)
        if sb is None or not sb.IsValid or not sb.IsSolid:
            warn("Bar %d slab floor %d: invalid Brep." % (bid, fi))
            invalid_slab += 1
            continue
        Floor_Breps.append(sb)
    core_sb = box_brep(core_x0, core_x1, core_y0, core_y1, slab_z0, slab_z1)
    if core_sb is None or not core_sb.IsValid or not core_sb.IsSolid:
        warn("Core slab floor %d: invalid Brep." % fi)
        invalid_slab += 1
        continue
    Floor_Breps.append(core_sb)

# ----------------------------------------------------------------------
# Pilotis columns — all four bar footprints, z = 0 → base_z
#
# Grid: grid_x × grid_y centres distributed across each bar, with
# outer columns flush inside the bar edge (centre = edge + cs/2).
# Deduplication: a (rounded-x, rounded-y) key set prevents columns
# appearing twice at L elbows or anywhere two bars share a corner.
# Core exclusion zone: the core footprint expanded by cs/2 on every
# side; any column centre inside that zone is skipped.
# ----------------------------------------------------------------------
cs   = column_size
cz0  = 0.0        # column bottom: actual ground
cz1  = base_z     # column top:    underside of first residential slab

# Expanded core exclusion zone.
exc_x0 = core_x0 - cs * 0.5
exc_x1 = core_x1 + cs * 0.5
exc_y0 = core_y0 - cs * 0.5
exc_y1 = core_y1 + cs * 0.5

placed_keys = set()   # (round(x,3), round(y,3)) — deduplication across all bars
invalid_col  = 0

for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
    if (bx1 - bx0) < cs + EPS or (by1 - by0) < cs + EPS:
        warn("Bar %d footprint too narrow for column_size %.2f; columns skipped." % (bid, cs))
        continue
    xs = linspace(bx0 + cs * 0.5, bx1 - cs * 0.5, grid_x)
    ys = linspace(by0 + cs * 0.5, by1 - cs * 0.5, grid_y)
    for x in xs:
        for y in ys:
            # Skip if inside expanded core exclusion zone.
            if exc_x0 <= x <= exc_x1 and exc_y0 <= y <= exc_y1:
                continue
            # Skip duplicates (shared elbow corners between bars).
            key = (round(x, 3), round(y, 3))
            if key in placed_keys:
                continue
            placed_keys.add(key)
            col = box_brep(x - cs*0.5, x + cs*0.5,
                           y - cs*0.5, y + cs*0.5,
                           cz0, cz1)
            if col is None or not col.IsValid or not col.IsSolid:
                warn("Column at (%.3f,%.3f): invalid Brep." % (x, y))
                invalid_col += 1
                continue
            Column_Breps.append(col)

# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------
exp_res  = floors * 4
exp_core = 1            # one continuous core solid (z=0 → roof_top)
exp_slab = floors * 5   # 4 bar slabs + 1 core slab per floor

if len(Residential_Breps) != exp_res:
    warn("Residential_Breps count %d != expected %d." % (len(Residential_Breps), exp_res))
if len(Bar_Id) != len(Residential_Breps):
    warn("Bar_Id length %d != Residential_Breps length %d — not parallel."
         % (len(Bar_Id), len(Residential_Breps)))
if len(Core_Brep) != exp_core:
    warn("Core_Brep count %d != expected %d (one per floor)."
         % (len(Core_Brep), exp_core))
if len(Floor_Breps) != exp_slab:
    warn("Floor_Breps count %d != expected %d (%d floors x 5)."
         % (len(Floor_Breps), exp_slab, floors))

# Per-bar XY connection check: verify core footprint overlaps each bar footprint.
conn_ok = [False, False, False, False]
for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
    ox = min(core_x1, bx1) - max(core_x0, bx0)
    oy = min(core_y1, by1) - max(core_y0, by0)
    if ox > EPS and oy > EPS:
        conn_ok[bid] = True
    else:
        warn("Core does not reach Bar %d (ox=%.4f oy=%.4f)." % (bid, ox, oy))

if not Column_Breps:
    warn("Column_Breps is empty — check column_size vs bar dimensions.")

# ----------------------------------------------------------------------
# Ground slabs — one per bar + one for core, sitting below world Z=0
#
# z0 = -t  (slab bottom, below world ground)
# z1 =  0  (slab top flush with world Z=0 where pilotis columns begin)
# Order: Bar 0, Bar 1, Bar 2, Bar 3, Core
# Overlap at core/bar joints is intentional; no Boolean ops at this stage.
# ----------------------------------------------------------------------
gs_z0 = -t
gs_z1 = 0.0
invalid_gnd = 0
for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
    gs = box_brep(bx0, bx1, by0, by1, gs_z0, gs_z1)
    if gs is None or not gs.IsValid or not gs.IsSolid:
        warn("Bar %d ground slab: invalid Brep." % bid)
        invalid_gnd += 1
        continue
    Ground_Breps.append(gs)
core_gs = box_brep(core_x0, core_x1, core_y0, core_y1, gs_z0, gs_z1)
if core_gs is None or not core_gs.IsValid or not core_gs.IsSolid:
    warn("Core ground slab: invalid Brep.")
    invalid_gnd += 1
else:
    Ground_Breps.append(core_gs)

if len(Ground_Breps) != 5:
    warn("Ground_Breps count %d != expected 5." % len(Ground_Breps))

# ----------------------------------------------------------------------
# Preview metadata
# ----------------------------------------------------------------------
CORE_COLOR = sd.Color.FromArgb(220, 190,  60)   # gold / amber for core

Preview_Colors = [
    sd.Color.FromArgb(70,  130, 200),   # Bar 0 — blue
    sd.Color.FromArgb(80,  180, 100),   # Bar 1 — green
    sd.Color.FromArgb(210, 120,  50),   # Bar 2 — orange
    sd.Color.FromArgb(200,  60,  60),   # Bar 3 — red
    CORE_COLOR,                          # Core  — gold
]
Layer_Names  = ["L_A_Horizontal", "L_A_Vertical", "L_B_Horizontal", "L_B_Vertical", "Core"]
BGR_Category = "Double-L_Core_Test"

# ----------------------------------------------------------------------
# Console report
# ----------------------------------------------------------------------
print("Double-L massing — Task 6: continuous core + offset L-shape B.")
print("Inputs:")
print("  building_length=%.2f  building_width=%.2f" % (L, W))
print("  wing_width=%.2f       gap_width=%.2f  offset_distance=%.2f" % (ww, gw, od))
print("  core_width=%.2f       core_depth=%.2f" % (core_width, core_depth))
print("  floors=%d  floor_height=%.2f  base_z=%.3f" % (floors, fh, base_z))
print("Core footprint:")
print("  centre x=%.3f  y=%.3f  (left_elbow_y=%.2f  right_elbow_y=%.2f)"
      % (core_cx, core_cy, left_elbow_y, right_elbow_y))
print("  x=[%.3f, %.3f]  y=[%.3f, %.3f]" % (core_x0, core_x1, core_y0, core_y1))
print("  half_cw=%.3f (requested %.3f)  half_cd=%.3f (requested %.3f)"
      % (half_cw, core_width*0.5, half_cd, core_depth*0.5))
print("  z=[0.000, %.3f]  (ground → roof_top)  count=%d" % (roof_top, len(Core_Brep)))
print("Bar connections (core overlaps each bar in XY):")
for bid, ok in enumerate(conn_ok):
    bx0, bx1, by0, by1 = bar_footprints[bid]
    ox = min(core_x1, bx1) - max(core_x0, bx0)
    oy = min(core_y1, by1) - max(core_y0, by0)
    print("  Bar %d: %s  overlap x=%.3f  y=%.3f" % (bid, "OK" if ok else "FAIL", ox, oy))
print("Residential_Breps : %d  (expected %d)  invalid=%d"
      % (len(Residential_Breps), exp_res, invalid_res))
print("Bar_Id            : %d  — %s"
      % (len(Bar_Id), ("parallel OK" if len(Bar_Id) == len(Residential_Breps) else "MISMATCH")))
print("Core_Brep         : %d  (expected %d)  invalid=%d"
      % (len(Core_Brep), exp_core, invalid_core))
print("Floor_Breps       : %d  (expected %d = %d floors x 5)  invalid=%d"
      % (len(Floor_Breps), exp_slab, floors, invalid_slab))
print("  slab order/floor: Bar0 Bar1 Bar2 Bar3 Core")
print("  slab z placement: slab_z0 = base_z + fi*fh  slab_z1 = slab_z0 + t (t=%.3f)" % t)
print("Column_Breps      : %d  (invalid=%d  duplicates/core-excluded removed)"
      % (len(Column_Breps), invalid_col))
print("  column z: [%.3f, %.3f]  (ground → base_z)" % (cz0, cz1))
print("  core excl zone: x=[%.3f,%.3f]  y=[%.3f,%.3f]" % (exc_x0, exc_x1, exc_y0, exc_y1))
print("Ground_Breps      : %d  (expected 5)  invalid=%d" % (len(Ground_Breps), invalid_gnd))
print("  ground slab order: Bar0 Bar1 Bar2 Bar3 Core")
print("  ground slab z: [%.3f, 0.000]  (-slab_thickness → world Z=0)" % gs_z0)
