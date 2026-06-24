# -*- coding: utf-8 -*-
# MaCAD S.3 - Double-L Residential Massing Generator
# GHPython component / Rhino 8 Script Editor (Python 3)
#
# Two ┘-orientation L-shapes anchored to a fixed rectangular core.
# Core: lower-left = (building_length, building_width), size = core_width × core_depth.
# L-A grows left and down from core lower-left; L-B grows right and up from core upper-right.
# All four bars have constant thickness = bar_width.
#
# INPUTS:
#   building_length  building_width
#   bar0_length  bar1_length  bar2_length  bar3_length
#   bar_width    core_width   core_depth   corridor_width
#   floors       floor_height  pilotis_height  slab_thickness
#   column_size  grid_x        grid_y
#
# OUTPUTS:
#   Ground_Breps   Column_Breps   Residential_Breps   Core_Brep
#   Floor_Breps    Preview_Colors Layer_Names          BGR_Category
#   Bar_Id         Bar_Orientation Floor_Index

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

def linspace(a, b, n):
    if n <= 1: return [0.5 * (a + b)]
    s = (b - a) / float(n - 1)
    return [a + i * s for i in range(n)]

# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------
building_length = float(dflt(building_length, 24.0))
building_width  = float(dflt(building_width,  24.0))

floors         = int(dflt(floors,           4))
floor_height   = float(dflt(floor_height,   3.0))
pilotis_height = float(dflt(pilotis_height, 3.5))
slab_thickness = float(dflt(slab_thickness, 0.3))
column_size    = float(dflt(column_size,    0.5))
grid_x         = int(dflt(grid_x,          4))
grid_y         = int(dflt(grid_y,          4))

bar0_length = float(dflt(bar0_length, building_length))
bar1_length = float(dflt(bar1_length, building_width))
bar2_length = float(dflt(bar2_length, building_length))
bar3_length = float(dflt(bar3_length, building_width))
bar_width      = float(dflt(bar_width,      6.0))
core_width     = float(dflt(core_width,     6.0))
core_depth     = float(dflt(core_depth,     6.0))
corridor_width = float(dflt(corridor_width, 1.5))

floors = max(1, floors)
grid_x = max(2, grid_x)
grid_y = max(2, grid_y)

if bar_width <= EPS:
    warn("bar_width %.4f <= 0 — set a positive value." % bar_width)
if core_width <= EPS:
    warn("core_width %.4f <= 0 — set a positive value." % core_width)
if core_depth <= EPS:
    warn("core_depth %.4f <= 0 — set a positive value." % core_depth)
if corridor_width >= bar_width - EPS:
    warn("corridor_width %.4f >= bar_width %.4f — corner cores will be zero-height." % (corridor_width, bar_width))

# ----------------------------------------------------------------------
# Derived constants
# ----------------------------------------------------------------------
t        = slab_thickness
ph       = max(pilotis_height, 0.1)
fh       = floor_height
base_z   = t + ph
roof_top = base_z + floors * fh

bw = bar_width

# ----------------------------------------------------------------------
# Core footprint — fixed at (building_length, building_width)
# ----------------------------------------------------------------------
core_x0 = building_length
core_y0 = building_width
core_x1 = core_x0 + core_width
core_y1 = core_y0 + core_depth

core_valid = (core_x1 - core_x0 > EPS and core_y1 - core_y0 > EPS)
if not core_valid:
    warn("Core is invalid. Increase core_width and core_depth.")

# Corner core footprints — kept for column exclusion only (no geometry generated).
cw = corridor_width
la_core_x0 = core_x0 - bw;  la_core_x1 = core_x0
la_core_y0 = core_y0;        la_core_y1 = core_y0 + bw - cw

lb_core_x0 = core_x1;        lb_core_x1 = core_x1 + bw
lb_core_y0 = core_y1 + cw;   lb_core_y1 = core_y1 + bw

# Spine split at bar-0 top face (y = core_y0 + bw).
# Spine_Lower: y=[core_y0, core_y0+bw]  — aligns with bars 0 and 1.
# Spine_Upper: y=[core_y0+bw, core_y1]  — only exists when core_depth > bar_width.
_spine_cut = core_y0 + bw
_CORES = []
if core_y1 > _spine_cut + EPS:
    _CORES.append(("Spine_Upper", core_x0, core_x1, _spine_cut, core_y1))
else:
    warn("Spine_Upper skipped: core_depth (%.2f) <= bar_width (%.2f) — increase core_depth." % (core_depth, bw))

# ----------------------------------------------------------------------
# Bar footprints — L-A from core lower-left, L-B from core upper-right
# ----------------------------------------------------------------------
bar0_x1 = core_x0
bar0_x0 = bar0_x1 - bar0_length
bar0_y0 = core_y0
bar0_y1 = bar0_y0 + bw

bar1_x0 = core_x0 - bw
bar1_x1 = core_x0
bar1_y1 = core_y0
bar1_y0 = bar1_y1 - bar1_length

bar3_x0 = core_x1
bar3_x1 = core_x1 + bw
bar3_y1 = core_y1
bar3_y0 = bar3_y1 - bar3_length

bar2_x1 = bar3_x1
bar2_x0 = bar2_x1 - bar2_length
bar2_y0 = core_y1
bar2_y1 = bar2_y0 + bw

bar_footprints = [
    (bar0_x0, bar0_x1, bar0_y0, bar0_y1),  # Bar 0 H L-A
    (bar1_x0, bar1_x1, bar1_y0, bar1_y1),  # Bar 1 V L-A
    (bar2_x0, bar2_x1, bar2_y0, bar2_y1),  # Bar 2 H L-B
    (bar3_x0, bar3_x1, bar3_y0, bar3_y1),  # Bar 3 V L-B
]

_b_thick = [
    bar_footprints[0][3] - bar_footprints[0][2],
    bar_footprints[1][1] - bar_footprints[1][0],
    bar_footprints[2][3] - bar_footprints[2][2],
    bar_footprints[3][1] - bar_footprints[3][0],
]
for _bid, _th in enumerate(_b_thick):
    if abs(_th - bw) > EPS:
        warn("Bar %d thickness %.4f != bar_width %.4f." % (_bid, _th, bw))

_core_clear = True
if core_valid:
    for _bid, (_bx0, _bx1, _by0, _by1) in enumerate(bar_footprints):
        _ox = min(core_x1, _bx1) - max(core_x0, _bx0)
        _oy = min(core_y1, _by1) - max(core_y0, _by0)
        if _ox > EPS and _oy > EPS:
            warn("Core overlaps Bar %d. Check core_width, core_depth, and bar lengths." % _bid)
            _core_clear = False

core_ok = core_valid and _core_clear

# ----------------------------------------------------------------------
# Output initialisation
# ----------------------------------------------------------------------
Ground_Breps            = []
Column_Breps            = []
Residential_Breps       = []
Core_Brep               = []
Floor_Breps             = []
Bar_Id                  = []
Bar_Orientation         = []
Floor_Index             = []
Circulation_Breps       = []
Circulation_Types       = []
Circulation_Floor_Index = []
Circulation_Bar_Id      = []
Circulation_Id          = []

_ORIENTATION = {0: "Horizontal", 1: "Vertical", 2: "Horizontal", 3: "Vertical"}

# ----------------------------------------------------------------------
# Residential bars
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
        Bar_Orientation.append(_ORIENTATION[bid])
        Floor_Index.append(fi)

# ----------------------------------------------------------------------
# Core — three volumes: LA corner, spine, LB corner; all z=0 → roof_top
# ----------------------------------------------------------------------
invalid_core = 0
if core_ok:
    for _clabel, _cx0, _cx1, _cy0, _cy1 in _CORES:
        cb = box_brep(_cx0, _cx1, _cy0, _cy1, 0.0, roof_top)
        if cb is None or not cb.IsValid or not cb.IsSolid:
            warn("%s core: invalid Brep." % _clabel)
            invalid_core += 1
        else:
            Core_Brep.append(cb)

# ----------------------------------------------------------------------
# Floor slabs — four bar slabs + one core slab per floor
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
    if core_ok:
        for _clabel, _cx0, _cx1, _cy0, _cy1 in _CORES:
            core_sb = box_brep(_cx0, _cx1, _cy0, _cy1, slab_z0, slab_z1)
            if core_sb is None or not core_sb.IsValid or not core_sb.IsSolid:
                warn("%s core slab floor %d: invalid Brep." % (_clabel, fi))
                invalid_slab += 1
            else:
                Floor_Breps.append(core_sb)

# ----------------------------------------------------------------------
# Pilotis columns — grid_x × grid_y per bar, z=0 → base_z
# Core exclusion zone: core footprint expanded by cs/2.
# ----------------------------------------------------------------------
cs  = column_size
cz0 = 0.0
cz1 = base_z

_exc_zones = [
    (la_core_x0 - cs*0.5, la_core_x1 + cs*0.5, la_core_y0 - cs*0.5, la_core_y1 + cs*0.5),
    (core_x0    - cs*0.5, core_x1    + cs*0.5, core_y0    - cs*0.5, core_y1    + cs*0.5),
    (lb_core_x0 - cs*0.5, lb_core_x1 + cs*0.5, lb_core_y0 - cs*0.5, lb_core_y1 + cs*0.5),
]

placed_keys = set()
invalid_col  = 0

for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
    if (bx1 - bx0) < cs + EPS or (by1 - by0) < cs + EPS:
        warn("Bar %d footprint too narrow for column_size %.2f; columns skipped." % (bid, cs))
        continue
    xs = linspace(bx0 + cs * 0.5, bx1 - cs * 0.5, grid_x)
    ys = linspace(by0 + cs * 0.5, by1 - cs * 0.5, grid_y)
    for x in xs:
        for y in ys:
            if any(ex0 <= x <= ex1 and ey0 <= y <= ey1
                   for ex0, ex1, ey0, ey1 in _exc_zones):
                continue
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
_n_cores = len(_CORES)
exp_core = _n_cores if core_ok else 0
exp_slab = floors * ((4 + _n_cores) if core_ok else 4)
exp_gnd  = (4 + _n_cores) if core_ok else 4

if len(Residential_Breps) != exp_res:
    warn("Residential_Breps count %d != expected %d." % (len(Residential_Breps), exp_res))
if len(Bar_Id) != len(Residential_Breps):
    warn("Bar_Id length %d != Residential_Breps length %d — not parallel."
         % (len(Bar_Id), len(Residential_Breps)))
if len(Bar_Orientation) != len(Residential_Breps):
    warn("Bar_Orientation length %d != Residential_Breps length %d — not parallel."
         % (len(Bar_Orientation), len(Residential_Breps)))
if len(Floor_Index) != len(Residential_Breps):
    warn("Floor_Index length %d != Residential_Breps length %d — not parallel."
         % (len(Floor_Index), len(Residential_Breps)))
for i, bid in enumerate(Bar_Id):
    if Bar_Orientation[i] != _ORIENTATION[bid]:
        warn("Bar_Orientation[%d] '%s' != expected '%s' for Bar_Id %d."
             % (i, Bar_Orientation[i], _ORIENTATION[bid], bid))
if len(Core_Brep) != exp_core:
    warn("Core_Brep count %d != expected %d." % (len(Core_Brep), exp_core))
if len(Floor_Breps) != exp_slab:
    warn("Floor_Breps count %d != expected %d (%d floors x %d)."
         % (len(Floor_Breps), exp_slab, floors, 5 if core_ok else 4))

def _bars_touch(fp1, fp2):
    bx0,bx1,by0,by1 = fp1; ax0,ax1,ay0,ay1 = fp2
    xov = min(bx1,ax1) - max(bx0,ax0)
    yov = min(by1,ay1) - max(by0,ay0)
    return (xov > EPS and yov >= -EPS) or (yov > EPS and xov >= -EPS)

c_01 = _bars_touch(bar_footprints[0], bar_footprints[1])
c_23 = _bars_touch(bar_footprints[2], bar_footprints[3])

if not c_01:
    warn("Bar 0 ↔ Bar 1: no face connection — check bar0_length vs bar_width.")
if not c_23:
    warn("Bar 2 ↔ Bar 3: no face connection — check bar2_length vs bar_width.")
if not Column_Breps:
    warn("Column_Breps is empty — check column_size vs bar dimensions.")

# ----------------------------------------------------------------------
# Ground slabs
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
if core_ok:
    for _clabel, _cx0, _cx1, _cy0, _cy1 in _CORES:
        core_gs = box_brep(_cx0, _cx1, _cy0, _cy1, gs_z0, gs_z1)
        if core_gs is None or not core_gs.IsValid or not core_gs.IsSolid:
            warn("%s core ground slab: invalid Brep." % _clabel)
            invalid_gnd += 1
        else:
            Ground_Breps.append(core_gs)

if len(Ground_Breps) != exp_gnd:
    warn("Ground_Breps count %d != expected %d." % (len(Ground_Breps), exp_gnd))

# ----------------------------------------------------------------------
# Circulation — corridor strips + connectors per residential floor
# ----------------------------------------------------------------------
_corr_spec = [
    (0, bar0_x0,       bar3_x0,       bar0_y1 - cw,  bar0_y1),       # Bar 0 North (merged with LINK_B0B3 to bar3 west)
    (1, bar1_x1 - cw,  bar1_x1,       bar1_y0,        bar2_y0),       # Bar 1 East (merged with LINK_B1 to bar2 south)
    (2, bar2_x0,       bar2_x1,       bar2_y0,        bar2_y0 + cw),  # Bar 2 South
    (3, bar3_x0,       bar3_x0 + cw,  bar3_y0,        bar3_y1),       # Bar 3 West
]

_circ_floor_stats = {}  # fi -> [corridors, connectors, missing_bids]

for fi in range(floors):
    fz0 = base_z + fi * fh
    fz1 = fz0 + fh

    # ---- corridor strips ----
    _corr_bbs = {}   # bid -> (x0, x1, y0, y1)
    _missing   = []

    for bid, cx0, cx1, cy0, cy1 in _corr_spec:
        if cw <= EPS:
            _missing.append(bid)
            continue
        if cw >= bw - EPS:
            _missing.append(bid)
            warn("Floor %d bar %d: corridor_width >= bar_width — skipped." % (fi, bid))
            continue
        cb = box_brep(cx0, cx1, cy0, cy1, fz0, fz1)
        if cb is None or not cb.IsValid or not cb.IsSolid:
            _missing.append(bid)
            warn("Floor %d bar %d: corridor Brep invalid." % (fi, bid))
            continue
        Circulation_Breps.append(cb)
        Circulation_Types.append("Corridor")
        Circulation_Floor_Index.append(fi)
        Circulation_Bar_Id.append(bid)
        Circulation_Id.append("F%d_B%d_COR" % (fi, bid))
        _corr_bbs[bid] = (cx0, cx1, cy0, cy1)

    if _missing:
        warn("Floor %d: missing corridor bars %s." % (fi, _missing))

    _circ_floor_stats[fi] = [len(_corr_bbs), _missing]

# Validate — warn if any circulation Brep's AABB overlaps a Core_Brep AABB
for _ci, _cb in enumerate(Circulation_Breps):
    if not _cb.IsValid:
        continue
    _cbb = _cb.GetBoundingBox(True)
    for _core in Core_Brep:
        if _core is None or not _core.IsValid:
            continue
        _kbb = _core.GetBoundingBox(True)
        _ox = min(_cbb.Max.X, _kbb.Max.X) - max(_cbb.Min.X, _kbb.Min.X)
        _oy = min(_cbb.Max.Y, _kbb.Max.Y) - max(_cbb.Min.Y, _kbb.Min.Y)
        _oz = min(_cbb.Max.Z, _kbb.Max.Z) - max(_cbb.Min.Z, _kbb.Min.Z)
        if _ox > EPS and _oy > EPS and _oz > EPS:
            warn("Circulation[%d] %s: AABB overlaps Core_Brep volume." % (_ci, Circulation_Id[_ci]))

# ----------------------------------------------------------------------
# Preview metadata
# ----------------------------------------------------------------------
Preview_Colors = [
    sd.Color.FromArgb(70,  130, 200),   # Bar 0 — blue
    sd.Color.FromArgb(80,  180, 100),   # Bar 1 — green
    sd.Color.FromArgb(210, 120,  50),   # Bar 2 — orange
    sd.Color.FromArgb(200,  60,  60),   # Bar 3 — red
    sd.Color.FromArgb(220, 190,  60),   # Core  — gold
]
Layer_Names  = ["L_A_Horizontal", "L_A_Vertical", "L_B_Horizontal", "L_B_Vertical", "Core"]
BGR_Category = "Double-L_Core"

# ----------------------------------------------------------------------
# Console report
# ----------------------------------------------------------------------
_orient = {0: "H", 1: "V", 2: "H", 3: "V"}
_lbl    = lambda ok: "OK" if ok else "FAIL"

print("Double-L  floors=%d  core_ok=%s  bar_width=%.2f  corridor_width=%.2f" % (floors, core_ok, bw, cw))
print("  building=%.2f×%.2f  core=%.2f×%.2f" % (building_length, building_width, core_width, core_depth))
for _clbl, _cx0, _cx1, _cy0, _cy1 in _CORES:
    print("  core %s: x=[%.3f, %.3f]  y=[%.3f, %.3f]" % (_clbl, _cx0, _cx1, _cy0, _cy1))
for bid, (bx0, bx1, by0, by1) in enumerate(bar_footprints):
    print("  Bar %d (%s): x=[%.3f, %.3f]  y=[%.3f, %.3f]  t=%.3f"
          % (bid, _orient[bid], bx0, bx1, by0, by1, _b_thick[bid]))
print("  contacts: 01=%s  23=%s" % (_lbl(c_01), _lbl(c_23)))
print("  Residential=%d/%d  Core=%d/%d  Floor=%d/%d  Ground=%d/%d  Columns=%d"
      % (len(Residential_Breps), exp_res,
         len(Core_Brep), exp_core,
         len(Floor_Breps), exp_slab,
         len(Ground_Breps), exp_gnd,
         len(Column_Breps)))
print("Circulation per floor:")
for _fi in sorted(_circ_floor_stats):
    _cors, _miss = _circ_floor_stats[_fi]
    _miss_str = ("  MISSING bars=%s" % _miss) if _miss else ""
    print("  Floor %d: corridors=%d/4%s" % (_fi, _cors, _miss_str))
print("  Circulation_Breps total: %d" % len(Circulation_Breps))
