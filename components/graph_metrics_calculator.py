# MaCAD S.3 - Assignment 2
# CSV export component
# Rhino 8 Script Editor / Python 3
#
# Inputs:
#   Nodes_CSV      ITEM / Text
#   Edges_CSV      ITEM / Text
#   Metric_CSV     ITEM / Text
#   folder_path    ITEM / Text
#   save           ITEM / Boolean
#
# Outputs:
#   Saved_Paths
#   Report

import os
import datetime


# ------------------------------------------------------------
# Safe input reading
# ------------------------------------------------------------

def get_input(name, default):
    try:
        return globals()[name]
    except:
        return default


def dflt(v, d):
    return d if v is None else v


raw_save = get_input("save", False)

try:
    save_value = bool(dflt(raw_save, False))
except:
    save_value = False


try:
    folder_path_value = str(dflt(get_input("folder_path", ""), ""))
except:
    folder_path_value = ""


try:
    nodes_csv = str(dflt(get_input("Nodes_CSV", ""), ""))
except:
    nodes_csv = ""


try:
    edges_csv = str(dflt(get_input("Edges_CSV", ""), ""))
except:
    edges_csv = ""


try:
    metric_csv = str(dflt(get_input("Metric_CSV", ""), ""))
except:
    metric_csv = ""


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------

def clean_folder(path):
    path = path.strip().strip('"').strip("'")

    if path == "":
        return None

    return path


def write_text(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


# ------------------------------------------------------------
# Save files
# ------------------------------------------------------------

Saved_Paths = []
folder = clean_folder(folder_path_value)

if not save_value:
    Report = "\n".join([
        "CSV EXPORT READY",
        "----------------",
        "Set save = True to write files.",
        "",
        "Folder path:",
        str(folder_path_value),
        "",
        "Expected files:",
        "- nodes_YYYYMMDD_HHMMSS.csv",
        "- edges_YYYYMMDD_HHMMSS.csv",
        "- metrics_YYYYMMDD_HHMMSS.csv"
    ])

else:
    if folder is None:
        Report = "ERROR: folder_path is empty."

    elif not os.path.isdir(folder):
        Report = "ERROR: folder_path does not exist:\n%s" % folder

    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

        nodes_path = os.path.join(folder, "nodes_%s.csv" % timestamp)
        edges_path = os.path.join(folder, "edges_%s.csv" % timestamp)
        metrics_path = os.path.join(folder, "metrics_%s.csv" % timestamp)

        try:
            write_text(nodes_path, nodes_csv)
            write_text(edges_path, edges_csv)
            write_text(metrics_path, metric_csv)

            Saved_Paths = [
                nodes_path,
                edges_path,
                metrics_path
            ]

            Report = "\n".join([
                "CSV EXPORT COMPLETE",
                "-------------------",
                "Saved files:",
                nodes_path,
                edges_path,
                metrics_path
            ])

        except Exception as e:
            Report = "ERROR while saving files:\n%s" % str(e)


print(Report)