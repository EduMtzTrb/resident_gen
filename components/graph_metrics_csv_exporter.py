# MaCAD S.3 - Assignment 2
# Graph metrics component
# Rhino 8 Script Editor / Python 3
#
# Inputs:
#   Node_Ids              LIST
#   Node_Points           LIST
#   Node_Types            LIST
#   Node_Floors           LIST
#   Node_ApartmentIds     LIST
#   Edge_From             LIST
#   Edge_To               LIST
#   start_node_id         ITEM, optional
#
# Outputs:
#   Degree
#   Degree_Centrality
#   Betweenness
#   Clustering
#   Shortest_From_Start
#   Metric_Labels
#   Metric_CSV
#   Report

from collections import deque


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def to_list(x):
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


def safe_item(values, i, default):
    try:
        if i < len(values):
            return values[i]
    except:
        pass

    return default


def as_text(x, default=""):
    try:
        if x is None:
            return default
        return str(x)
    except:
        return default


def as_int(x, default=0):
    try:
        return int(x)
    except:
        return default


# ------------------------------------------------------------
# Clean inputs
# ------------------------------------------------------------

node_ids = [as_text(x) for x in to_list(Node_Ids)]
node_types = [as_text(x, "Space") for x in to_list(Node_Types)]
node_floors = [as_int(x, 0) for x in to_list(Node_Floors)]
node_apts = [as_int(x, -999) for x in to_list(Node_ApartmentIds)]

edge_from = [as_text(x) for x in to_list(Edge_From)]
edge_to = [as_text(x) for x in to_list(Edge_To)]

try:
    start_node_id = as_text(start_node_id, "")
except:
    start_node_id = ""


n = len(node_ids)

id_to_i = {}
for i, node_id in enumerate(node_ids):
    id_to_i[node_id] = i


# ------------------------------------------------------------
# Build undirected adjacency list
# ------------------------------------------------------------

adj = {}

for i in range(n):
    adj[i] = set()


for a_id, b_id in zip(edge_from, edge_to):
    if a_id not in id_to_i:
        continue

    if b_id not in id_to_i:
        continue

    a = id_to_i[a_id]
    b = id_to_i[b_id]

    if a == b:
        continue

    adj[a].add(b)
    adj[b].add(a)


# ------------------------------------------------------------
# Degree centrality
# ------------------------------------------------------------

Degree = [len(adj[i]) for i in range(n)]

if n > 1:
    Degree_Centrality = [float(d) / float(n - 1) for d in Degree]
else:
    Degree_Centrality = [0.0 for d in Degree]


# ------------------------------------------------------------
# Betweenness centrality
# Brandes algorithm, unweighted undirected graph
# ------------------------------------------------------------

def betweenness_centrality(adj, n):
    cb = [0.0 for _ in range(n)]

    for s in range(n):
        stack = []
        pred = [[] for _ in range(n)]

        sigma = [0.0 for _ in range(n)]
        sigma[s] = 1.0

        dist = [-1 for _ in range(n)]
        dist[s] = 0

        q = deque()
        q.append(s)

        while q:
            v = q.popleft()
            stack.append(v)

            for w in adj[v]:
                if dist[w] < 0:
                    q.append(w)
                    dist[w] = dist[v] + 1

                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)

        delta = [0.0 for _ in range(n)]

        while stack:
            w = stack.pop()

            for v in pred[w]:
                if sigma[w] != 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])

            if w != s:
                cb[w] += delta[w]

    # Undirected graph correction.
    cb = [x / 2.0 for x in cb]

    # Normalization.
    if n > 2:
        scale = 2.0 / float((n - 1) * (n - 2))
        cb = [x * scale for x in cb]

    return cb


Betweenness = betweenness_centrality(adj, n)


# ------------------------------------------------------------
# Clustering coefficient
# ------------------------------------------------------------

def clustering_for_node(i):
    neighbors = list(adj[i])
    k = len(neighbors)

    if k < 2:
        return 0.0

    links = 0

    for a_index in range(k):
        for b_index in range(a_index + 1, k):
            a = neighbors[a_index]
            b = neighbors[b_index]

            if b in adj[a]:
                links += 1

    possible = k * (k - 1) / 2.0

    if possible == 0:
        return 0.0

    return float(links) / possible


Clustering = [clustering_for_node(i) for i in range(n)]


# ------------------------------------------------------------
# Shortest path distance from start node
# ------------------------------------------------------------

def find_default_start():
    # Prefer first core node.
    for i, t in enumerate(node_types):
        if t.lower() == "core":
            return i

    # Otherwise prefer first corridor.
    for i, t in enumerate(node_types):
        if t.lower() == "corridor":
            return i

    # Otherwise first node.
    if n > 0:
        return 0

    return None


if start_node_id and start_node_id in id_to_i:
    start_i = id_to_i[start_node_id]
else:
    start_i = find_default_start()


Shortest_From_Start = [-1 for _ in range(n)]

if start_i is not None:
    q = deque()
    q.append(start_i)
    Shortest_From_Start[start_i] = 0

    while q:
        v = q.popleft()

        for w in adj[v]:
            if Shortest_From_Start[w] == -1:
                Shortest_From_Start[w] = Shortest_From_Start[v] + 1
                q.append(w)


# ------------------------------------------------------------
# Labels for visualization
# ------------------------------------------------------------

Metric_Labels = []

for i in range(n):
    label = (
        "%s | %s | F%s | Apt %s\n"
        "deg=%s | bet=%.3f | clust=%.3f | d_core=%s"
        %
        (
            node_ids[i],
            safe_item(node_types, i, "Space"),
            safe_item(node_floors, i, 0),
            safe_item(node_apts, i, -999),
            Degree[i],
            Betweenness[i],
            Clustering[i],
            Shortest_From_Start[i]
        )
    )

    Metric_Labels.append(label)


# ------------------------------------------------------------
# CSV output
# ------------------------------------------------------------

rows = []
rows.append(
    "node_id,type,floor,apartment_id,degree,degree_centrality,betweenness,clustering,shortest_from_start"
)

for i in range(n):
    rows.append(
        "%s,%s,%s,%s,%s,%.6f,%.6f,%.6f,%s"
        %
        (
            node_ids[i],
            safe_item(node_types, i, "Space"),
            safe_item(node_floors, i, 0),
            safe_item(node_apts, i, -999),
            Degree[i],
            Degree_Centrality[i],
            Betweenness[i],
            Clustering[i],
            Shortest_From_Start[i]
        )
    )

Metric_CSV = "\n".join(rows)


# ------------------------------------------------------------
# Summary report
# ------------------------------------------------------------

def max_node(values):
    if not values:
        return ("None", 0)

    max_i = 0
    max_v = values[0]

    for i, v in enumerate(values):
        if v > max_v:
            max_i = i
            max_v = v

    return (node_ids[max_i], max_v)


max_degree_node, max_degree_value = max_node(Degree)
max_bet_node, max_bet_value = max_node(Betweenness)
max_cluster_node, max_cluster_value = max_node(Clustering)

reachable = len([d for d in Shortest_From_Start if d >= 0])
unreachable = n - reachable

start_label = "None"
if start_i is not None:
    start_label = node_ids[start_i]

Report = "\n".join([
    "GRAPH METRICS REPORT",
    "--------------------",
    "Nodes: %d" % n,
    "Edges: %d" % len(edge_from),
    "Start node: %s" % start_label,
    "",
    "Highest degree:",
    "- %s = %s" % (max_degree_node, max_degree_value),
    "",
    "Highest betweenness:",
    "- %s = %.6f" % (max_bet_node, max_bet_value),
    "",
    "Highest clustering:",
    "- %s = %.6f" % (max_cluster_node, max_cluster_value),
    "",
    "Reachability:",
    "- Reachable nodes: %d" % reachable,
    "- Unreachable nodes: %d" % unreachable,
    "",
    "Spatial reading:",
    "- High degree = connector space",
    "- High betweenness = bridge or bottleneck",
    "- High clustering = local apartment grouping",
    "- Short path from core = better accessibility"
])

print(Report)