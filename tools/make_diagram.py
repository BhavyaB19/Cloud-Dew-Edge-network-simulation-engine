"""Draw the architecture diagram: ``python tools/make_diagram.py`` → ``docs/architecture.png``.

Shows the brief's required parts: users and tasks, the placement logic, the
Edge/Fog/Cloud nodes, and the results; plus the VM manager, access control and
the two interfaces. Drawn with matplotlib so it can be regenerated whenever the
design changes.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "architecture.png"

SURFACE, INK, INK_2, EDGE_LINE = "#fcfcfb", "#0b0b0b", "#52514e", "#8f8e88"
TIER = {"edge": "#2a78d6", "fog": "#eb6834", "cloud": "#1baf7a"}
ACCENT_FILL = "#e8f1fc"


def box(ax, x, y, w, h, title, lines=(), fill="white", edge=EDGE_LINE, title_color=INK, bold_edge=False):
    """Draw a rounded box with a bold title and smaller body lines; return its centre and size."""
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor=fill, edgecolor=edge, linewidth=2 if bold_edge else 1.2))
    ax.text(x + w / 2, y + h - 0.28, title, ha="center", va="top", fontsize=11, fontweight="bold", color=title_color)
    for i, line in enumerate(lines):
        ax.text(x + w / 2, y + h - 0.68 - 0.34 * i, line, ha="center", va="top", fontsize=8.5, color=INK_2)
    return (x, y, w, h)


def arrow(ax, start, end, label=None, label_offset=(0, 0.14), rad=0.0):
    """Draw an arrow between two points with an optional label beside it."""
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14, color=EDGE_LINE, linewidth=1.3,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=2, shrinkB=2))
    if label:
        mx, my = (start[0] + end[0]) / 2 + label_offset[0], (start[1] + end[1]) / 2 + label_offset[1]
        ax.text(mx, my, label, ha="center", va="bottom", fontsize=8, color=INK_2, style="italic")


def right(b, dy=0.0):
    """Middle of a box's right edge (shifted by dy)."""
    return (b[0] + b[2], b[1] + b[3] / 2 + dy)


def left(b, dy=0.0):
    """Middle of a box's left edge (shifted by dy)."""
    return (b[0], b[1] + b[3] / 2 + dy)


def draw(path: Path = OUTPUT) -> Path:
    """Draw the diagram and save it as a PNG.

    Args:
        path: Where to save it.

    Returns:
        The path written.
    """
    fig, ax = plt.subplots(figsize=(16.5, 9), facecolor=SURFACE)
    ax.set_xlim(0, 20.6)
    ax.set_ylim(0, 11.2)
    ax.axis("off")
    ax.text(0.2, 11.0, "EdgeFogSim architecture", fontsize=16, fontweight="bold", color=INK, va="top")
    ax.text(0.2, 10.45, "Tasks flow left to right. Both interfaces call the same engine, every request passes "
                        "access control, and only the VM manager changes node usage.", fontsize=10, color=INK_2,
            va="top")

    users = box(ax, 0.2, 5.4, 2.5, 2.7, "Users", ["hospital-a (tenant)", "hospital-b (tenant)", "admin",
                                                 "login = tenant id,", "no passwords"])
    cli = box(ax, 3.3, 7.0, 2.7, 1.5, "CLI menu", ["python -m edgefogsim"])
    web = box(ax, 3.3, 5.0, 2.7, 1.5, "Streamlit app", ["python -m edgefogsim web"])
    audit = box(ax, 6.9, 8.95, 2.8, 0.9, "Audit log (CSV)")
    access = box(ax, 6.9, 6.4, 2.8, 2.1, "Access control", ["tenant: own records", "admin: all records",
                                                           "else ACCESS DENIED"])
    workload = box(ax, 6.9, 3.4, 2.8, 2.4, "Workload", ["random (seeded)", "CSV / JSON file", "typed by hand",
                                                       "CPU, RAM, sensitivity"])
    placement = box(ax, 10.7, 5.3, 3.3, 3.5, "Placement engine",
                    ["1. Latency-First (baseline)", "2. Cloud-Only (baseline)", "3. Capacity-Aware (rule-based)",
                     "    filter → score → offload/reject", "4. TOPSIS (multi-criteria)",
                     "every decision has a reason"], fill=ACCENT_FILL, edge=TIER["edge"], bold_edge=True)
    qos = box(ax, 10.7, 2.6, 3.3, 1.9, "QoS model", ["latency = network +", "work / speed × congestion",
                                                     "deadlines 25 / 100 / 400 ms"])
    vms = box(ax, 15.0, 5.5, 2.4, 2.9, "VM manager", ["shared VMs,", "one tenant each;", "task joins or",
                                                      "creates a VM;", "create, stop"])
    edge = box(ax, 18.0, 7.6, 2.5, 1.4, "Edge", ["4 CPU · 8 GB · 5 ms"], edge=TIER["edge"],
               title_color=TIER["edge"], bold_edge=True)
    fog = box(ax, 18.0, 5.8, 2.5, 1.4, "Fog", ["16 CPU · 32 GB · 20 ms"], edge=TIER["fog"],
              title_color=TIER["fog"], bold_edge=True)
    cloud = box(ax, 18.0, 4.0, 2.5, 1.4, "Cloud", ["128 CPU · 512 GB · 80 ms"], edge=TIER["cloud"],
                title_color=TIER["cloud"], bold_edge=True)
    results = box(ax, 15.0, 0.3, 5.5, 2.5, "Results", ["decisions.csv · summary.json · vms.csv · nodes.csv",
                                                       "charts: outcomes, tiers, latency, node CPU",
                                                       "experiments.md (E1–E4) + evidence",
                                                       "settings_used.json (repeatable runs)"])
    config = box(ax, 0.2, 0.9, 6.0, 2.3, "Settings (all editable)", ["config/*.json → --config file → --set flags",
                                                                     "→ menu / app edits (later layers win):",
                                                                     "nodes, deadlines, weights, VM sizes, seeds"])

    arrow(ax, right(users, 0.6), left(cli))
    arrow(ax, right(users, -0.6), left(web))
    arrow(ax, right(cli), left(access, 0.4))
    arrow(ax, right(web), left(access, -0.6))
    arrow(ax, (8.3, 8.5), (8.3, 8.95))
    arrow(ax, (8.3, 6.4), (8.3, 5.8))
    ax.text(8.4, 5.95, "add / load tasks", fontsize=8, color=INK_2, style="italic", va="bottom")
    arrow(ax, right(access), left(placement, 0.6), "run", label_offset=(0, 0.06))
    arrow(ax, right(workload), left(placement, -1.0), "tasks", label_offset=(-0.1, 0.12))
    arrow(ax, (12.1, 5.3), (12.1, 4.5))
    arrow(ax, (12.6, 4.5), (12.6, 5.3))
    ax.text(12.75, 4.75, "estimate latency", fontsize=8, color=INK_2, style="italic", va="center")
    arrow(ax, right(placement, 0.3), left(vms, 0.3), "node", label_offset=(0, 0.08))
    arrow(ax, right(vms, 0.9), left(edge), rad=-0.1)
    arrow(ax, right(vms, 0.0), left(fog))
    arrow(ax, right(vms, -0.9), left(cloud), rad=0.1)
    arrow(ax, (14.0, 6.0), (15.6, 2.8), "decisions", label_offset=(-0.55, -0.1), rad=0.15)
    arrow(ax, (19.25, 4.0), (19.25, 2.8), "usage", label_offset=(0.45, -0.1))
    arrow(ax, right(config, 0.4), left(qos, -0.3), "settings", label_offset=(0, 0.06))

    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=160, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


if __name__ == "__main__":
    print(draw(Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT))
