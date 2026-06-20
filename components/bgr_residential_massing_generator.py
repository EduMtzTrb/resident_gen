# -*- coding: utf-8 -*-
# MaCAD S.3 - Graph ML Assignment 3
# Parametric residential building - Building-Ground Relationship (BGR) generator
# GHPython component (IronPython 2.7 / RhinoCommon)
#
# Outputs four closed-solid groups whose names match the Assignment 3 notebook:
#   ground / columns / offices (residential) / core
#
# BGR selector (bgr_category):
#   0 Separation              1 Separation with Plinth
#   2 Adherence               3 Adherence with Plinth
#   4 Interlock

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

def warn(msg):
    try:
        ghenv.Component.AddRuntimeMessage(RML.Warning, msg)
    except:
        pass

# ----------------------------------------------------------------------
# Defaults so the component runs with unconnected inputs
# ----------------------------------------------------------------------
def dflt(v, d):
    return d if v is None else v

building_length = float(dflt(building_length, 24.0))
building_width  = float(dflt(building_width, 12.0))
floors          = int(dflt(floors, 4))
floor_height    = float(dflt(floor_height, 3.0))
pilotis_height  = float(dflt(pilotis_height, 3.5))
slab_thickness  = float(dflt(slab_thickness, 0.6))
column_size     = float(dflt(column_size, 0.5))
grid_x          = int(dflt(grid_x, 4))
grid_y          = int(dflt(grid_y, 3))
core_width      = float(dflt(core_width, 4.0))
core_depth      = float(dflt(core_depth, 3.0))
core_position   = int(dflt(core_position, 0))
num_bars        = int(dflt(num_bars, 1))
bgr_category    = int(dflt(bgr_category, 0))

floors   = max(1, floors)
grid_x   = max(2, grid_x)
grid_y   = max(2, grid_y)
num_bars = 2 if num_bars == 2 else 1
if bgr_category < 0 or bgr_category > 4:
    warn("bgr_category out of range; defaulting to 0 (Separation).")
    bgr_category = 0
cat = bgr_category

# ----------------------------------------------------------------------
# Geometry helpers
# ----------------------------------------------------------------------
def box_brep(x0, x1, y0, y1, z0, z1):
    if x1 < x0: x0, x1 = x1, x0
    if y1 < y0: y0, y1 = y1, y0
    if z1 < z0: z0, z1 = z1, z0
    bx = rg.Box(rg.Plane.WorldXY,
                rg.Interval(x0, x1),
                rg.Interval(y0, y1),
                rg.Interval(z0, z1))
    return bx.ToBrep()

def subtract(base, cutter):
    res = rg.Brep.CreateBooleanDifference([base], [cutter], TOL)
    if res is None or len(res) == 0:
        warn("Boolean difference failed; kept original solid (check core size).")
        return base
    if len(res) == 1:
        return res[0]
    joined = rg.Brep.JoinBreps(res, TOL)
    return joined[0] if (joined and len(joined) > 0) else res[0]

def linspace(a, b, n):
    if n <= 1:
        return [0.5 * (a + b)]
    s = (b - a) / float(n - 1)
    return [a + i * s for i in range(n)]

# ----------------------------------------------------------------------
# Level logic driven by the BGR category
# ----------------------------------------------------------------------
L  = building_length
W  = building_width
t  = slab_thickness
fh = floor_height
ph = max(pilotis_height, 0.1)
cs = column_size

has_columns  = cat in (0, 1)
has_plinth   = cat in (1, 3)
is_interlock = (cat == 4)

plinth_h    = fh          # derived: one-storey podium
embed_depth = fh          # derived: one storey embedded (interlock)

# ground slab must be deep enough to hold the interlock pit
if is_interlock and t < embed_depth + 0.2 * fh:
    t = embed_depth + 0.2 * fh

ground_top  = t
plinth_top  = ground_top + plinth_h if has_plinth else ground_top
support_top = plinth_top   # columns / volume bear on this level

if   cat == 0: base_z = ground_top + ph           # separation
elif cat == 1: base_z = plinth_top + ph           # separation + plinth
elif cat == 2: base_z = ground_top                # adherence
elif cat == 3: base_z = plinth_top                # adherence + plinth
elif cat == 4: base_z = ground_top - embed_depth  # interlock
else:          base_z = ground_top + ph

roof_top = base_z + floors * fh

# ----------------------------------------------------------------------
# Footprints
# ----------------------------------------------------------------------
gm = max(L, W) * 0.30      # ground apron margin
pm = max(L, W) * 0.12      # plinth margin (< gm so ground covers plinth)
g_x0, g_x1 = -gm, L + gm
g_y0, g_y1 = -gm, W + gm

cw = min(core_width, L * 0.5)
cd = min(core_depth, W * 0.6)

bars = []          # list of (x0,x1,y0,y1)
core_in_gap = False
if num_bars == 1:
    bars.append((0.0, L, 0.0, W))
    core_x0, core_x1 = 0.5 * (L - cw), 0.5 * (L + cw)
    core_y0, core_y1 = 0.5 * (W - cd), 0.5 * (W + cd)
else:
    gap = cd
    bar_depth = 0.5 * (W - gap)
    if bar_depth <= 0.5:
        warn("core_depth too large for two bars; reverting to one bar.")
        num_bars = 1
        bars.append((0.0, L, 0.0, W))
        core_x0, core_x1 = 0.5 * (L - cw), 0.5 * (L + cw)
        core_y0, core_y1 = 0.5 * (W - cd), 0.5 * (W + cd)
    else:
        bars.append((0.0, L, 0.0, bar_depth))
        bars.append((0.0, L, W - bar_depth, W))
        core_x0, core_x1 = 0.5 * (L - cw), 0.5 * (L + cw)
        core_y0, core_y1 = bar_depth, W - bar_depth
        core_in_gap = True

core_z0 = base_z if is_interlock else ground_top
core_z1 = roof_top

# ----------------------------------------------------------------------
# RESIDENTIAL VOLUME (one closed solid per floor per bar)
# ----------------------------------------------------------------------
residential = []
for fi in range(floors):
    z0 = base_z + fi * fh
    z1 = z0 + fh
    for (bx0, bx1, by0, by1) in bars:
        fb = box_brep(bx0, bx1, by0, by1, z0, z1)
        if not core_in_gap:   # central core: notch it out of each floor
            cutter = box_brep(core_x0, core_x1, core_y0, core_y1, z0 - EPS, z1 + EPS)
            fb = subtract(fb, cutter)
        residential.append(fb)

# ----------------------------------------------------------------------
# FLOOR SLABS (bar slabs + core slab per floor)
# Bar slabs: one per bar per floor, no core hole (core slab is separate).
# Core slab: one per floor, matching Core_Brep X/Y footprint exactly.
# Slab bottom = base_z + fi * fh; thickness = t.
# ----------------------------------------------------------------------
floor_breps = []
for fi in range(floors):
    slab_z0 = base_z + fi * fh
    slab_z1 = slab_z0 + t
    for (bx0, bx1, by0, by1) in bars:
        sb = box_brep(bx0, bx1, by0, by1, slab_z0, slab_z1)
        if sb:
            floor_breps.append(sb)
    core_sb = box_brep(core_x0, core_x1, core_y0, core_y1, slab_z0, slab_z1)
    if core_sb:
        floor_breps.append(core_sb)

# ----------------------------------------------------------------------
# CORE (single vertical closed solid, ground -> roof)
# ----------------------------------------------------------------------
core_breps = [box_brep(core_x0, core_x1, core_y0, core_y1, core_z0, core_z1)]

# ----------------------------------------------------------------------
# PLINTH (assigned to the GROUND group; notch the core through it)
# ----------------------------------------------------------------------
plinth_breps = []
if has_plinth:
    pb = box_brep(-pm, L + pm, -pm, W + pm, ground_top, plinth_top)
    cutter = box_brep(core_x0, core_x1, core_y0, core_y1, ground_top - EPS, plinth_top + EPS)
    pb = subtract(pb, cutter)
    plinth_breps.append(pb)

# ----------------------------------------------------------------------
# GROUND SLAB (+ interlock pit)
# ----------------------------------------------------------------------
ground = box_brep(g_x0, g_x1, g_y0, g_y1, 0.0, ground_top)
if is_interlock:
    for (bx0, bx1, by0, by1) in bars:
        cutter = box_brep(bx0, bx1, by0, by1, base_z - EPS, ground_top + EPS)
        ground = subtract(ground, cutter)
ground_breps = [ground] + plinth_breps

# ----------------------------------------------------------------------
# COLUMNS (only for separation categories)
# ----------------------------------------------------------------------
column_breps = []
piloti_report = []
if has_columns:
    cz0, cz1 = support_top, base_z
    placed = []   # (cx, cy) for deduplication across bars

    for (bx0, bx1, by0, by1) in bars:
        # Perimeter piloti outer face flush with bar wall.
        # Column centre sits cs/2 inward so outer_face = centre - cs/2 = bar_edge.
        if (bx1 - bx0) < cs + EPS or (by1 - by0) < cs + EPS:
            warn("Bar (%.2f,%.2f)-(%.2f,%.2f) too narrow for columns; skipped." % (bx0, by0, bx1, by1))
            continue
        xs = linspace(bx0 + cs*0.5, bx1 - cs*0.5, grid_x)
        ys = linspace(by0 + cs*0.5, by1 - cs*0.5, grid_y)
        for x in xs:
            for y in ys:
                # skip under the core footprint
                if (core_x0 - cs <= x <= core_x1 + cs) and (core_y0 - cs <= y <= core_y1 + cs):
                    continue
                # skip duplicate positions (shared corners between bars)
                if any(abs(x - px) < EPS and abs(y - py) < EPS for px, py in placed):
                    continue
                placed.append((x, y))
                column_breps.append(box_brep(x - cs*0.5, x + cs*0.5,
                                             y - cs*0.5, y + cs*0.5,
                                             cz0, cz1))

    # Corner verification report (flush outer-face check)
    shared_corners = []
    for bi, (bx0, bx1, by0, by1) in enumerate(bars):
        exp_corners = [
            (bx0 + cs*0.5, by0 + cs*0.5),   # SW: west face=bx0, south face=by0
            (bx1 - cs*0.5, by0 + cs*0.5),   # SE: east face=bx1, south face=by0
            (bx0 + cs*0.5, by1 - cs*0.5),   # NW: west face=bx0, north face=by1
            (bx1 - cs*0.5, by1 - cs*0.5),   # NE: east face=bx1, north face=by1
        ]
        bar_pts = [(px, py) for (px, py) in placed
                   if bx0 - EPS <= px <= bx1 + EPS and by0 - EPS <= py <= by1 + EPS]
        missing = [c for c in exp_corners
                   if not any(abs(c[0]-px) < EPS and abs(c[1]-py) < EPS for px, py in bar_pts)]
        piloti_report.append(
            "Bar %d (%.2f,%.2f)-(%.2f,%.2f): %d pilotis, outer-faces-flush=YES, corners=%s" % (
                bi + 1, bx0, by0, bx1, by1, len(bar_pts),
                "YES" if not missing else "MISSING %s" % str(missing)))
    if len(bars) == 2:
        c1s = [(bars[0][0]+cs*0.5, bars[0][2]+cs*0.5),
               (bars[0][1]-cs*0.5, bars[0][2]+cs*0.5),
               (bars[0][0]+cs*0.5, bars[0][3]-cs*0.5),
               (bars[0][1]-cs*0.5, bars[0][3]-cs*0.5)]
        c2s = [(bars[1][0]+cs*0.5, bars[1][2]+cs*0.5),
               (bars[1][1]-cs*0.5, bars[1][2]+cs*0.5),
               (bars[1][0]+cs*0.5, bars[1][3]-cs*0.5),
               (bars[1][1]-cs*0.5, bars[1][3]-cs*0.5)]
        for (ax, ay) in c1s:
            for (bx, by) in c2s:
                if abs(ax - bx) < EPS and abs(ay - by) < EPS:
                    shared_corners.append((ax, ay))
        piloti_report.append("Shared/duplicate corners: %s" % (shared_corners if shared_corners else "none"))

# ----------------------------------------------------------------------
# VALIDATION
# ----------------------------------------------------------------------
def validate(breps, name):
    ok = True
    for i, b in enumerate(breps):
        if b is None or not b.IsValid:
            warn("%s[%d] is null/invalid." % (name, i)); ok = False
        elif not b.IsSolid:
            warn("%s[%d] is not a closed solid." % (name, i)); ok = False
    return ok

all_ok = True
all_ok = all_ok and validate(ground_breps, "ground")
all_ok = all_ok and validate(column_breps, "columns")
all_ok = all_ok and validate(residential,  "offices")
all_ok = all_ok and validate(core_breps,   "core")
all_ok = all_ok and validate(floor_breps,  "floor_slabs")

# ----------------------------------------------------------------------
# OUTPUTS
# ----------------------------------------------------------------------
Ground_Breps      = ground_breps
Column_Breps      = column_breps
Residential_Breps = residential
Core_Brep         = core_breps
Floor_Breps       = floor_breps

Preview_Colors = [sd.Color.FromArgb(150, 150, 150),   # ground
                  sd.Color.FromArgb(60, 60, 70),      # columns
                  sd.Color.FromArgb(70, 130, 200),    # offices
                  sd.Color.FromArgb(210, 120, 50)]    # core
Layer_Names = ["ground", "columns", "offices", "core"]

names = {0: "Separation", 1: "Separation with Plinth", 2: "Adherence",
         3: "Adherence with Plinth", 4: "Interlock"}
BGR_Category = "%d - %s" % (cat, names.get(cat, "Separation"))

print("Valid & closed" if all_ok else "Validation issues - see warnings")
print("Category: " + BGR_Category)
bar_slab_count = floors * len(bars)
core_slab_count = floors
print("Counts -> ground:%d columns:%d offices:%d core:%d floor_slabs:%d (bars:%d + core:%d)" % (
    len(ground_breps), len(column_breps), len(residential), len(core_breps),
    len(floor_breps), bar_slab_count, core_slab_count))
for line in piloti_report:
    print(line)