# -*- coding: utf-8 -*-
# MaCAD S.3 - Double-L Interior Layout Generator
# GHPython component / Rhino 8 Script Editor (Python 3)
#
# Skeleton component. Validates inputs and builds a per-bar metadata Report.
# No rooms, corridors, doors, walls, windows, graph edges, or CSV are generated.
#
# INPUTS:
#   Residential_Breps   list of residential bar Breps (parallel with Bar_Id, Floor_Index)
#   Core_Brep           list with one continuous core Brep (may be empty)
#   Bar_Id              int per Residential_Brep — bar index (0-3)
#   Floor_Index         int per Residential_Brep — floor index (0-based)
#   corridor_width      float — corridor strip depth (default 1.5)
#   unit_mix_seed       int  — rotates type pattern per bar/floor (default 0)
#
# OUTPUTS:
#   Interior_Breps      [] — reserved
#   Space_Types         [] — reserved
#   Apartment_Id        [] — reserved
#   Floor_Index_Out     [] — reserved
#   Bar_Id_Out          [] — reserved
#   Corridor_Breps           [] — one per valid bar
#   Corridor_Connector_Breps [] — L-B (Bar2↔Bar3) elbow, one per floor; Bar0↔Bar2 bridge when needed
#   Circulation_Breps        Corridor_Breps + Corridor_Connector_Breps (preview)
#   Apartment_Zone_Breps     [] — one zone Brep per unit slot, split along bar long axis
#   Apartment_Zone_Types     [] — "Studio" / "1Bedroom" / "2Bedroom", parallel
#   Apartment_Zone_Id        [] — stable id "F{f}_B{b}_U{i:02d}", parallel
#   Apartment_Zone_Floor_Index [] — floor index, parallel
#   Apartment_Zone_Bar_Id    [] — bar index, parallel
#   Label_Points             [] — rg.Point3d at room/community/circulation centre, floor Z
#   Label_Text               [] — display text parallel to Label_Points
#   Report                   one string per valid residential bar

import Rhino.Geometry as rg
from Grasshopper.Kernel import GH_RuntimeMessageLevel as RML

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

def _nearest_corner_dist(bar_bb, cx, cy):
    """Min 2-D distance from any corner of bar_bb to (cx, cy)."""
    best = float("inf")
    for bx in (bar_bb.Min.X, bar_bb.Max.X):
        for by in (bar_bb.Min.Y, bar_bb.Max.Y):
            d = ((bx - cx) ** 2 + (by - cy) ** 2) ** 0.5
            if d < best:
                best = d
    return best

def _l_group(bar_bb, core_bb):
    """Lower if bar is closer to core lower-left corner; Higher otherwise."""
    d_lower = _nearest_corner_dist(bar_bb, core_bb.Min.X, core_bb.Min.Y)
    d_upper = _nearest_corner_dist(bar_bb, core_bb.Max.X, core_bb.Max.Y)
    return "Lower" if d_lower <= d_upper else "Higher"

def _circulation_edge(bar_bb, core_bb, l_group):
    """Return (circulation_type, circulation_side).

    Lower L → outer perimeter (long face farthest from core centre in the
               perpendicular dimension).
    Higher L → inner face toward core/void (long face closest to core centre
               in the perpendicular dimension).
    Tiebreaker when equidistant: minimum-coordinate face (South / West).
    """
    ccx = (core_bb.Min.X + core_bb.Max.X) / 2.0
    ccy = (core_bb.Min.Y + core_bb.Max.Y) / 2.0

    dx = bar_bb.Max.X - bar_bb.Min.X
    dy = bar_bb.Max.Y - bar_bb.Min.Y

    if dx >= dy:  # horizontal bar — long faces N / S
        d_south = abs(bar_bb.Min.Y - ccy)
        d_north = abs(bar_bb.Max.Y - ccy)
        if abs(d_south - d_north) > 1e-6:
            if l_group == "Lower":
                side = "South" if d_south > d_north else "North"
            else:
                side = "South" if d_south < d_north else "North"
        else:
            # Bar straddles core-centre Y — south face is the target in both
            # groups for this layout (outer bottom for Lower L; faces void for
            # Higher L whose min-Y abuts the core top).
            side = "South"
    else:  # vertical bar — long faces E / W
        d_west = abs(bar_bb.Min.X - ccx)
        d_east = abs(bar_bb.Max.X - ccx)
        if abs(d_west - d_east) > 1e-6:
            if l_group == "Lower":
                side = "West" if d_west > d_east else "East"
            else:
                side = "West" if d_west < d_east else "East"
        else:
            side = "West"

    circ_type = "Outer" if l_group == "Lower" else "Inner"
    return circ_type, side

EPS = 1e-6

_CIRCULATION_SIDE = {0: "North", 1: "East", 2: "South", 3: "West"}

_UNIT_WEIGHTS = {"Studio": 1.00, "1Bedroom": 1.35, "2Bedroom": 1.80}
_UNIT_BASE    = ["Studio", "1Bedroom", "2Bedroom"]

# Studio room proportions in local (u, v) space
# u = long axis of zone; v=0 = corridor side, v=1 = façade side
_STUDIO_ROOMS = [
    ("Bath",    0.00, 0.35, 0.00, 0.45),
    ("Kitchen", 0.00, 0.35, 0.45, 1.00),
    ("Hall",    0.35, 0.55, 0.00, 1.00),
    ("Living",  0.55, 1.00, 0.00, 1.00),
]

_ONEBED_ROOMS = [
    ("Bath",    0.00, 0.32, 0.00, 0.38),
    ("Bedroom", 0.00, 0.32, 0.38, 1.00),
    ("Hall",    0.32, 0.52, 0.00, 1.00),
    ("Kitchen", 0.52, 1.00, 0.00, 0.35),
    ("Living",  0.52, 1.00, 0.35, 1.00),
]

_TWOBED_ROOMS = [
    ("Bath",     0.00, 0.34, 0.00, 0.28),
    ("Bedroom1", 0.00, 0.34, 0.28, 0.64),
    ("Bedroom2", 0.00, 0.34, 0.64, 1.00),
    ("Hall",     0.34, 0.54, 0.00, 1.00),
    ("Kitchen",  0.54, 1.00, 0.00, 0.30),
    ("Living",   0.54, 1.00, 0.30, 1.00),
]

_ROOM_MIN_DIM = {
    "Hall":     1.20,
    "Bath":     2.50,
    "Kitchen":  2.50,
    "Living":   2.50,
    "Bedroom":  2.50,
    "Bedroom1": 2.50,
    "Bedroom2": 2.50,
}

def _studio_room_brep(zone_bb, bid, u0, u1, v0, v1):
    """Map local Studio fractions to a world axis-aligned Brep.

    u  = long axis of the zone (X for horizontal bars, Y for vertical).
    v=0 = corridor side, v=1 = façade side.
    """
    zx0, zx1 = zone_bb.Min.X, zone_bb.Max.X
    zy0, zy1 = zone_bb.Min.Y, zone_bb.Max.Y
    zz0, zz1 = zone_bb.Min.Z, zone_bb.Max.Z
    dx = zx1 - zx0
    dy = zy1 - zy0

    if bid == 0:   # horizontal, corridor North, façade South  → u=X, v=0 at Y-max
        wx0 = zx0 + u0 * dx;  wx1 = zx0 + u1 * dx
        wy0 = zy1 - v1 * dy;  wy1 = zy1 - v0 * dy
    elif bid == 1: # vertical,   corridor East,  façade West   → u=Y, v=0 at X-max
        wy0 = zy0 + u0 * dy;  wy1 = zy0 + u1 * dy
        wx0 = zx1 - v1 * dx;  wx1 = zx1 - v0 * dx
    elif bid == 2: # horizontal, corridor South, façade North  → u=X, v=0 at Y-min
        wx0 = zx0 + u0 * dx;  wx1 = zx0 + u1 * dx
        wy0 = zy0 + v0 * dy;  wy1 = zy0 + v1 * dy
    elif bid == 3: # vertical,   corridor West,  façade East   → u=Y, v=0 at X-min
        wy0 = zy0 + u0 * dy;  wy1 = zy0 + u1 * dy
        wx0 = zx0 + v0 * dx;  wx1 = zx0 + v1 * dx
    else:
        return None

    if wx1 <= wx0 + EPS or wy1 <= wy0 + EPS or zz1 <= zz0 + EPS:
        return None
    return rg.Brep.CreateFromBox(
        rg.BoundingBox(rg.Point3d(wx0, wy0, zz0), rg.Point3d(wx1, wy1, zz1))
    )

def _make_corridor_brep(bb, side, width):
    """Return (Brep, skip_reason).  skip_reason is None on success."""
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y

    if width <= EPS:
        return None, "corridor_width %.4f <= 0" % width

    if side == "South":
        short_dim = dy
        if width >= short_dim - EPS:
            return None, "corridor_width %.4f >= bar dy %.4f" % (width, short_dim)
        x0, x1 = bb.Min.X, bb.Max.X
        y0, y1 = bb.Min.Y, bb.Min.Y + width

    elif side == "North":
        short_dim = dy
        if width >= short_dim - EPS:
            return None, "corridor_width %.4f >= bar dy %.4f" % (width, short_dim)
        x0, x1 = bb.Min.X, bb.Max.X
        y0, y1 = bb.Max.Y - width, bb.Max.Y

    elif side == "West":
        short_dim = dx
        if width >= short_dim - EPS:
            return None, "corridor_width %.4f >= bar dx %.4f" % (width, short_dim)
        x0, x1 = bb.Min.X, bb.Min.X + width
        y0, y1 = bb.Min.Y, bb.Max.Y

    elif side == "East":
        short_dim = dx
        if width >= short_dim - EPS:
            return None, "corridor_width %.4f >= bar dx %.4f" % (width, short_dim)
        x0, x1 = bb.Max.X - width, bb.Max.X
        y0, y1 = bb.Min.Y, bb.Max.Y

    else:
        return None, "unknown side '%s'" % side

    pt_min = rg.Point3d(x0, y0, bb.Min.Z)
    pt_max = rg.Point3d(x1, y1, bb.Max.Z)
    return rg.Brep.CreateFromBox(rg.BoundingBox(pt_min, pt_max)), None

def _check_core_connection(c_bb, core_bb):
    """True when the corridor footprint shares a real XY face segment with the core.

    overlap >= -EPS (touch_x / touch_y) in one axis combined with a shared
    face boundary in the other axis constitutes a connection.
    """
    c_x0, c_y0 = c_bb.Min.X, c_bb.Min.Y
    c_x1, c_y1 = c_bb.Max.X, c_bb.Max.Y
    r_x0, r_y0 = core_bb.Min.X, core_bb.Min.Y
    r_x1, r_y1 = core_bb.Max.X, core_bb.Max.Y

    overlap_x = min(c_x1, r_x1) - max(c_x0, r_x0)
    overlap_y = min(c_y1, r_y1) - max(c_y0, r_y0)
    touch_x = overlap_x >= -EPS
    touch_y = overlap_y >= -EPS

    return (
        (touch_x and abs(c_y0 - r_y1) <= EPS) or
        (touch_x and abs(c_y1 - r_y0) <= EPS) or
        (touch_y and abs(c_x1 - r_x0) <= EPS) or
        (touch_y and abs(c_x0 - r_x1) <= EPS)
    )

# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------
Residential_Breps = dflt(Residential_Breps, [])
Core_Brep         = dflt(Core_Brep,         [])
Bar_Id            = dflt(Bar_Id,             [])
Floor_Index       = dflt(Floor_Index,        [])
corridor_width    = float(dflt(corridor_width, 1.5))
unit_mix_seed     = int(dflt(unit_mix_seed,   0))

# ----------------------------------------------------------------------
# Output initialisation
# ----------------------------------------------------------------------
Interior_Breps       = []
Space_Types          = []
Apartment_Id         = []
Floor_Index_Out      = []
Bar_Id_Out           = []
Room_Area_m2         = []
Room_Min_Dimension_m = []
Room_Dimensions      = []
Room_Size_Status          = []
Room_Size_Failure_Report  = []
Corridor_Breps           = []
Corridor_Connector_Breps = []
Circulation_Breps        = []
Apartment_Zone_Breps       = []
Apartment_Zone_Types       = []
Apartment_Zone_Id          = []
Apartment_Zone_Floor_Index = []
Apartment_Zone_Bar_Id      = []
Label_Points             = []
Label_Text               = []
Report                   = []

# ----------------------------------------------------------------------
# Skeleton warning
# ----------------------------------------------------------------------
warn("Circulation stage: apartments, rooms, doors, walls, windows, graph outputs, and CSV are not generated yet.")

# ----------------------------------------------------------------------
# Parallel-list validation
# ----------------------------------------------------------------------
n = len(Residential_Breps)

if len(Bar_Id) != n:
    warn("Bar_Id length %d != Residential_Breps length %d — lists must be parallel." % (len(Bar_Id), n))
if len(Floor_Index) != n:
    warn("Floor_Index length %d != Residential_Breps length %d — lists must be parallel." % (len(Floor_Index), n))

# ----------------------------------------------------------------------
# Core bounding box (plan) — union of all core breps, then extended south
# to bar 0's base (= core_y0) so bar 1's corridor can connect.
# ----------------------------------------------------------------------
core_bb = None
for _cb in (Core_Brep or []):
    if _cb is not None:
        _cbb = _cb.GetBoundingBox(True)
        core_bb = rg.BoundingBox.Union(core_bb, _cbb) if core_bb is not None else _cbb

_bar_min_y = {}
for _rb, _bid_raw in zip(Residential_Breps, Bar_Id):
    try:
        _b = int(_bid_raw)
    except (TypeError, ValueError):
        continue
    if _rb is not None:
        _my = _rb.GetBoundingBox(True).Min.Y
        if _b not in _bar_min_y or _my < _bar_min_y[_b]:
            _bar_min_y[_b] = _my

if core_bb is not None and 0 in _bar_min_y and _bar_min_y[0] < core_bb.Min.Y - EPS:
    _ext_min = rg.Point3d(core_bb.Min.X, _bar_min_y[0], core_bb.Min.Z)
    _ext_max = rg.Point3d(core_bb.Max.X, core_bb.Max.Y, core_bb.Max.Z)
    core_bb  = rg.BoundingBox(_ext_min, _ext_max)

# per-floor bar bbs, report line indices, and corridor Brep indices used by connector pass
floor_bar_bbs       = {}
report_index        = {}
corridor_brep_index = {}  # (fid, bid) -> index in Corridor_Breps

# ----------------------------------------------------------------------
# Per-bar metadata report
# ----------------------------------------------------------------------
for i, brep in enumerate(Residential_Breps):
    if brep is None:
        warn("Residential_Breps[%d] is None — skipped." % i)
        continue

    bid = Bar_Id[i]    if i < len(Bar_Id)    else None
    fid = Floor_Index[i] if i < len(Floor_Index) else None

    if bid is None or fid is None:
        warn("Residential_Breps[%d]: missing Bar_Id or Floor_Index — skipped." % i)
        continue

    bb = brep.GetBoundingBox(True)
    floor_bar_bbs.setdefault(fid, {})[bid] = bb
    dx = bb.Max.X - bb.Min.X
    dy = bb.Max.Y - bb.Min.Y
    dz = bb.Max.Z - bb.Min.Z

    if dx > dy:
        orientation = "Horizontal"
    elif dy > dx:
        orientation = "Vertical"
    else:
        orientation = "Square"

    if core_bb is not None:
        grp       = _l_group(bb, core_bb)
        circ_type = "Outer" if grp == "Lower" else "Inner"
    else:
        grp       = "N/A"
        circ_type = "N/A"

    circ_side = _CIRCULATION_SIDE.get(bid, None)
    if circ_side is None:
        corr_status = "skipped"
        corr_reason = "bar_id %d not in _CIRCULATION_SIDE" % bid
        warn("Bar %d floor %d: %s" % (bid, fid, corr_reason))
        circ_str = "  l_group=%s  circulation_type=%s  circulation_side=N/A" % (grp, circ_type)
    else:
        circ_str = "  l_group=%s  circulation_type=%s  circulation_side=%s" % (grp, circ_type, circ_side)
        c_brep, skip_reason = _make_corridor_brep(bb, circ_side, corridor_width)
        if c_brep is None:
            corr_status = "skipped"
            corr_reason = skip_reason or "unknown"
            warn("Bar %d floor %d: corridor skipped — %s" % (bid, fid, corr_reason))
        elif not c_brep.IsValid:
            corr_status = "skipped"
            corr_reason = "invalid corridor Brep"
            warn("Bar %d floor %d: corridor skipped — %s" % (bid, fid, corr_reason))
        else:
            corridor_brep_index[(fid, bid)] = len(Corridor_Breps)
            Corridor_Breps.append(c_brep)
            corr_status = "created"
            corr_reason = "OK"

    report_index[(fid, bid)] = len(Report)
    Report.append(
        "floor=%d  bar=%d  dx=%.3f  dy=%.3f  dz=%.3f  orientation=%s%s  corridor_status=%s  corridor_reason=%s"
        % (fid, bid, dx, dy, dz, orientation, circ_str, corr_status, corr_reason)
    )

# ----------------------------------------------------------------------
# Per-floor corridor count check
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    created = sum(
        1 for bid in (0, 1, 2, 3)
        if (fid, bid) in corridor_brep_index
    )
    if created != 4:
        warn(
            "Floor %d: Corridor_Breps has %d/4 bars. "
            "Check Report corridor_status values." % (fid, created)
        )

# ----------------------------------------------------------------------
# L-A touch  (extend Bar 1 East corridor north to touch Bar 0 North bottom)
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    idx0 = corridor_brep_index.get((fid, 0))
    idx1 = corridor_brep_index.get((fid, 1))
    if idx0 is None or idx1 is None:
        warn("Floor %d: bar 0 or bar 1 corridor missing — L-A touch skipped." % fid)
        continue

    bb0 = Corridor_Breps[idx0].GetBoundingBox(True)
    bb1 = Corridor_Breps[idx1].GetBoundingBox(True)

    if bb1.Max.Y >= bb0.Min.Y - EPS:
        la_tag = "direct"
    else:
        ext_brep = rg.Brep.CreateFromBox(
            rg.BoundingBox(
                rg.Point3d(bb1.Min.X, bb1.Min.Y, bb1.Min.Z),
                rg.Point3d(bb1.Max.X, bb0.Min.Y, bb1.Max.Z)
            )
        )
        if ext_brep is None:
            warn("Floor %d: bar 1 corridor extension failed — L-A touch skipped." % fid)
            continue
        Corridor_Breps[idx1] = ext_brep
        la_tag = "OK"

    for bid in (0, 1):
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += "  l_a_connector=%s" % la_tag

# ----------------------------------------------------------------------
# Bar 0 → Bar 3 touch  (extend Bar 0 North corridor east to touch Bar 3 West)
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    idx0 = corridor_brep_index.get((fid, 0))
    idx3 = corridor_brep_index.get((fid, 3))
    if idx0 is None or idx3 is None:
        warn("Floor %d: bar 0 or bar 3 corridor missing — Bar0-Bar3 touch skipped." % fid)
        continue

    bb0 = Corridor_Breps[idx0].GetBoundingBox(True)
    bb3 = Corridor_Breps[idx3].GetBoundingBox(True)

    if bb0.Max.X >= bb3.Min.X - EPS:
        b03_tag = "direct"
    else:
        ext_brep = rg.Brep.CreateFromBox(
            rg.BoundingBox(
                rg.Point3d(bb0.Min.X, bb0.Min.Y, bb0.Min.Z),
                rg.Point3d(bb3.Min.X, bb0.Max.Y, bb0.Max.Z)
            )
        )
        if ext_brep is None:
            warn("Floor %d: bar 0 corridor extension failed — Bar0-Bar3 touch skipped." % fid)
            continue
        Corridor_Breps[idx0] = ext_brep
        b03_tag = "OK"

    for bid in (0, 3):
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += "  b0_b3_touch=%s" % b03_tag

# ----------------------------------------------------------------------
# Bar 1 → Bar 2 touch  (extend Bar 1 East corridor north to touch Bar 2 South bottom)
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    idx1 = corridor_brep_index.get((fid, 1))
    idx2 = corridor_brep_index.get((fid, 2))
    if idx1 is None or idx2 is None:
        warn("Floor %d: bar 1 or bar 2 corridor missing — Bar1-Bar2 touch skipped." % fid)
        continue

    bb1 = Corridor_Breps[idx1].GetBoundingBox(True)
    bb2 = Corridor_Breps[idx2].GetBoundingBox(True)

    if bb1.Max.Y >= bb2.Min.Y - EPS:
        b12_tag = "direct"
    else:
        ext_brep = rg.Brep.CreateFromBox(
            rg.BoundingBox(
                rg.Point3d(bb1.Min.X, bb1.Min.Y, bb1.Min.Z),
                rg.Point3d(bb1.Max.X, bb2.Min.Y, bb1.Max.Z)
            )
        )
        if ext_brep is None:
            warn("Floor %d: bar 1 corridor extension failed — Bar1-Bar2 touch skipped." % fid)
            continue
        Corridor_Breps[idx1] = ext_brep
        b12_tag = "OK"

    for bid in (1, 2):
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += "  b1_b2_touch=%s" % b12_tag

# ----------------------------------------------------------------------
# Bar 0 ↔ Bar 2 bridge  (North corridor → South corridor, shared X range)
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    idx0 = corridor_brep_index.get((fid, 0))
    idx2 = corridor_brep_index.get((fid, 2))
    if idx0 is None or idx2 is None:
        warn("Floor %d: bar 0 or bar 2 corridor missing — Bar0-Bar2 bridge skipped." % fid)
        continue

    bb0 = Corridor_Breps[idx0].GetBoundingBox(True)
    bb2 = Corridor_Breps[idx2].GetBoundingBox(True)

    x0 = max(bb0.Min.X, bb2.Min.X)
    x1 = min(bb0.Max.X, bb2.Max.X)
    y0 = bb0.Max.Y
    y1 = bb2.Min.Y
    z0 = bb0.Min.Z
    z1 = bb0.Max.Z

    if x1 <= x0 + EPS:
        warn("Floor %d: Bar0-Bar2 bridge has no shared X range — skipped." % fid)
        continue

    if y1 <= y0 + EPS:
        b02_tag = "direct"
    else:
        if z1 <= z0 + EPS:
            warn("Floor %d: Bar0-Bar2 bridge has invalid Z dimension — skipped." % fid)
            continue
        pt_min = rg.Point3d(x0, y0, z0)
        pt_max = rg.Point3d(x1, y1, z1)
        bridge_brep = rg.Brep.CreateFromBox(rg.BoundingBox(pt_min, pt_max))
        if bridge_brep is None:
            warn("Floor %d: Bar0-Bar2 bridge Brep creation failed — skipped." % fid)
            continue
        Corridor_Connector_Breps.append(bridge_brep)
        b02_tag = "OK"

    for bid in (0, 2):
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += "  b0_b2_connector=%s" % b02_tag

# ----------------------------------------------------------------------
# L-B elbow connector  (Bar 2 South ↔ Bar 3 West, one per floor)
# ----------------------------------------------------------------------
for fid in sorted(floor_bar_bbs):
    idx2 = corridor_brep_index.get((fid, 2))
    idx3 = corridor_brep_index.get((fid, 3))
    if idx2 is None or idx3 is None:
        warn("Floor %d: bar 2 or bar 3 corridor missing — L-B connector skipped." % fid)
        continue

    bb2 = Corridor_Breps[idx2].GetBoundingBox(True)
    bb3 = Corridor_Breps[idx3].GetBoundingBox(True)

    overlap = EPS * 2.0
    x0 = max(bb2.Min.X, bb3.Min.X)
    x1 = min(bb2.Max.X, bb3.Max.X)
    y0 = bb3.Max.Y - overlap
    y1 = bb2.Min.Y + overlap
    z0 = bb2.Min.Z
    z1 = bb2.Max.Z

    if x1 <= x0 + EPS or y1 <= y0 + EPS or z1 <= z0 + EPS:
        warn("Floor %d: L-B connector has zero/negative dimension — skipped." % fid)
        continue

    pt_min = rg.Point3d(x0, y0, z0)
    pt_max = rg.Point3d(x1, y1, z1)
    conn_brep = rg.Brep.CreateFromBox(rg.BoundingBox(pt_min, pt_max))
    if conn_brep is None:
        warn("Floor %d: L-B connector Brep creation failed — skipped." % fid)
        continue

    Corridor_Connector_Breps.append(conn_brep)
    for bid in (2, 3):
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += "  l_b_connector=OK"

Circulation_Breps = Corridor_Breps + Corridor_Connector_Breps


# ----------------------------------------------------------------------
# Apartment zone footprints  (mixed unit split along bar long axis)
# ----------------------------------------------------------------------
# Usable rectangle rules (uses original bar BB, not extended corridor BBs):
#   Bar 0 (North corr): apt_y1 = bb.Max.Y - corridor_width
#   Bar 1 (East corr) : apt_x1 = bb.Max.X - corridor_width
#   Bar 2 (South corr): apt_y0 = bb.Min.Y + corridor_width
#   Bar 3 (West corr) : apt_x0 = bb.Min.X + corridor_width
_APT_USABLE = {
    0: lambda bb, cw: (bb.Min.X, bb.Max.X,         bb.Min.Y,        bb.Max.Y - cw),
    1: lambda bb, cw: (bb.Min.X, bb.Max.X - cw,    bb.Min.Y,        bb.Max.Y),
    2: lambda bb, cw: (bb.Min.X, bb.Max.X,         bb.Min.Y + cw,   bb.Max.Y),
    3: lambda bb, cw: (bb.Min.X + cw, bb.Max.X,    bb.Min.Y,        bb.Max.Y),
}

for fid in sorted(floor_bar_bbs):
    for bid in sorted(floor_bar_bbs[fid]):
        fid_int = int(fid)
        bid_int = int(bid)
        bb = floor_bar_bbs[fid][bid]
        if bid not in _APT_USABLE:
            continue

        ax0, ax1, ay0, ay1 = _APT_USABLE[bid](bb, corridor_width)
        usable_dx = ax1 - ax0
        usable_dy = ay1 - ay0

        if usable_dx <= EPS or usable_dy <= EPS:
            warn("Floor %d bar %d: usable apartment rectangle is degenerate — skipped." % (fid_int, bid_int))
            continue

        # Bar 0: carve out Bar 1 corridor X-span, split usable area into pieces
        if bid == 0:
            _b0_z0, _b0_z1   = bb.Min.Z, bb.Max.Z
            _b0_slot_reserved = False
            _b0_pieces        = []

            if (fid, 1) in corridor_brep_index:
                _c1b = Corridor_Breps[corridor_brep_index[(fid, 1)]]
                if _c1b is not None:
                    _c1bb    = _c1b.GetBoundingBox(True)
                    _slot_x0 = max(ax0, _c1bb.Min.X)
                    _slot_x1 = min(ax1, _c1bb.Max.X)
                    if _slot_x1 > _slot_x0 + EPS:
                        if _slot_x0 > ax0 + EPS:
                            _b0_pieces.append((ax0, _slot_x0))
                        if ax1 > _slot_x1 + EPS:
                            _b0_pieces.append((_slot_x1, ax1))
                        _b0_slot_reserved = True

            if not _b0_pieces:
                _b0_pieces = [(ax0, ax1)]

            _b0_offset     = int((unit_mix_seed + fid_int + bid_int) % 3)
            _b0_zone_count = 0
            _b0_all_types  = []
            _b0_global_ui  = 0

            for (_px0, _px1) in _b0_pieces:
                _pdx = _px1 - _px0
                if _pdx <= EPS:
                    continue
                _p_count   = max(3, int(round(_pdx / 8.0)))
                _p_pattern = _UNIT_BASE[_b0_offset:] + _UNIT_BASE[:_b0_offset]
                _p_types   = [_p_pattern[_j % 3] for _j in range(_p_count)]
                _p_weights = [_UNIT_WEIGHTS[_t] for _t in _p_types]
                _p_total_w = sum(_p_weights)
                _p_cursor  = _px0

                for _p_local, (_ptype, _pw) in enumerate(zip(_p_types, _p_weights)):
                    _p_span = (_pw / _p_total_w) * _pdx
                    _zb = rg.Brep.CreateFromBox(
                        rg.BoundingBox(
                            rg.Point3d(_p_cursor,          ay0, _b0_z0),
                            rg.Point3d(_p_cursor + _p_span, ay1, _b0_z1)
                        )
                    )
                    _p_cursor += _p_span
                    if _zb is None:
                        warn("Floor %d bar 0 unit %d: zone Brep failed." % (fid_int, _b0_global_ui))
                        _b0_global_ui += 1
                        continue
                    Apartment_Zone_Breps.append(_zb)
                    Apartment_Zone_Types.append(_ptype)
                    Apartment_Zone_Id.append("F%d_B%d_U%02d" % (fid_int, bid_int, _b0_global_ui))
                    Apartment_Zone_Floor_Index.append(fid_int)
                    Apartment_Zone_Bar_Id.append(bid_int)
                    _b0_zone_count += 1
                    _b0_global_ui  += 1

                _b0_all_types.extend(_p_types)

            _b0_s   = _b0_all_types.count("Studio")
            _b0_b1  = _b0_all_types.count("1Bedroom")
            _b0_b2  = _b0_all_types.count("2Bedroom")
            _b0_mix = "%dxStudio/%dx1Bedroom/%dx2Bedroom" % (_b0_s, _b0_b1, _b0_b2)
            _b0_key = (fid, bid)
            if _b0_key in report_index:
                _slot_sfx = "  bar1_circulation_slot=reserved" if _b0_slot_reserved else ""
                Report[report_index[_b0_key]] += (
                    "  apartment_zones=%d  unit_mix=%s%s" % (_b0_zone_count, _b0_mix, _slot_sfx)
                )
            continue  # bid==0 fully handled above

        if usable_dx >= usable_dy:
            split_axis     = "X"
            long_axis_len  = usable_dx
        else:
            split_axis     = "Y"
            long_axis_len  = usable_dy

        unit_count = max(3, int(round(long_axis_len / 8.0)))
        offset     = int((unit_mix_seed + fid_int + bid_int) % 3)
        pattern    = _UNIT_BASE[offset:] + _UNIT_BASE[:offset]
        unit_types = [pattern[i % 3] for i in range(unit_count)]

        weights  = [_UNIT_WEIGHTS[t] for t in unit_types]
        total_w  = sum(weights)
        z0, z1   = bb.Min.Z, bb.Max.Z
        cursor   = ax0 if split_axis == "X" else ay0

        floor_zone_count = 0
        for ui, (utype, w) in enumerate(zip(unit_types, weights)):
            span = (w / total_w) * long_axis_len
            if split_axis == "X":
                px0, px1 = cursor, cursor + span
                py0, py1 = ay0, ay1
            else:
                px0, px1 = ax0, ax1
                py0, py1 = cursor, cursor + span
            cursor += span

            zone_brep = rg.Brep.CreateFromBox(
                rg.BoundingBox(rg.Point3d(px0, py0, z0), rg.Point3d(px1, py1, z1))
            )
            if zone_brep is None:
                warn("Floor %d bar %d unit %d: zone Brep failed — skipped." % (fid_int, bid_int, ui))
                continue

            Apartment_Zone_Breps.append(zone_brep)
            Apartment_Zone_Types.append(utype)
            Apartment_Zone_Id.append("F%d_B%d_U%02d" % (fid_int, bid_int, ui))
            Apartment_Zone_Floor_Index.append(fid_int)
            Apartment_Zone_Bar_Id.append(bid_int)
            floor_zone_count += 1

        s_c  = unit_types.count("Studio")
        b1_c = unit_types.count("1Bedroom")
        b2_c = unit_types.count("2Bedroom")
        mix_str = "%dxStudio/%dx1Bedroom/%dx2Bedroom" % (s_c, b1_c, b2_c)
        key = (fid, bid)
        if key in report_index:
            Report[report_index[key]] += (
                "  apartment_zones=%d  unit_mix=%s" % (floor_zone_count, mix_str)
            )

# ----------------------------------------------------------------------
# Studio room footprints  (Bath + Kitchen + Hall + Living per Studio zone)
# ----------------------------------------------------------------------
_studio_report = {}   # (fid, bid) -> total rooms emitted for report suffix

for _zi in range(len(Apartment_Zone_Breps)):
    if Apartment_Zone_Types[_zi] != "Studio":
        continue

    _zone_brep = Apartment_Zone_Breps[_zi]
    if _zone_brep is None:
        warn("Studio zone index %d: Brep is None — skipped." % _zi)
        continue

    _zone_bb = _zone_brep.GetBoundingBox(True)
    _apt_id  = Apartment_Zone_Id[_zi]
    _fid_out = Apartment_Zone_Floor_Index[_zi]
    _bid_out = Apartment_Zone_Bar_Id[_zi]

    # Studio: compute per-zone fractions so every room meets its minimum dimension.
    # New topology (Hall at corridor strip, service stack + Living side by side):
    #   Hall:    u=[0, 1],        v=[0, hall_d]           — 1.20 m corridor strip
    #   Bath:    u=[0, svc_u],    v=[hall_d, bath_vend]   — service column, top half
    #   Kitchen: u=[0, svc_u],    v=[bath_vend, 1]        — service column, bottom half
    #   Living:  u=[svc_u, 1],    v=[hall_d, 1]           — open façade zone
    _zdx     = _zone_bb.Max.X - _zone_bb.Min.X
    _zdy     = _zone_bb.Max.Y - _zone_bb.Min.Y
    _zone_u  = _zdx if _bid_out in (0, 2) else _zdy
    _zone_v  = _zdy if _bid_out in (0, 2) else _zdx

    _hall_d    = 1.20 / _zone_v
    _svc_u     = 2.50 / _zone_u
    _bath_vend = (_hall_d + 1.00) / 2.0          # equal split → Bath and Kitchen share remaining v

    _bath_vdim = (_bath_vend - _hall_d) * _zone_v
    _kit_vdim  = (1.00 - _bath_vend)   * _zone_v
    _liv_udim  = (1.00 - _svc_u)       * _zone_u
    _liv_vdim  = (1.00 - _hall_d)      * _zone_v

    _studio_ok = (
        _zone_u > 0.0 and _zone_v > 0.0 and
        _hall_d < 1.00 and _svc_u < 1.00 and
        _bath_vdim >= 2.50 - EPS and
        _kit_vdim  >= 2.50 - EPS and
        _liv_udim  >= 2.50 - EPS and
        _liv_vdim  >= 2.50 - EPS
    )

    if _studio_ok:
        _active_studio_rooms = [
            ("Hall",    0.00,    1.00,       0.00,       _hall_d),
            ("Bath",    0.00,    _svc_u,     _hall_d,    _bath_vend),
            ("Kitchen", 0.00,    _svc_u,     _bath_vend, 1.00),
            ("Living",  _svc_u,  1.00,       _hall_d,    1.00),
        ]
    else:
        warn("Studio %s (F%d B%d): zone u=%.2fm v=%.2fm cannot satisfy room minimums "
             "(bath_v=%.2f kit_v=%.2f liv_u=%.2f liv_v=%.2f) — using original layout."
             % (_apt_id, _fid_out, _bid_out, _zone_u, _zone_v,
                _bath_vdim, _kit_vdim, _liv_udim, _liv_vdim))
        _active_studio_rooms = _STUDIO_ROOMS

    _rooms_ok = 0
    for _rname, _u0, _u1, _v0, _v1 in _active_studio_rooms:
        _rb = _studio_room_brep(_zone_bb, _bid_out, _u0, _u1, _v0, _v1)
        if _rb is None:
            warn("Studio %s room %s: non-positive dimension — skipped." % (_apt_id, _rname))
            continue
        Interior_Breps.append(_rb)
        Space_Types.append(_rname)
        Apartment_Id.append(_apt_id)
        Floor_Index_Out.append(_fid_out)
        Bar_Id_Out.append(_bid_out)
        _rooms_ok += 1

    if _rooms_ok != 4:
        warn("Studio %s: emitted %d rooms (expected 4)." % (_apt_id, _rooms_ok))

    _key = (_fid_out, _bid_out)
    _studio_report[_key] = _studio_report.get(_key, 0) + _rooms_ok

for _key, _total in _studio_report.items():
    if _key in report_index:
        Report[report_index[_key]] += "  studio_rooms=%d" % _total

# ----------------------------------------------------------------------
# 1Bedroom room footprints  (Bath + Bedroom + Hall + Kitchen + Living)
# ----------------------------------------------------------------------
_onebed_report = {}   # (fid, bid) -> total rooms emitted

for _zi in range(len(Apartment_Zone_Breps)):
    if Apartment_Zone_Types[_zi] != "1Bedroom":
        continue

    _zone_brep = Apartment_Zone_Breps[_zi]
    if _zone_brep is None:
        warn("1Bedroom zone index %d: Brep is None — skipped." % _zi)
        continue

    _zone_bb = _zone_brep.GetBoundingBox(True)
    _apt_id  = Apartment_Zone_Id[_zi]
    _fid_out = Apartment_Zone_Floor_Index[_zi]
    _bid_out = Apartment_Zone_Bar_Id[_zi]

    # 1Bedroom: clamp Bath+Bedroom u-strip to 2.50 m; give residual to Kitchen+Living.
    _zdx     = _zone_bb.Max.X - _zone_bb.Min.X
    _zdy     = _zone_bb.Max.Y - _zone_bb.Min.Y
    _zone_u  = _zdx if _bid_out in (0, 2) else _zdy
    _zone_v  = _zdy if _bid_out in (0, 2) else _zdx

    _br_u   = max(0.32 * _zone_u, 2.50)
    _hall_u = max(0.20 * _zone_u, 1.20)
    _kl_u   = _zone_u - _br_u - _hall_u

    _bath_min = min(_br_u,   0.38 * _zone_v)
    _bed_min  = min(_br_u,   0.62 * _zone_v)
    _hall_min = min(_hall_u, _zone_v)
    _kit_min  = min(_kl_u,   0.35 * _zone_v)
    _liv_min  = min(_kl_u,   0.65 * _zone_v)

    _onebed_ok = (
        _zone_u > 0.0 and _zone_v > 0.0 and
        _kl_u     >= 2.50 - EPS and
        _bath_min >= 2.50 - EPS and
        _bed_min  >= 2.50 - EPS and
        _hall_min >= 1.20 - EPS and
        _kit_min  >= 2.50 - EPS and
        _liv_min  >= 2.50 - EPS
    )

    if _onebed_ok:
        _f_br  = _br_u / _zone_u
        _f_end = (_br_u + _hall_u) / _zone_u
        _active_onebed_rooms = [
            ("Bath",    0.0,    _f_br,   0.00, 0.38),
            ("Bedroom", 0.0,    _f_br,   0.38, 1.00),
            ("Hall",    _f_br,  _f_end,  0.00, 1.00),
            ("Kitchen", _f_end, 1.00,    0.00, 0.35),
            ("Living",  _f_end, 1.00,    0.35, 1.00),
        ]
    else:
        warn("1Bedroom %s (F%d B%d): zone u=%.2fm v=%.2fm cannot satisfy room minimums "
             "(bath=%.2f bed=%.2f hall=%.2f kit=%.2f liv=%.2f) — using original layout."
             % (_apt_id, _fid_out, _bid_out, _zone_u, _zone_v,
                _bath_min, _bed_min, _hall_min, _kit_min, _liv_min))
        _active_onebed_rooms = _ONEBED_ROOMS

    _rooms_ok = 0
    for _rname, _u0, _u1, _v0, _v1 in _active_onebed_rooms:
        _rb = _studio_room_brep(_zone_bb, _bid_out, _u0, _u1, _v0, _v1)
        if _rb is None:
            warn("1Bedroom %s room %s: non-positive dimension — skipped." % (_apt_id, _rname))
            continue
        Interior_Breps.append(_rb)
        Space_Types.append(_rname)
        Apartment_Id.append(_apt_id)
        Floor_Index_Out.append(_fid_out)
        Bar_Id_Out.append(_bid_out)
        _rooms_ok += 1

    if _rooms_ok != 5:
        warn("1Bedroom %s: emitted %d rooms (expected 5)." % (_apt_id, _rooms_ok))

    _key = (_fid_out, _bid_out)
    _onebed_report[_key] = _onebed_report.get(_key, 0) + _rooms_ok

for _key, _total in _onebed_report.items():
    if _key in report_index:
        Report[report_index[_key]] += "  onebed_rooms=%d" % _total

# ----------------------------------------------------------------------
# 2Bedroom room footprints  (Bath + Bedroom1 + Bedroom2 + Hall + Kitchen + Living)
# ----------------------------------------------------------------------
_twobed_report = {}   # (fid, bid) -> total rooms emitted

for _zi in range(len(Apartment_Zone_Breps)):
    if Apartment_Zone_Types[_zi] != "2Bedroom":
        continue

    _zone_brep = Apartment_Zone_Breps[_zi]
    if _zone_brep is None:
        warn("2Bedroom zone index %d: Brep is None — skipped." % _zi)
        continue

    _zone_bb = _zone_brep.GetBoundingBox(True)
    _apt_id  = Apartment_Zone_Id[_zi]
    _fid_out = Apartment_Zone_Floor_Index[_zi]
    _bid_out = Apartment_Zone_Bar_Id[_zi]

    _rooms_ok = 0
    for _rname, _u0, _u1, _v0, _v1 in _TWOBED_ROOMS:
        _rb = _studio_room_brep(_zone_bb, _bid_out, _u0, _u1, _v0, _v1)
        if _rb is None:
            warn("2Bedroom %s room %s: non-positive dimension — skipped." % (_apt_id, _rname))
            continue
        Interior_Breps.append(_rb)
        Space_Types.append(_rname)
        Apartment_Id.append(_apt_id)
        Floor_Index_Out.append(_fid_out)
        Bar_Id_Out.append(_bid_out)
        _rooms_ok += 1

    if _rooms_ok != 6:
        warn("2Bedroom %s: emitted %d rooms (expected 6)." % (_apt_id, _rooms_ok))

    _key = (_fid_out, _bid_out)
    _twobed_report[_key] = _twobed_report.get(_key, 0) + _rooms_ok

for _key, _total in _twobed_report.items():
    if _key in report_index:
        Report[report_index[_key]] += "  twobed_rooms=%d" % _total

# ----------------------------------------------------------------------
# Room size audit  (parallel with Interior_Breps)
# ----------------------------------------------------------------------
_audit_room_report = {}   # (fid, bid) -> total rooms checked
_audit_fail_report = {}   # (fid, bid) -> FAIL count
_audit_fail_by_type = {}  # space_type -> FAIL count (for console)
_audit_min_dim  = float("inf")
_audit_min_type = ""
_audit_min_apt  = ""

_zone_type_lut_audit = {_id: _t for _id, _t in zip(Apartment_Zone_Id, Apartment_Zone_Types)}

for _i in range(len(Interior_Breps)):
    _rm  = Interior_Breps[_i]
    _abb = _rm.GetBoundingBox(True)
    _dx  = _abb.Max.X - _abb.Min.X
    _dy  = _abb.Max.Y - _abb.Min.Y
    _area  = _dx * _dy
    _min_d = min(_dx, _dy)

    Room_Area_m2.append(_area)
    Room_Min_Dimension_m.append(_min_d)
    Room_Dimensions.append("%.2f x %.2f m" % (_dx, _dy))

    _stype  = Space_Types[_i]
    _target = _ROOM_MIN_DIM.get(_stype, 2.50)
    _ck     = (Floor_Index_Out[_i], Bar_Id_Out[_i])
    _audit_room_report[_ck] = _audit_room_report.get(_ck, 0) + 1

    if _min_d + EPS < _target:
        if _stype == "Hall":
            _status = "FAIL: Hall min dimension < 1.20 m"
        else:
            _status = "FAIL: %s min dimension < 2.50 m" % _stype
        _audit_fail_report[_ck] = _audit_fail_report.get(_ck, 0) + 1
        _audit_fail_by_type[_stype] = _audit_fail_by_type.get(_stype, 0) + 1
        _apt_type = _zone_type_lut_audit.get(Apartment_Id[_i], "")
        Room_Size_Failure_Report.append(
            "F%d | B%d | %s | %s | %s | %.2f × %.2f m | min=%.2f m | target=%.2f m"
            % (Floor_Index_Out[_i], Bar_Id_Out[_i],
               Apartment_Id[_i], _apt_type, _stype,
               _dx, _dy, _min_d, _target)
        )
    else:
        _status = "OK"
    Room_Size_Status.append(_status)

    if _min_d < _audit_min_dim:
        _audit_min_dim  = _min_d
        _audit_min_type = _stype
        _audit_min_apt  = Apartment_Id[_i]

for _ck in _audit_room_report:
    if _ck in report_index:
        _checks = _audit_room_report[_ck]
        _fails  = _audit_fail_report.get(_ck, 0)
        Report[report_index[_ck]] += "  room_size_checks=%d  room_size_failures=%d" % (_checks, _fails)

# ----------------------------------------------------------------------
# Labels  (room, community, circulation — one per entity / one per floor)
# ----------------------------------------------------------------------

def _bb_centre_floor(brep):
    """Return (Point3d at XY centre / floor Z, ok) for a Brep."""
    if brep is None:
        return None, False
    bb = brep.GetBoundingBox(True)
    return rg.Point3d(
        (bb.Min.X + bb.Max.X) * 0.5,
        (bb.Min.Y + bb.Max.Y) * 0.5,
        bb.Min.Z
    ), True

# Room labels
_BEDROOM_DISPLAY = {"Bedroom1": "Bedroom", "Bedroom2": "Bedroom"}
_zone_type_lut   = {_id: _t for _id, _t in zip(Apartment_Zone_Id, Apartment_Zone_Types)}
for _i in range(len(Interior_Breps)):
    _pt, _ok = _bb_centre_floor(Interior_Breps[_i])
    if not _ok:
        continue
    _display   = _BEDROOM_DISPLAY.get(Space_Types[_i], Space_Types[_i])
    _apt_id    = Apartment_Id[_i]
    _unit_num  = _apt_id.rsplit("_U", 1)[-1]
    _zone_type = _zone_type_lut.get(_apt_id, "")
    Label_Points.append(_pt)
    Label_Text.append("%s\nApt. %s\n%s" % (_display, _unit_num, _zone_type))


# Circulation labels — one per floor, at first corridor found for that floor
_circ_floors_done = set()
for (_fid_c, _bid_c) in sorted(corridor_brep_index.keys()):
    if _fid_c in _circ_floors_done:
        continue
    _pt, _ok = _bb_centre_floor(Corridor_Breps[corridor_brep_index[(_fid_c, _bid_c)]])
    if not _ok:
        continue
    Label_Points.append(_pt)
    Label_Text.append("Circulation\nFloor %d" % int(_fid_c))
    _circ_floors_done.add(_fid_c)

# ----------------------------------------------------------------------
# Console report
# ----------------------------------------------------------------------
print("Double-L Interior Layout — circulation + Studio + 1Bedroom + 2Bedroom rooms")
print("  Residential_Breps        : %d" % n)
print("  Core_Brep                : %d" % len(Core_Brep))
print("  corridor_width           : %.3f" % corridor_width)
print("  unit_mix_seed            : %d" % unit_mix_seed)
print("  Corridor_Breps           : %d" % len(Corridor_Breps))
print("  Corridor_Connector_Breps : %d" % len(Corridor_Connector_Breps))
print("  Circulation_Breps        : %d" % len(Circulation_Breps))
print("  Apartment_Zone_Breps     : %d" % len(Apartment_Zone_Breps))
print("    Studio    : %d" % Apartment_Zone_Types.count("Studio"))
print("    1Bedroom  : %d" % Apartment_Zone_Types.count("1Bedroom"))
print("    2Bedroom  : %d" % Apartment_Zone_Types.count("2Bedroom"))
print("  Label_Points             : %d" % len(Label_Points))
print("  Label_Text               : %d" % len(Label_Text))
print("  Interior_Breps           : %d" % len(Interior_Breps))
print("  Room size audit:")
print("    total rooms        : %d" % len(Interior_Breps))
print("    FAIL count         : %d" % sum(_audit_fail_report.values()))
if len(Interior_Breps) > 0:
    print("    smallest room      : %.2f m (shortest side)" % _audit_min_dim)
    print("    smallest room type : %s" % _audit_min_type)
    print("    smallest room apt  : %s" % _audit_min_apt)
print("  Failures by space type:")
for _ft in ("Hall", "Bath", "Kitchen", "Living", "Bedroom", "Bedroom1", "Bedroom2"):
    _fc = _audit_fail_by_type.get(_ft, 0)
    if _fc:
        print("    %-10s : %d" % (_ft, _fc))
print("  Room_Size_Failure_Report : %d" % len(Room_Size_Failure_Report))
print("  Report entries           : %d" % len(Report))
for line in Report:
    print("    " + line)
