# MaCAD S.3 - Assignment 2
# Building spaces to graph
# Rhino 8 Script Editor / Python 3
#
# Purpose:
#   Convert generated residential spaces into a graph.
#
# Graph logic:
#   Nodes = rooms, corridors, core
#   Edges = touching / connected spaces
#   Attributes = type, floor, apartment ID, centroid
#
# Inputs:
#   Interior_Breps              LIST
#   Space_Types                 LIST
#   Apartment_Id                LIST
#   Floor_Index                 LIST
#   Core_Brep                   LIST
#
# Optional inputs:
#   touch_tolerance             ITEM
#   make_core_vertical_edges    ITEM
#
# Outputs:
#   Node_Points
#   Node_Ids
#   Node_Types
#   Node_Floors
#   Node_ApartmentIds
#   Node_Labels
#   Edge_Lines
#   Edge_From
#   Edge_To
#   Edge_Type
#   Nodes_CSV
#   Edges_CSV
#   Report

import Rhino
import Rhino.Geometry as rg
import scriptcontext as sc
import System


# ------------------------------------------------------------
# Tolerance
# ------------------------------------------------------------

TOL = 0.001

try:
    if sc.doc and sc.doc.ModelAbsoluteTolerance > 0:
        TOL = sc.doc.ModelAbsoluteTolerance
except:
    pass


def dflt(v, d):
    return d if v is None else v


try:
    touch_tolerance = float(dflt(touch_tolerance, TOL * 10.0))
except:
    touch_tolerance = TOL * 10.0


try:
    make_core_vertical_edges = bool(dflt(make_core_vertical_edges, True))
except:
    make_core_vertical_edges = True


EPS = max(TOL * 5.0, touch_tolerance)


# ------------------------------------------------------------
# Input helpers
# ------------------------------------------------------------

def to_list(x):
    """
    Converts Grasshopper input to a normal Python list.

    Handles:
    - None
    - single item
    - list / tuple
    - Grasshopper iterable data
    """

    if x is None:
        return []

    if isinstance(x, list):
        return x

    if isinstance(x, tuple):
        return list(x)

    try:
        return list(x)
    except:
        return [x]


def coerce_brep(x):
    """
    Converts incoming Grasshopper / Rhino data to a Brep.

    Accepts:
    - Rhino.Geometry.Brep
    - Rhino object Guid
    - Grasshopper wrapper with .Value
    - Rhino object with .Geometry
    """

    if x is None:
        return None

    # Already a Brep.
    if isinstance(x, rg.Brep):
        if x.IsValid:
            return x
        return None

    # Grasshopper Goo wrapper.
    if hasattr(x, "Value"):
        try:
            return coerce_brep(x.Value)
        except:
            pass

    # Rhino document Guid.
    if isinstance(x, System.Guid):
        try:
            obj = sc.doc.Objects.FindId(x)

            if obj is None:
                return None

            geo = obj.Geometry

            if isinstance(geo, rg.Brep) and geo.IsValid:
                return geo

            return None
        except:
            return None

    # Rhino object with Geometry property.
    if hasattr(x, "Geometry"):
        try:
            geo = x.Geometry

            if isinstance(geo, rg.Brep) and geo.IsValid:
                return geo
        except:
            pass

    return None


def safe_item(values, i, default):
    try:
        if i < len(values):
            return values[i]
    except:
        pass

    return default


def as_int(value, default):
    try:
        return int(value)
    except:
        return default


def as_text(value, default):
    try:
        if value is None:
            return default
        return str(value)
    except:
        return default


# ------------------------------------------------------------
# Clean inputs
# ------------------------------------------------------------

spaces = []

for item in to_list(Interior_Breps):
    b = coerce_brep(item)

    if b is not None:
        spaces.append(b)


cores = []

for item in to_list(Core_Brep):
    b = coerce_brep(item)

    if b is not None:
        cores.append(b)


types_in = to_list(Space_Types)
apts_in = to_list(Apartment_Id)
floors_in = to_list(Floor_Index)


# ------------------------------------------------------------
# Geometry helpers
# ------------------------------------------------------------

def aabb(brep):
    return brep.GetBoundingBox(True)


def bbox_center(bb):
    return rg.Point3d(
        0.5 * (bb.Min.X + bb.Max.X),
        0.5 * (bb.Min.Y + bb.Max.Y),
        0.5 * (bb.Min.Z + bb.Max.Z)
    )


def overlap_len(a0, a1, b0, b1):
    return min(a1, b1) - max(a0, b0)


def boxes_touch(bb1, bb2, tol):
    """
    Returns True if two bounding boxes touch by face.
    This approximates adjacency between rectangular room Breps.
    """

    x_overlap = overlap_len(bb1.Min.X, bb1.Max.X, bb2.Min.X, bb2.Max.X)
    y_overlap = overlap_len(bb1.Min.Y, bb1.Max.Y, bb2.Min.Y, bb2.Max.Y)
    z_overlap = overlap_len(bb1.Min.Z, bb1.Max.Z, bb2.Min.Z, bb2.Max.Z)

    # Same floor / vertical overlap required.
    if z_overlap <= tol:
        return False

    # Face contact in X direction.
    touch_x = (
        abs(bb1.Max.X - bb2.Min.X) <= tol or
        abs(bb2.Max.X - bb1.Min.X) <= tol
    )

    if touch_x and y_overlap > tol:
        return True

    # Face contact in Y direction.
    touch_y = (
        abs(bb1.Max.Y - bb2.Min.Y) <= tol or
        abs(bb2.Max.Y - bb1.Min.Y) <= tol
    )

    if touch_y and x_overlap > tol:
        return True

    return False


def boxes_overlap_or_touch(bb1, bb2, tol):
    """
    Used for core connection.
    Allows touching or tiny overlap.
    """

    separated = (
        bb1.Max.X < bb2.Min.X - tol or
        bb1.Min.X > bb2.Max.X + tol or
        bb1.Max.Y < bb2.Min.Y - tol or
        bb1.Min.Y > bb2.Max.Y + tol or
        bb1.Max.Z < bb2.Min.Z - tol or
        bb1.Min.Z > bb2.Max.Z + tol
    )

    return not separated


# ------------------------------------------------------------
# Build space nodes
# ------------------------------------------------------------

nodes = []
bbs = []

for i, brep in enumerate(spaces):
    bb = aabb(brep)
    pt = bbox_center(bb)

    stype = as_text(safe_item(types_in, i, "Space"), "Space")
    aid = as_int(safe_item(apts_in, i, -999), -999)
    floor = as_int(safe_item(floors_in, i, 0), 0)

    node_id = "S_%04d" % i

    nodes.append({
        "id": node_id,
        "type": stype,
        "floor": floor,
        "apartment_id": aid,
        "point": pt,
        "brep": brep,
        "is_core": False
    })

    bbs.append(bb)


# ------------------------------------------------------------
# Infer floor z-ranges from space nodes
# ------------------------------------------------------------

floor_ranges = {}

for i, n in enumerate(nodes):
    f = n["floor"]
    bb = bbs[i]

    if f not in floor_ranges:
        floor_ranges[f] = [bb.Min.Z, bb.Max.Z]
    else:
        floor_ranges[f][0] = min(floor_ranges[f][0], bb.Min.Z)
        floor_ranges[f][1] = max(floor_ranges[f][1], bb.Max.Z)

known_floors = sorted(floor_ranges.keys())


# ------------------------------------------------------------
# Add one core node per floor
# ------------------------------------------------------------

core_node_indices = []

if cores and known_floors:
    core_union = cores[0].GetBoundingBox(True)

    for c in cores[1:]:
        core_union.Union(c.GetBoundingBox(True))

    for f in known_floors:
        z0, z1 = floor_ranges[f]

        core_pt = rg.Point3d(
            0.5 * (core_union.Min.X + core_union.Max.X),
            0.5 * (core_union.Min.Y + core_union.Max.Y),
            0.5 * (z0 + z1)
        )

        core_bb = rg.BoundingBox(
            rg.Point3d(core_union.Min.X, core_union.Min.Y, z0),
            rg.Point3d(core_union.Max.X, core_union.Max.Y, z1)
        )

        node_id = "CORE_F%02d" % f

        nodes.append({
            "id": node_id,
            "type": "Core",
            "floor": f,
            "apartment_id": -1,
            "point": core_pt,
            "brep": None,
            "is_core": True
        })

        bbs.append(core_bb)
        core_node_indices.append(len(nodes) - 1)


# ------------------------------------------------------------
# Build edges
# ------------------------------------------------------------

edges = []
edge_keys = set()


def add_edge(i, j, etype):
    if i == j:
        return

    a = min(i, j)
    b = max(i, j)

    # One undirected edge per pair and type.
    key = (a, b, etype)

    if key in edge_keys:
        return

    edge_keys.add(key)

    edges.append({
        "from": nodes[a]["id"],
        "to": nodes[b]["id"],
        "type": etype,
        "from_i": a,
        "to_i": b
    })


# ------------------------------------------------------------
# Space-space adjacency edges
# ------------------------------------------------------------

for i in range(len(nodes)):
    for j in range(i + 1, len(nodes)):

        ni = nodes[i]
        nj = nodes[j]

        # Core handled separately below.
        if ni["is_core"] or nj["is_core"]:
            continue

        # Only connect spaces on the same floor.
        if ni["floor"] != nj["floor"]:
            continue

        if boxes_touch(bbs[i], bbs[j], EPS):
            add_edge(i, j, "touching")


# ------------------------------------------------------------
# Core-space edges
# ------------------------------------------------------------

for ci in core_node_indices:
    core_floor = nodes[ci]["floor"]

    for si, n in enumerate(nodes):
        if n["is_core"]:
            continue

        if n["floor"] != core_floor:
            continue

        if boxes_overlap_or_touch(bbs[ci], bbs[si], EPS):
            add_edge(ci, si, "core_connection")


# ------------------------------------------------------------
# Vertical core edges
# ------------------------------------------------------------

if make_core_vertical_edges and len(core_node_indices) > 1:
    sorted_core = sorted(
        core_node_indices,
        key=lambda idx: nodes[idx]["floor"]
    )

    for a, b in zip(sorted_core[:-1], sorted_core[1:]):
        add_edge(a, b, "vertical_core")


# ------------------------------------------------------------
# Output geometry
# ------------------------------------------------------------

Node_Points = [n["point"] for n in nodes]
Node_Ids = [n["id"] for n in nodes]
Node_Types = [n["type"] for n in nodes]
Node_Floors = [n["floor"] for n in nodes]
Node_ApartmentIds = [n["apartment_id"] for n in nodes]

Node_Labels = [
    "%s | %s | F%s | Apt %s" %
    (
        n["id"],
        n["type"],
        n["floor"],
        n["apartment_id"]
    )
    for n in nodes
]

Edge_Lines = [
    rg.Line(
        nodes[e["from_i"]]["point"],
        nodes[e["to_i"]]["point"]
    )
    for e in edges
]

Edge_From = [e["from"] for e in edges]
Edge_To = [e["to"] for e in edges]
Edge_Type = [e["type"] for e in edges]


# ------------------------------------------------------------
# CSV outputs
# ------------------------------------------------------------

nodes_rows = []
nodes_rows.append("node_id,type,floor,apartment_id,x,y,z")

for n in nodes:
    p = n["point"]

    nodes_rows.append(
        "%s,%s,%s,%s,%.3f,%.3f,%.3f" %
        (
            n["id"],
            n["type"],
            n["floor"],
            n["apartment_id"],
            p.X,
            p.Y,
            p.Z
        )
    )

edges_rows = []
edges_rows.append("source,target,edge_type")

for e in edges:
    edges_rows.append(
        "%s,%s,%s" %
        (
            e["from"],
            e["to"],
            e["type"]
        )
    )

Nodes_CSV = "\n".join(nodes_rows)
Edges_CSV = "\n".join(edges_rows)


# ------------------------------------------------------------
# Report
# ------------------------------------------------------------

space_count = len([n for n in nodes if not n["is_core"]])
core_count = len([n for n in nodes if n["is_core"]])
corridor_count = len([n for n in nodes if n["type"] == "Corridor"])
room_count = space_count - corridor_count

touch_edges = len([e for e in edges if e["type"] == "touching"])
core_edges = len([e for e in edges if e["type"] == "core_connection"])
vertical_edges = len([e for e in edges if e["type"] == "vertical_core"])

Report = "\n".join([
    "GRAPH EXTRACTION REPORT",
    "-----------------------",
    "Nodes total: %d" % len(nodes),
    "Room / space nodes: %d" % room_count,
    "Corridor nodes: %d" % corridor_count,
    "Core nodes: %d" % core_count,
    "Edges total: %d" % len(edges),
    "Touching edges: %d" % touch_edges,
    "Core connection edges: %d" % core_edges,
    "Vertical core edges: %d" % vertical_edges,
    "",
    "Node attributes:",
    "- type",
    "- floor",
    "- apartment_id",
    "- x, y, z centroid",
    "",
    "Edge rule:",
    "- spaces connect when bounding boxes touch by face",
    "- core connects to spaces touching its floor slice",
    "- core floors connect vertically",
    "",
    "Warnings:",
    "- No spaces received" if len(spaces) == 0 else "- Spaces received: OK",
    "- No core received" if len(cores) == 0 else "- Core received: OK"
])

print(Report)