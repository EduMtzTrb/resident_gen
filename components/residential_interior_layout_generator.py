# Complex apartments + thin cross-corridor lobby
# Now with WALL THICKNESS + DOOR/WINDOW OPENINGS
# Rhino 8 Script Editor / Python 3
# Residential_Breps and Core_Brep inputs = LIST access.
#
# INPUTS (add wall_thickness; rest unchanged):
#   Residential_Breps (list)  Core_Brep (list)
#   apt_width  corridor_width  layout_type  seed  wall_thickness
#
# OUTPUTS to wire on the component:
#   Interior_Breps   Space_Types   Apartment_Id   Floor_Index   Space_Colors   Unit_Colors
#   Corridor_Breps
#   Wall_Breps       Wall_Colors            <-- NEW
#   Door_Breps       Window_Breps           <-- NEW (indicative opening volumes)

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System.Drawing as sd

from Grasshopper.Kernel import GH_RuntimeMessageLevel as RML


# ------------------------------------------------------------
# Tolerance
# ------------------------------------------------------------

TOL = 0.001

try:
    if sc.doc and sc.doc.ModelAbsoluteTolerance > 0:
        TOL = sc.doc.ModelAbsoluteTolerance
except:
    pass

EPS = TOL * 5.0


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def warn(m):
    try:
        ghenv.Component.AddRuntimeMessage(RML.Warning, m)
    except:
        pass


def dflt(v, d):
    return d if v is None else v


apt_width = float(dflt(apt_width, 6.5))
corridor_width = float(dflt(corridor_width, 1.6))
layout_type = int(dflt(layout_type, 0))
seed = int(dflt(seed, 0))

# NEW input. Thickness of every interior/exterior wall (model units).
wall_thickness = float(dflt(wall_thickness, 0.2))

# Toggle: when False, skip all wall/door/window geometry (much faster).
compute_walls = bool(dflt(compute_walls, True))

# Opening sizes (tweak freely; could be promoted to component inputs).
DOOR_W = 0.9
DOOR_H = 2.1
WIN_W = 1.3
WIN_H = 1.3
WIN_SILL = 0.9

# Minimum free span that can physically host a window (Hall uses this; others use WIN_W + 2t).
MIN_WINDOW_SPAN = max(DOOR_W, wall_thickness * 4)
# Minimum interior room dimension for non-Hall rooms.
# Rooms below this size emit a warning but are still generated (no skip).
MIN_ROOM_DIM = 2.6

floors_in = [b for b in (Residential_Breps or []) if b and b.IsValid]
cores_in = [b for b in (Core_Brep or []) if b and b.IsValid]

if not floors_in:
    warn("No valid Residential_Breps connected.")


def box_brep(x0, x1, y0, y1, z0, z1):
    if x1 < x0:
        x0, x1 = x1, x0

    if y1 < y0:
        y0, y1 = y1, y0

    if z1 < z0:
        z0, z1 = z1, z0

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


def overlap(b1, b2):
    return not (
        b1.Max.X <= b2.Min.X + EPS or
        b1.Min.X >= b2.Max.X - EPS or
        b1.Max.Y <= b2.Min.Y + EPS or
        b1.Min.Y >= b2.Max.Y - EPS or
        b1.Max.Z <= b2.Min.Z + EPS or
        b1.Min.Z >= b2.Max.Z - EPS
    )


core_bbs = [aabb(c) for c in cores_in]


def _core_segment_overlap(wall_coord, wall_axis_is_x, seg_lo, seg_hi):
    """Return blocked intervals where a core face lies on the wall plane
    AND its face segment overlaps [seg_lo, seg_hi].

    wall_axis_is_x=True  → wall at constant world-X = wall_coord; segment in world-Y.
    wall_axis_is_x=False → wall at constant world-Y = wall_coord; segment in world-X.
    """
    blocked = []
    for cb in core_bbs:
        if wall_axis_is_x:
            if not (abs(wall_coord - cb.Min.X) < EPS or abs(wall_coord - cb.Max.X) < EPS):
                continue
            core_lo, core_hi = cb.Min.Y, cb.Max.Y
        else:
            if not (abs(wall_coord - cb.Min.Y) < EPS or abs(wall_coord - cb.Max.Y) < EPS):
                continue
            core_lo, core_hi = cb.Min.X, cb.Max.X
        ov_lo = max(seg_lo, core_lo)
        ov_hi = min(seg_hi, core_hi)
        if ov_hi - ov_lo > EPS:
            blocked.append((ov_lo, ov_hi))
    return blocked


def _largest_free_segment(seg_lo, seg_hi, blocked):
    """Largest contiguous free sub-interval of [seg_lo, seg_hi] after removing blocked."""
    if not blocked:
        return seg_lo, seg_hi
    merged = []
    for b in sorted(blocked):
        b_lo = max(b[0], seg_lo)
        b_hi = min(b[1], seg_hi)
        if b_hi - b_lo <= EPS:
            continue
        if merged and b_lo <= merged[-1][1] + EPS:
            merged[-1][1] = max(merged[-1][1], b_hi)
        else:
            merged.append([b_lo, b_hi])
    best = (seg_lo, seg_lo)
    cur = seg_lo
    for b_lo, b_hi in merged:
        if b_lo - cur > best[1] - best[0]:
            best = (cur, b_lo)
        cur = max(cur, b_hi)
    if seg_hi - cur > best[1] - best[0]:
        best = (cur, seg_hi)
    return best


def _faces_core_across_gap(wall_coord, wall_axis_is_x, outward_is_negative,
                            seg_lo, seg_hi, max_gap):
    """Return True when a wall faces a core across a gap in the outward direction.

    wall_axis_is_x=True  → wall at constant world-X; outward along X; segment in world-Y.
    wall_axis_is_x=False → wall at constant world-Y; outward along Y; segment in world-X.
    outward_is_negative  → the outward normal points toward smaller coordinate values.
    max_gap              → ignore cores beyond this distance from the wall.
    """
    for cb in core_bbs:
        if wall_axis_is_x:
            if outward_is_negative:
                gap = wall_coord - cb.Max.X   # positive when core is fully outward
            else:
                gap = cb.Min.X - wall_coord
            if gap < -EPS or gap > max_gap + EPS:
                continue
            span_ov = min(cb.Max.Y, seg_hi) - max(cb.Min.Y, seg_lo)
        else:
            if outward_is_negative:
                gap = wall_coord - cb.Max.Y
            else:
                gap = cb.Min.Y - wall_coord
            if gap < -EPS or gap > max_gap + EPS:
                continue
            span_ov = min(cb.Max.X, seg_hi) - max(cb.Min.X, seg_lo)
        if span_ov > EPS:
            return True
    return False


def _corridor_face_touches_core(ori, coord, span_lo, span_hi, z0, z1):
    """Return True when a corridor exterior face is coplanar with a core face.

    ori: 'y' → face at constant world-Y; span runs in world-X.
         'x' → face at constant world-X; span runs in world-Y.
    coord: the face's constant coordinate.
    span_lo, span_hi: extent of the face in the perpendicular axis.
    z0, z1: floor height range — cores outside this range are ignored.

    When True, the caller must skip the exterior window (the door panel
    created by emit_corridor_core_doors already covers this face).
    """
    for cb in core_bbs:
        if cb.Max.Z < z0 - EPS or cb.Min.Z > z1 + EPS:
            continue
        if ori == 'y':
            if not (abs(coord - cb.Min.Y) < EPS or abs(coord - cb.Max.Y) < EPS):
                continue
            ov = min(cb.Max.X, span_hi) - max(cb.Min.X, span_lo)
        else:
            if not (abs(coord - cb.Min.X) < EPS or abs(coord - cb.Max.X) < EPS):
                continue
            ov = min(cb.Max.Y, span_hi) - max(cb.Min.Y, span_lo)
        if ov > EPS:
            return True
    return False


def carve(cell):
    if cell is None:
        return []

    hit = [c for c, bb in zip(cores_in, core_bbs) if overlap(aabb(cell), bb)]

    if not hit:
        return [cell]

    res = rg.Brep.CreateBooleanDifference([cell], hit, TOL)

    if res is None:
        return [cell]

    return [r for r in res if r and r.IsSolid]


def win_geometry(lab, span, fh, z0, core_aligned=False):
    # Returns (win_w, w_zlo, w_zhi) for an exterior window, by space type.
    # span = usable wall width; fh = floor height; z0 = floor bottom Z.
    # core_aligned=True → Hall/Living use standard sill instead of tall centred opening.
    # Hall:     90 % span × 70 % height centred (or WIN_H sill when core-aligned).
    # Living:   80 % span × 70 % height centred (or WIN_H sill when core-aligned).
    # Bedroom*: 60 % span, standard sill/head (WIN_SILL + WIN_H constants).
    # Bath:     50 % span, 35 % height, sill at 55 % of floor height.
    # Others (Kitchen…): fixed WIN_W, standard sill/head.
    # Corridor windows are handled by emit_corridor_ext_windows, not here.
    MIN_DIM = EPS * 10
    if lab == "Hall":
        win_w = span * 0.90
        if core_aligned:
            win_h = WIN_H          # fixed sill/head for core-adjacent walls
            w_zlo = z0 + WIN_SILL
        else:
            win_h = fh * 0.70
            w_zlo = z0 + (fh - win_h) * 0.5
    elif lab == "Living":
        win_w = span * 0.80
        if core_aligned:
            win_h = WIN_H          # fixed sill/head for core-adjacent walls
            w_zlo = z0 + WIN_SILL
        else:
            win_h = fh * 0.70
            w_zlo = z0 + (fh - win_h) * 0.5
    elif lab in ("Bedroom", "Bedroom1", "Bedroom2"):
        win_w = span * 0.60
        win_h = min(WIN_H, fh - 0.05 - min(WIN_SILL, 0.5 * fh))
        w_zlo = z0 + min(WIN_SILL, 0.5 * fh)
    elif lab == "Bath":
        win_w = span * 0.50
        win_h = fh * 0.35
        w_zlo = z0 + min(fh * 0.55, fh - win_h - MIN_DIM)
    else:
        win_w = WIN_W
        win_h = min(WIN_H, fh - 0.05 - min(WIN_SILL, 0.5 * fh))
        w_zlo = z0 + min(WIN_SILL, 0.5 * fh)
    # 85 % safety cap applied independently to width and height.
    win_w = min(win_w, span * 0.85)
    win_h = min(win_h, fh * 0.85)
    win_w = max(win_w, MIN_DIM)
    win_h = max(win_h, MIN_DIM)
    w_zhi = w_zlo + win_h
    w_zlo = max(w_zlo, z0 + MIN_DIM)
    w_zhi = min(w_zhi, z0 + fh - 0.01)
    if w_zhi <= w_zlo + MIN_DIM:
        w_zlo, w_zhi = z0 + fh * 0.1, z0 + fh * 0.9
    return win_w, w_zlo, w_zhi


def find_shared_wall(rec_a, rec_b):
    """Return (orientation, wall_coord, seg_lo, seg_hi) or None.

    Checks whether two room rects share a face segment (along-axis or
    across-axis wall). Uses EPS tolerance so floating-point boundaries
    created by the split grammar are treated as touching.
    """
    amin_a = min(rec_a[0], rec_a[1])
    amax_a = max(rec_a[0], rec_a[1])
    cmin_a = min(rec_a[2], rec_a[3])
    cmax_a = max(rec_a[2], rec_a[3])

    amin_b = min(rec_b[0], rec_b[1])
    amax_b = max(rec_b[0], rec_b[1])
    cmin_b = min(rec_b[2], rec_b[3])
    cmax_b = max(rec_b[2], rec_b[3])

    for coord, other in [(amax_a, amin_b), (amin_a, amax_b)]:
        if abs(coord - other) < EPS:
            seg_lo = max(cmin_a, cmin_b)
            seg_hi = min(cmax_a, cmax_b)
            if seg_hi - seg_lo > EPS:
                return ("along", coord, seg_lo, seg_hi)

    for coord, other in [(cmax_a, cmin_b), (cmin_a, cmax_b)]:
        if abs(coord - other) < EPS:
            seg_lo = max(amin_a, amin_b)
            seg_hi = min(amax_a, amax_b)
            if seg_hi - seg_lo > EPS:
                return ("across", coord, seg_lo, seg_hi)

    return None


def is_open_plan_pair(lab_a, lab_b):
    """True only for Hall ↔ Living — the one pair that shares open space."""
    return frozenset([lab_a, lab_b]) == frozenset(["Hall", "Living"])


# ------------------------------------------------------------
# Apartment split grammar
# ------------------------------------------------------------

def leaf(l):
    return {"leaf": l}


def vsplit(*p):
    return {
        "axis": "v",
        "parts": list(p)
    }


def usplit(*p):
    return {
        "axis": "u",
        "parts": list(p)
    }


def eval_split(node, u0, u1, v0, v1, out):
    if "leaf" in node:
        out.append((u0, u1, v0, v1, node["leaf"]))
        return

    parts = node["parts"]
    total = float(sum(w for w, _ in parts))

    if node["axis"] == "u":
        x = u0

        for w, ch in parts:
            x1 = x + (u1 - u0) * w / total
            eval_split(ch, x, x1, v0, v1, out)
            x = x1

    else:
        y = v0

        for w, ch in parts:
            y1 = y + (v1 - v0) * w / total
            eval_split(ch, u0, u1, y, y1, out)
            y = y1


# Hall-as-spine layout (u axis: left-column | Hall | right-column).
# Hall occupies a full-depth central strip (v=0→1) so it shares an edge
# with every room in both columns simultaneously — no room requires passing
# through another room to reach Hall.

STUDIO = usplit(
    (1.0, vsplit(                  # left column: service zone
        (1.5, leaf("Bath")),       # Bath: corridor side, no facade
        (2.0, leaf("Kitchen"))     # Kitchen: facade side (acceptable in studio)
    )),
    (0.6, leaf("Hall")),           # spine: touches Bath, Kitchen, Living
    (2.0, leaf("Living"))          # right column: full depth → facade
)

ONEBED = usplit(
    (1.2, vsplit(                  # left column: private zone
        (1.5, leaf("Bath")),       # Bath: corridor side, service, no facade
        (2.5, leaf("Bedroom"))     # Bedroom: facade ✓
    )),
    (0.6, leaf("Hall")),           # spine: touches Bath, Bedroom, Kitchen, Living
    (1.5, vsplit(                  # right column: living zone
        (1.5, leaf("Kitchen")),    # Kitchen: corridor side, service, no facade
        (2.5, leaf("Living"))      # Living: facade ✓
    ))
)

# TWOBED — Hall-spine layout preserves direct access from Hall to all five rooms.
# Living and Bedroom1 receive facade priority (v→1.0).
# Bedroom2 remains in the middle zone: the rectangular grammar cannot give Hall
# access to five rooms while also placing Living, Bedroom1, and Bedroom2 all at
# facade. A future L-shaped Hall primitive would resolve this.
TWOBED = usplit(
    (1.2, vsplit(                  # left column: private zone
        (1.5, leaf("Bath")),       # Bath: corridor side, service, no facade
        (2.5, leaf("Bedroom1"))    # Bedroom1: facade ✓
    )),
    (0.6, leaf("Hall")),           # spine: touches Bath, Bedroom1, Kitchen, Bedroom2, Living
    (1.5, vsplit(                  # right column: mixed living zone
        (1.0, leaf("Kitchen")),    # Kitchen: corridor side, no facade
        (2.0, leaf("Bedroom2")),   # Bedroom2: middle zone (see limitations)
        (2.0, leaf("Living"))      # Living: facade ✓
    ))
)

TYPES = [STUDIO, ONEBED, TWOBED]


# ------------------------------------------------------------
# Colors
# ------------------------------------------------------------

COL = {
    "Living": (150, 180, 225),
    "Kitchen": (235, 170, 90),
    "Bath": (110, 200, 200),
    "Bedroom": (150, 205, 150),
    "Bedroom1": (150, 205, 150),
    "Bedroom2": (125, 185, 135),
    "Hall": (205, 205, 210),
    "Corridor": (170, 170, 175)
}

WALL_COL = sd.Color.FromArgb(120, 120, 128)

# Muted apartment-unit palette; index = Apartment_Id % 10, deterministic.
UNIT_ALPHA = 120
UNIT_PALETTE = [
    sd.Color.FromArgb(UNIT_ALPHA, 200, 130, 110),  # 0 terracotta
    sd.Color.FromArgb(UNIT_ALPHA, 130, 175, 140),  # 1 sage
    sd.Color.FromArgb(UNIT_ALPHA, 160, 145, 195),  # 2 lavender
    sd.Color.FromArgb(UNIT_ALPHA, 210, 180, 100),  # 3 gold
    sd.Color.FromArgb(UNIT_ALPHA, 110, 175, 175),  # 4 teal
    sd.Color.FromArgb(UNIT_ALPHA, 200, 150, 155),  # 5 rose
    sd.Color.FromArgb(UNIT_ALPHA, 130, 160, 195),  # 6 steel-blue
    sd.Color.FromArgb(UNIT_ALPHA, 165, 175, 120),  # 7 olive
    sd.Color.FromArgb(UNIT_ALPHA, 210, 155, 130),  # 8 coral
    sd.Color.FromArgb(UNIT_ALPHA, 155, 155, 200),  # 9 periwinkle
]
UNIT_CORR_COL = sd.Color.FromArgb(175, 175, 178)


def color(l):
    r, g, b = COL.get(l, (200, 200, 200))
    return sd.Color.FromArgb(r, g, b)


# ------------------------------------------------------------
# Outputs
# ------------------------------------------------------------

Interior_Breps = []
Space_Types = []
Apartment_Id = []
Floor_Index = []
Space_Colors = []
Unit_Colors = []
Corridor_Breps = []

Wall_Breps = []
Wall_Colors = []
Door_Breps = []
Window_Breps = []

Label_Points = []
Label_Text = []

apt = 0
tindex = seed

floors_sorted = sorted(floors_in, key=lambda b: aabb(b).Min.Z)


def emit(brep, label, aid, fi):
    # Emits a "space" volume (room interior or corridor).
    for p in carve(brep):
        if p is None or not p.IsSolid:
            continue

        Interior_Breps.append(p)
        Space_Types.append(label)
        Apartment_Id.append(aid)
        Floor_Index.append(fi)
        Space_Colors.append(color(label))
        Unit_Colors.append(
            UNIT_PALETTE[aid % len(UNIT_PALETTE)] if aid >= 0 else UNIT_CORR_COL
        )

        bb_p = p.GetBoundingBox(True)
        cx = 0.5 * (bb_p.Min.X + bb_p.Max.X)
        cy = 0.5 * (bb_p.Min.Y + bb_p.Max.Y)
        Label_Points.append(rg.Point3d(cx, cy, bb_p.Min.Z))

        display_label = label

        if label in ["Bedroom1", "Bedroom2"]:
            display_label = "Bedroom"

        if aid < 0:
            Label_Text.append(display_label)
        else:
            Label_Text.append("%s\nApt %d" % (display_label, aid))

        if label == "Corridor":
            Corridor_Breps.append(p)


def emit_wall(brep):
    for p in carve(brep):
        if p and p.IsSolid:
            Wall_Breps.append(p)
            Wall_Colors.append(WALL_COL)


def emit_corridor_ext_windows(corr_brep, floor_bb, z0, z1):
    """
    Emit wall panels with window openings on any face of corr_brep that
    lies on the exterior boundary of the parent floor (floor_bb).
    Window: 80 % of wall span × 80 % of floor height, centred both axes.
    Skips when compute_walls=False.
    """
    if not compute_walls:
        return

    cb = aabb(corr_brep)
    cx0, cx1 = cb.Min.X, cb.Max.X
    cy0, cy1 = cb.Min.Y, cb.Max.Y
    wt = wall_thickness

    fh = z1 - z0
    # Corridor: 80 % height centred — equal sill and head margins.
    w_zlo = z0 + fh * 0.10
    w_zhi = z0 + fh * 0.90
    if w_zhi <= w_zlo + EPS:
        return

    def _y_wall(span0, span1, face_y, inward):
        # Wall panel on a Y-constant face; span runs in X.
        # inward=True  → panel sits at [face_y, face_y + wt]  (south face)
        # inward=False → panel sits at [face_y - wt, face_y]  (north face)
        span = span1 - span0
        if span < EPS * 10:
            return
        py0 = face_y if inward else face_y - wt
        py1 = py0 + wt
        panel = box_brep(span0, span1, py0, py1, z0, z1)
        if panel is None:
            return
        win_w = span * 0.8
        cx_c = 0.5 * (span0 + span1)
        vx0 = cx_c - 0.5 * win_w
        vx1 = cx_c + 0.5 * win_w
        void = box_brep(vx0, vx1, py0 - wt - EPS, py1 + wt + EPS, w_zlo, w_zhi)
        if void:
            res = rg.Brep.CreateBooleanDifference([panel], [void], TOL)
            if res:
                for r in res:
                    emit_wall(r)
            else:
                emit_wall(panel)
        else:
            emit_wall(panel)
        py_c = 0.5 * (py0 + py1)
        pan = box_brep(vx0, vx1, py_c - 0.25 * wt, py_c + 0.25 * wt, w_zlo, w_zhi)
        if pan:
            Window_Breps.append(pan)

    def _x_wall(span0, span1, face_x, inward):
        # Wall panel on an X-constant face; span runs in Y.
        # inward=True  → panel sits at [face_x, face_x + wt]  (west face)
        # inward=False → panel sits at [face_x - wt, face_x]  (east face)
        span = span1 - span0
        if span < EPS * 10:
            return
        px0 = face_x if inward else face_x - wt
        px1 = px0 + wt
        panel = box_brep(px0, px1, span0, span1, z0, z1)
        if panel is None:
            return
        win_w = span * 0.8
        cy_c = 0.5 * (span0 + span1)
        vy0 = cy_c - 0.5 * win_w
        vy1 = cy_c + 0.5 * win_w
        void = box_brep(px0 - wt - EPS, px1 + wt + EPS, vy0, vy1, w_zlo, w_zhi)
        if void:
            res = rg.Brep.CreateBooleanDifference([panel], [void], TOL)
            if res:
                for r in res:
                    emit_wall(r)
            else:
                emit_wall(panel)
        else:
            emit_wall(panel)
        px_c = 0.5 * (px0 + px1)
        pan = box_brep(px_c - 0.25 * wt, px_c + 0.25 * wt, vy0, vy1, w_zlo, w_zhi)
        if pan:
            Window_Breps.append(pan)

    if abs(cy0 - floor_bb.Min.Y) <= EPS:   # south face
        if not _corridor_face_touches_core('y', cy0, cx0, cx1, z0, z1):
            _y_wall(cx0, cx1, cy0, True)
    if abs(cy1 - floor_bb.Max.Y) <= EPS:   # north face
        if not _corridor_face_touches_core('y', cy1, cx0, cx1, z0, z1):
            _y_wall(cx0, cx1, cy1, False)
    if abs(cx0 - floor_bb.Min.X) <= EPS:   # west face
        if not _corridor_face_touches_core('x', cx0, cy0, cy1, z0, z1):
            _x_wall(cy0, cy1, cx0, True)
    if abs(cx1 - floor_bb.Max.X) <= EPS:   # east face
        if not _corridor_face_touches_core('x', cx1, cy0, cy1, z0, z1):
            _x_wall(cy0, cy1, cx1, False)


def _corr_core_door(ori, coord, inward, span_lo, span_hi, zlo, zhi, d_zhi):
    """Wall panel with a centred door at a corridor/core shared face.
    ori: 'x' (face at constant X) or 'y' (face at constant Y).
    inward=True → corridor is north/east of core → panel at [coord, coord+t].
    """
    span = span_hi - span_lo
    if span < EPS * 10:
        return
    t = wall_thickness
    sc_mid = 0.5 * (span_lo + span_hi)
    ww = min(DOOR_W, span * 0.80)
    p0 = coord if inward else coord - t
    p1 = p0 + t
    if ori == 'y':
        panel = box_brep(span_lo, span_hi, p0, p1, zlo, zhi)
        void  = box_brep(sc_mid - 0.5*ww, sc_mid + 0.5*ww, p0 - t - EPS, p1 + t + EPS, zlo, d_zhi)
        door_ind = box_brep(sc_mid - 0.5*ww, sc_mid + 0.5*ww,
                            0.5*(p0+p1) - 0.25*t, 0.5*(p0+p1) + 0.25*t, zlo, d_zhi)
    else:
        panel = box_brep(p0, p1, span_lo, span_hi, zlo, zhi)
        void  = box_brep(p0 - t - EPS, p1 + t + EPS, sc_mid - 0.5*ww, sc_mid + 0.5*ww, zlo, d_zhi)
        door_ind = box_brep(0.5*(p0+p1) - 0.25*t, 0.5*(p0+p1) + 0.25*t,
                            sc_mid - 0.5*ww, sc_mid + 0.5*ww, zlo, d_zhi)
    if panel is None:
        return
    if void:
        res = rg.Brep.CreateBooleanDifference([panel], [void], TOL)
        if res:
            for r in res:
                if r and r.IsSolid:
                    Wall_Breps.append(r)
                    Wall_Colors.append(WALL_COL)
        else:
            if panel.IsSolid:
                Wall_Breps.append(panel)
                Wall_Colors.append(WALL_COL)
    else:
        if panel.IsSolid:
            Wall_Breps.append(panel)
            Wall_Colors.append(WALL_COL)
    if door_ind:
        Door_Breps.append(door_ind)


def emit_corridor_core_doors(new_corr_breps, z0, z1):
    """Emit one wall+door panel at each corridor/core shared face."""
    if not compute_walls:
        return
    if not cores_in:
        return
    fh = z1 - z0
    d_zhi = z0 + min(DOOR_H, fh - 0.05)
    seen = set()
    for corr_b in new_corr_breps:
        cb = aabb(corr_b)
        for core_b in cores_in:
            rb = aabb(core_b)
            if rb.Max.Z < z0 - EPS or rb.Min.Z > z1 + EPS:
                continue
            x_lo = max(cb.Min.X, rb.Min.X)
            x_hi = min(cb.Max.X, rb.Max.X)
            if x_hi - x_lo > EPS:
                for (cy, ry, inward) in [
                        (cb.Max.Y, rb.Min.Y, False),
                        (cb.Min.Y, rb.Max.Y, True)]:
                    if abs(cy - ry) < EPS:
                        key = ('y', round(cy, 4), round(x_lo, 4), round(x_hi, 4))
                        if key not in seen:
                            seen.add(key)
                            _corr_core_door('y', cy, inward, x_lo, x_hi, z0, z1, d_zhi)
            y_lo = max(cb.Min.Y, rb.Min.Y)
            y_hi = min(cb.Max.Y, rb.Max.Y)
            if y_hi - y_lo > EPS:
                for (cx, rx, inward) in [
                        (cb.Max.X, rb.Min.X, False),
                        (cb.Min.X, rb.Max.X, True)]:
                    if abs(cx - rx) < EPS:
                        key = ('x', round(cx, 4), round(y_lo, 4), round(y_hi, 4))
                        if key not in seen:
                            seen.add(key)
                            _corr_core_door('x', cx, inward, y_lo, y_hi, z0, z1, d_zhi)


# ------------------------------------------------------------
# Main layout generation
# ------------------------------------------------------------

for fi, fb in enumerate(floors_sorted):
    bb = aabb(fb)

    x0 = bb.Min.X
    x1 = bb.Max.X
    y0 = bb.Min.Y
    y1 = bb.Max.Y
    z0 = bb.Min.Z
    z1 = bb.Max.Z

    fh = z1 - z0
    corr_start = len(Corridor_Breps)

    long_is_x = (x1 - x0) >= (y1 - y0)

    if long_is_x:
        a0, a1 = x0, x1
        c0, c1 = y0, y1
    else:
        a0, a1 = y0, y1
        c0, c1 = x0, x1

    across = c1 - c0

    # Map (along, across) -> world box at full floor height.
    def AAB(al0, al1, ac0, ac1):
        if long_is_x:
            return box_brep(al0, al1, ac0, ac1, z0, z1)
        else:
            return box_brep(ac0, ac1, al0, al1, z0, z1)

    # Same mapping but with an explicit z range (for openings + walls).
    def AABz(al0, al1, ac0, ac1, zlo, zhi):
        if long_is_x:
            return box_brep(al0, al1, ac0, ac1, zlo, zhi)
        else:
            return box_brep(ac0, ac1, al0, al1, zlo, zhi)

    def place(node, al0, al1, ci, cfac):
        # Returns leaf records, keeping the unit-square coords so we can tell
        # which edges are interior partitions vs corridor vs facade.
        leaves = []
        eval_split(node, 0.0, 1.0, 0.0, 1.0, leaves)

        out = []

        for u0, u1, v0, v1, lab in leaves:
            aL0 = al0 + (al1 - al0) * u0
            aL1 = al0 + (al1 - al0) * u1

            cR0 = ci + (cfac - ci) * v0   # corridor-facing side
            cR1 = ci + (cfac - ci) * v1   # facade-facing side

            out.append((aL0, aL1, cR0, cR1, u0, u1, v0, v1, lab))

        return out

    def open_across(C, w, zlo, zhi, amin, amax, max_frac=0.80):
        # Opening in a wall that runs ALONG the building (constant across=C).
        ac = 0.5 * (amin + amax)
        ww = min(w, (amax - amin) * max_frac)
        t = wall_thickness
        # EPS extension guarantees the cutter passes fully through both wall faces.
        cut = AABz(ac - 0.5 * ww, ac + 0.5 * ww, C - t - EPS, C + t + EPS, zlo, zhi)
        pan = AABz(ac - 0.5 * ww, ac + 0.5 * ww, C - 0.5 * t, C + 0.5 * t, zlo, zhi)
        return cut, pan

    def open_along(A, w, zlo, zhi, cmin, cmax, max_frac=0.80):
        # Opening in a wall PERPENDICULAR to the building (constant along=A).
        cc = 0.5 * (cmin + cmax)
        ww = min(w, (cmax - cmin) * max_frac)
        t = wall_thickness
        # EPS extension guarantees the cutter passes fully through both wall faces.
        cut = AABz(A - t - EPS, A + t + EPS, cc - 0.5 * ww, cc + 0.5 * ww, zlo, zhi)
        pan = AABz(A - 0.5 * t, A + 0.5 * t, cc - 0.5 * ww, cc + 0.5 * ww, zlo, zhi)
        return cut, pan

    def emit_room(rec, aid, fi, end_lo, end_hi, is_hub=False, extra_voids=None):
        aL0, aL1, cR0, cR1, u0, u1, v0, v1, lab = rec

        t = wall_thickness
        ht = 0.5 * t

        amin, amax = (aL0, aL1) if aL0 <= aL1 else (aL1, aL0)

        # Which edges are building-exterior short facades?
        ext_lo = end_lo and (u0 <= 1e-9)
        ext_hi = end_hi and (u1 >= 1.0 - 1e-9)

        is_corridor = (v0 <= 1e-9)        # cR0 side faces the real corridor
        is_facade = (v1 >= 1.0 - 1e-9)    # cR1 side faces the building facade

        # Per-side wall thickness: full t on a true exterior/corridor wall,
        # half t on a shared partition (the neighbour supplies the other half).
        ia_lo = t if ext_lo else ht
        ia_hi = t if ext_hi else ht
        inset_cR0 = t if is_corridor else ht
        inset_cR1 = t if is_facade else ht

        # Map corridor/facade insets onto numeric min/max.
        if cR0 <= cR1:
            cmin, cmax = cR0, cR1
            ic_lo, ic_hi = inset_cR0, inset_cR1
        else:
            cmin, cmax = cR1, cR0
            ic_lo, ic_hi = inset_cR1, inset_cR0

        full = AAB(amin, amax, cmin, cmax)
        if full is None:
            return

        if not compute_walls:
            emit(full, lab, aid, fi)
            return

        in_a0 = amin + ia_lo
        in_a1 = amax - ia_hi
        in_c0 = cmin + ic_lo
        in_c1 = cmax - ic_hi

        # Degenerate (too small to host walls): emit as a plain space.
        if (in_a1 - in_a0) <= EPS or (in_c1 - in_c0) <= EPS:
            emit(full, lab, aid, fi)
            return

        # Warning-only: undersized rooms are generated but flagged.
        if lab not in ("Hall", "Corridor"):
            _int_a = in_a1 - in_a0
            _int_c = in_c1 - in_c0
            if min(_int_a, _int_c) < MIN_ROOM_DIM:
                warn("%s Apt%d: %.2fm×%.2fm interior < %.1fm min" %
                     (lab, aid, _int_a, _int_c, MIN_ROOM_DIM))

        interior = AAB(in_a0, in_a1, in_c0, in_c1)

        # Door z-range (clamped to floor height).
        d_zhi = z0 + min(DOOR_H, fh - 0.05)

        voids = []
        doors = []
        windows = []

        # cR0: corridor entry only for the hub room.
        # Non-hub rooms facing the corridor get a solid wall.
        # Internal v-partitions (v0 > 0) get no door: hub-and-spoke connects
        # them through the Hub via u-axis doors, not through each other.
        if is_corridor and is_hub:
            cut, pan = open_across(cR0, DOOR_W, z0, d_zhi, amin, amax)
            if cut:
                voids.append(cut)
            if pan:
                doors.append(pan)

        # cR1: facade → exterior window (core-aware: skip core-blocked span).
        if is_facade:
            _blk = _core_segment_overlap(cR1, not long_is_x, amin, amax)
            free_lo, free_hi = _largest_free_segment(amin, amax, _blk)
            free_span = free_hi - free_lo
            _min_span = MIN_WINDOW_SPAN if lab == "Hall" else WIN_W + 2.0 * wall_thickness
            if free_span >= _min_span:
                ca = bool(_blk) or _faces_core_across_gap(
                    cR1, not long_is_x, cR1 < cR0, amin, amax, corridor_width * 2.0)
                ww, wzlo, wzhi = win_geometry(lab, free_span, fh, z0, core_aligned=ca)
                cut, pan = open_across(cR1, ww, wzlo, wzhi, free_lo, free_hi, max_frac=0.95)
                if cut:
                    voids.append(cut)
                if pan:
                    windows.append(pan)

        # along-min short side (constant along=amin).
        if ext_lo:
            _blk = _core_segment_overlap(amin, long_is_x, cmin, cmax)
            free_lo, free_hi = _largest_free_segment(cmin, cmax, _blk)
            free_span = free_hi - free_lo
            _min_span = MIN_WINDOW_SPAN if lab == "Hall" else WIN_W + 2.0 * wall_thickness
            if free_span >= _min_span:
                ca = bool(_blk) or _faces_core_across_gap(
                    amin, long_is_x, True, cmin, cmax, corridor_width * 2.0)
                ww, wzlo, wzhi = win_geometry(lab, free_span, fh, z0, core_aligned=ca)
                cut, pan = open_along(amin, ww, wzlo, wzhi, free_lo, free_hi, max_frac=0.95)
                if cut:
                    voids.append(cut)
                if pan:
                    windows.append(pan)

        # along-max short side (constant along=amax).
        if ext_hi:
            _blk = _core_segment_overlap(amax, long_is_x, cmin, cmax)
            free_lo, free_hi = _largest_free_segment(cmin, cmax, _blk)
            free_span = free_hi - free_lo
            _min_span = MIN_WINDOW_SPAN if lab == "Hall" else WIN_W + 2.0 * wall_thickness
            if free_span >= _min_span:
                ca = bool(_blk) or _faces_core_across_gap(
                    amax, long_is_x, False, cmin, cmax, corridor_width * 2.0)
                ww, wzlo, wzhi = win_geometry(lab, free_span, fh, z0, core_aligned=ca)
                cut, pan = open_along(amax, ww, wzlo, wzhi, free_lo, free_hi, max_frac=0.95)
                if cut:
                    voids.append(cut)
                if pan:
                    windows.append(pan)

        # --- Step 1: create hollow shell (full − interior) ---
        shells = rg.Brep.CreateBooleanDifference([full], [interior], TOL)
        if not shells:
            emit_wall(full)  # last-resort: solid block
        else:
            shells = [s for s in shells if s and s.IsSolid]
            # --- Step 2: subtract each opening void one at a time ---
            # A failed subtraction issues a warning and keeps the current shell
            # unchanged, so no void can silently vanish through a combined fallback.
            for v in voids + (extra_voids or []):
                if v is None or not shells:
                    continue
                next_shells = []
                for sh in shells:
                    res = rg.Brep.CreateBooleanDifference([sh], [v], TOL)
                    if res:
                        next_shells.extend(r for r in res if r and r.IsSolid)
                    else:
                        warn("Opening subtraction failed for %s Apt%d" % (lab, aid))
                        next_shells.append(sh)
                shells = [s for s in next_shells if s and s.IsSolid]
            for sh in shells:
                if sh and sh.IsSolid:
                    emit_wall(sh)

        # room clear space + indicative opening volumes
        emit(interior, lab, aid, fi)
        Door_Breps.extend(doors)
        Window_Breps.extend(windows)

    def emit_apt(recs, apt_id, end_lo, end_hi):
        """Two-pass apartment emitter.

        Pass 1: detect shared walls between Hub and each other room;
                build one door void+panel per pair, centred on the actual
                overlap segment (geometry-based, not index-based).
        Pass 2: emit each room shell with its per-room extra voids applied.
        """
        _hub = "Hall" if any(r[8] == "Hall" for r in recs) else "Living"
        hub_idx = next((i for i, r in enumerate(recs) if r[8] == _hub), None)
        d_zhi_apt = z0 + min(DOOR_H, fh - 0.05)
        extra_voids = [[] for _ in recs]
        apt_doors = []

        if hub_idx is not None:
            hub_rec = recs[hub_idx]
            for i, rec in enumerate(recs):
                if i == hub_idx:
                    continue
                sw = find_shared_wall(hub_rec, rec)
                if sw is not None:
                    ori, coord, seg0, seg1 = sw
                    if is_open_plan_pair(_hub, rec[8]):
                        # Hall ↔ Living: full-height open-plan cut.
                        # End returns = wall_thickness at each end of the shared span;
                        # cutter depth = 2*wall_thickness + 2*EPS to remove both half-wall shells.
                        t = wall_thickness
                        open_lo = seg0 + t
                        open_hi = seg1 - t
                        if open_hi - open_lo <= EPS:
                            warn("Hall-Living shared wall %.2fm too short for open-plan cut" %
                                 (seg1 - seg0))
                            void_b = None
                        else:
                            if ori == "along":
                                void_b = AABz(coord - t - EPS, coord + t + EPS,
                                              open_lo, open_hi, z0, z1)
                            else:
                                void_b = AABz(open_lo, open_hi,
                                              coord - t - EPS, coord + t + EPS, z0, z1)
                        pan_b = None
                    else:
                        if ori == "along":
                            void_b, pan_b = open_along(coord, DOOR_W, z0, d_zhi_apt, seg0, seg1)
                        else:
                            void_b, pan_b = open_across(coord, DOOR_W, z0, d_zhi_apt, seg0, seg1)
                    if void_b:
                        extra_voids[hub_idx].append(void_b)
                        extra_voids[i].append(void_b)
                    if pan_b:
                        apt_doors.append(pan_b)

        for i, rec in enumerate(recs):
            emit_room(rec, apt_id, fi, end_lo, end_hi,
                      is_hub=(rec[8] == _hub),
                      extra_voids=extra_voids[i])
        Door_Breps.extend(apt_doors)

    # --------------------------------------------------------
    # Thin transverse cross-corridor at the core
    # --------------------------------------------------------

    spans = [(a0, a1)]

    if cores_in:
        if long_is_x:
            kmin = min(b.Min.X for b in core_bbs)
            kmax = max(b.Max.X for b in core_bbs)
        else:
            kmin = min(b.Min.Y for b in core_bbs)
            kmax = max(b.Max.Y for b in core_bbs)

        if kmax > a0 and kmin < a1:
            kcen = 0.5 * (kmin + kmax)

            tw = min(corridor_width, (a1 - a0) * 0.4)

            tca0 = max(a0, kcen - tw / 2.0)
            tca1 = min(a1, kcen + tw / 2.0)

            _cc = AAB(tca0, tca1, c0, c1)
            emit(_cc, "Corridor", -1, fi)
            if _cc:
                emit_corridor_ext_windows(_cc, bb, z0, z1)

            spans = [(a0, tca0), (tca1, a1)]

    # --------------------------------------------------------
    # Fill remaining spans with apartments and main corridors
    # --------------------------------------------------------

    for s0, s1 in spans:
        span = s1 - s0

        if span <= EPS:
            continue

        if span < apt_width * 0.6:
            _sc = AAB(s0, s1, c0, c1)
            emit(_sc, "Corridor", -1, fi)
            if _sc:
                emit_corridor_ext_windows(_sc, bb, z0, z1)
            continue

        nn = max(1, int(round(span / apt_width)))
        st = span / nn

        e = [s0 + i * st for i in range(nn + 1)]

        # Corridor bounds are constant across all bays in this span.
        if layout_type == 1:
            cw = min(corridor_width, across * 0.5)
            clo = c0
            chi = c0 + cw
        else:
            cw = min(corridor_width, across * 0.6)
            m = 0.5 * (c0 + c1)
            clo = m - cw / 2.0
            chi = m + cw / 2.0

        # One corridor Brep for the full span instead of one per bay.
        _lc = AAB(s0, s1, clo, chi)
        emit(_lc, "Corridor", -1, fi)
        if _lc:
            emit_corridor_ext_windows(_lc, bb, z0, z1)

        for k in range(nn):
            end_lo = abs(e[k] - a0) < EPS
            end_hi = abs(e[k + 1] - a1) < EPS

            if layout_type == 1:
                recs = place(TYPES[tindex % 3], e[k], e[k + 1], chi, c1)
                emit_apt(recs, apt, end_lo, end_hi)
                apt += 1
                tindex += 1

            else:
                recs = place(TYPES[tindex % 3], e[k], e[k + 1], clo, c0)
                emit_apt(recs, apt, end_lo, end_hi)
                apt += 1

                recs = place(TYPES[(tindex + 1) % 3], e[k], e[k + 1], chi, c1)
                emit_apt(recs, apt, end_lo, end_hi)
                apt += 1
                tindex += 1

    emit_corridor_core_doors(Corridor_Breps[corr_start:], z0, z1)


# ------------------------------------------------------------
# Console report
# ------------------------------------------------------------

print(
    "floors:%d spaces:%d apts:%d corridor:%d walls:%d doors:%d windows:%d" %
    (
        len(floors_sorted),
        len(Interior_Breps),
        len(set(i for i in Apartment_Id if i >= 0)),
        len(Corridor_Breps),
        len(Wall_Breps),
        len(Door_Breps),
        len(Window_Breps)
    )
)