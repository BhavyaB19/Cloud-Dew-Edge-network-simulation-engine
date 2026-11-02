"""Charts (F9): matplotlib figures for runs, policy comparisons and before/after changes.

Each ``*_chart`` function returns a matplotlib ``Figure`` (the Streamlit app
shows it directly); :func:`save_run_charts`, :func:`save_comparison_charts` and
:func:`save_before_after_chart` write PNGs for the report and slides.

Colours follow one rule each (validated for colour-blind separation):

- outcomes use status colours with labels: on time green, late amber, rejected red;
- tiers use fixed categorical colours: edge blue, fog orange, cloud aqua, rejected grey;
- before/after uses grey for "before" and blue for "after".

Every bar carries its value as a label, so no chart relies on colour alone.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # draw to files, no window; must happen before pyplot is imported

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from edgefogsim.simulator import LATE, ON_TIME, REJECTED, RunResult  # noqa: E402

SURFACE = "#fcfcfb"
"""Chart background."""

INK, INK_SECONDARY, GRID = "#0b0b0b", "#52514e", "#e4e3df"
"""Text, secondary text and gridline colours."""

OUTCOME_COLORS = {ON_TIME: "#0ca30c", LATE: "#fab219", REJECTED: "#d03b3b"}
"""Status colours for task outcomes."""

TIER_COLORS = {"edge": "#2a78d6", "fog": "#eb6834", "cloud": "#1baf7a", "rejected": "#b5b4ad"}
"""Fixed categorical colour per tier (and grey for rejected tasks)."""

BEFORE_COLOR, AFTER_COLOR = "#b5b4ad", "#2a78d6"
"""Colours for the before and after series."""


def outcomes_chart(results: list[RunResult]) -> Figure:
    """Stacked bars: how many tasks each policy finished on time, late or rejected.

    Args:
        results: One run per policy, on the same workload.

    Returns:
        The figure.
    """
    labels = [r.label for r in results]
    series = {outcome: [sum(d.outcome == outcome for d in r.decisions) for r in results]
              for outcome in (ON_TIME, LATE, REJECTED)}
    fig, ax = _figure(height=0.6 * len(results) + 1.6)
    _stacked_bars(ax, labels, series, OUTCOME_COLORS)
    _finish(ax, "Task outcomes by policy", "Tasks")
    return fig


def tiers_chart(results: list[RunResult]) -> Figure:
    """Stacked bars: where each policy placed the tasks (edge, fog, cloud) and how many it rejected.

    Args:
        results: One run per policy, on the same workload.

    Returns:
        The figure.
    """
    labels = [r.label for r in results]
    series = {tier: [sum((d.tier or "rejected") == tier for d in r.decisions) for r in results]
              for tier in ("edge", "fog", "cloud", "rejected")}
    fig, ax = _figure(height=0.6 * len(results) + 1.6)
    _stacked_bars(ax, labels, series, TIER_COLORS)
    _finish(ax, "Where each policy placed the tasks", "Tasks")
    return fig


def node_usage_chart(result: RunResult) -> Figure:
    """Grouped bars per node: share of CPU reserved by VMs and share used by tasks.

    Args:
        result: The run whose final node usage to show.

    Returns:
        The figure.
    """
    names = [n.id for n in result.nodes]
    series = {"Reserved by VMs": [100 * n.cpu_util for n in result.nodes],
              "Used by tasks (load)": [100 * n.load_util for n in result.nodes]}
    fig, ax = _figure(height=3.2)
    _grouped_bars(ax, names, series, [TIER_COLORS["edge"], TIER_COLORS["fog"]], suffix="%")
    ax.set_ylim(0, 115)
    _finish(ax, f"Node CPU after {result.label}", "% of CPU", horizontal=False)
    return fig


def latency_chart(results: list[RunResult]) -> Figure:
    """Box plot per policy of each placed task's latency as a share of its deadline.

    Deadlines differ by sensitivity (25 / 100 / 400 ms by default), so latency
    is shown relative to each task's own deadline; the dashed line at 100%
    is "exactly on the deadline". The scale is logarithmic so very late tasks fit.

    Args:
        results: One run per policy, on the same workload.

    Returns:
        The figure.
    """
    data = [[100 * d.latency_ms / d.deadline_ms for d in r.decisions if d.placed] or [float("nan")]
            for r in results]
    fig, ax = _figure(height=3.4)
    box = ax.boxplot(data, tick_labels=[r.label for r in results], patch_artist=True, widths=0.5,
                     medianprops={"color": INK, "linewidth": 2}, flierprops={"markersize": 4,
                     "markerfacecolor": INK_SECONDARY, "markeredgecolor": "none"})
    for patch in box["boxes"]:
        patch.set(facecolor="#cde2fb", edgecolor=TIER_COLORS["edge"], linewidth=1.2)
    ax.axhline(100, color=OUTCOME_COLORS[REJECTED], linestyle="--", linewidth=1.5)
    ax.text(len(results) + 0.45, 100, "deadline", color=INK_SECONDARY, va="bottom", ha="right", fontsize=9)
    ax.set_yscale("log")
    ax.yaxis.set_major_locator(matplotlib.ticker.FixedLocator([5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000]))
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}%"))
    ax.yaxis.set_minor_locator(matplotlib.ticker.NullLocator())
    _finish(ax, "Latency as a share of each task's deadline (placed tasks)", "% of deadline", horizontal=False)
    return fig


def before_after_chart(before: RunResult, after: RunResult, change: str) -> Figure:
    """Two panels comparing a run before and after a node change: task outcomes and node load.

    Args:
        before: The run with the original nodes.
        after: The same workload and policy with the changed nodes.
        change: What changed, for the title, e.g. ``"edge-1 cpu_cores 4 → 8"``.

    Returns:
        The figure.
    """
    fig, (left, right) = plt.subplots(1, 2, figsize=(10, 3.6), facecolor=SURFACE)
    for ax in (left, right):
        ax.set_facecolor(SURFACE)
    outcomes = [ON_TIME, LATE, REJECTED]
    counts = {name: [sum(d.outcome == o for d in run.decisions) for o in outcomes]
              for name, run in (("Before", before), ("After", after))}
    _grouped_bars(left, ["On time", "Late", "Rejected"], counts, [BEFORE_COLOR, AFTER_COLOR])
    _finish(left, "Task outcomes", "Tasks", horizontal=False)
    nodes = [n.id for n in after.nodes]
    load = {name: [100 * n.load_util for n in run.nodes] for name, run in (("Before", before), ("After", after))}
    _grouped_bars(right, nodes, load, [BEFORE_COLOR, AFTER_COLOR], suffix="%")
    right.set_ylim(0, 115)
    _finish(right, "CPU load per node", "% of CPU", horizontal=False)
    fig.suptitle(f"Before / after: {change} ({after.label})", color=INK, fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    return fig


def save_figure(fig: Figure, path: Path | str) -> Path:
    """Write a figure as a PNG at 150 dpi and free its memory.

    Args:
        fig: The figure.
        path: Destination; parent folders are created if needed.

    Returns:
        The path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    return path


def save_run_charts(result: RunResult, folder: Path | str) -> dict[str, Path]:
    """Save the charts for one run: node usage and latency.

    Returns:
        Chart name -> PNG path, for ``node_usage`` and ``latency``.
    """
    folder = Path(folder)
    return {
        "node_usage": save_figure(node_usage_chart(result), folder / "node_usage.png"),
        "latency": save_figure(latency_chart([result]), folder / "latency.png"),
    }


def save_comparison_charts(results: list[RunResult], folder: Path | str) -> dict[str, Path]:
    """Save the charts for a policy comparison: outcomes, tiers and latency.

    Returns:
        Chart name -> PNG path, for ``outcomes``, ``tiers`` and ``latency``.
    """
    folder = Path(folder)
    return {
        "outcomes": save_figure(outcomes_chart(results), folder / "outcomes.png"),
        "tiers": save_figure(tiers_chart(results), folder / "tiers.png"),
        "latency": save_figure(latency_chart(results), folder / "latency.png"),
    }


def save_before_after_chart(before: RunResult, after: RunResult, change: str, folder: Path | str) -> Path:
    """Save the before/after chart as ``before_after.png`` in ``folder``."""
    return save_figure(before_after_chart(before, after, change), Path(folder) / "before_after.png")


def _figure(height: float) -> tuple[Figure, plt.Axes]:
    """A single-panel figure on the chart surface."""
    fig, ax = plt.subplots(figsize=(8, height), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    return fig, ax


def _stacked_bars(ax: plt.Axes, labels: list[str], series: dict[str, list[int]], colors: dict[str, str]) -> None:
    """Horizontal stacked bars, one row per label, with a count inside every segment wide enough to hold it."""
    rows = list(range(len(labels)))[::-1]
    left = [0] * len(labels)
    total = max((sum(v) for v in zip(*series.values())), default=1) or 1
    for name, values in series.items():
        bars = ax.barh(rows, values, left=left, color=colors[name], edgecolor=SURFACE, linewidth=2,
                       height=0.6, label=name.capitalize() if name.islower() else name)
        for bar, value in zip(bars, values):
            if value and value / total >= 0.04:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2, str(value),
                        ha="center", va="center", fontsize=9, color="white" if name != "late" else INK)
        left = [a + b for a, b in zip(left, values)]
    ax.set_yticks(rows, labels)
    ax.legend(ncols=len(series), loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=9)


def _grouped_bars(ax: plt.Axes, names: list[str], series: dict[str, list[float]], colors: list[str],
                  suffix: str = "") -> None:
    """Vertical grouped bars, one group per name and one bar per series, each labelled with its value."""
    width = 0.8 / len(series)
    for i, ((label, values), color) in enumerate(zip(series.items(), colors)):
        xs = [x + (i - (len(series) - 1) / 2) * width for x in range(len(names))]
        bars = ax.bar(xs, values, width=width, color=color, edgecolor=SURFACE, linewidth=2, label=label)
        for bar, value in zip(bars, values):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{value:.0f}{suffix}",
                    ha="center", va="bottom", fontsize=8, color=INK_SECONDARY)
    ax.set_xticks(range(len(names)), names)
    ax.legend(frameon=False, fontsize=9, loc="upper right")


def _finish(ax: plt.Axes, title: str, value_label: str, horizontal: bool = True) -> None:
    """Apply the shared look: left-aligned title, recessive grid and axes, no box."""
    ax.set_title(title, loc="left", color=INK, fontsize=11, pad=24 if horizontal else 10)
    (ax.set_xlabel if horizontal else ax.set_ylabel)(value_label, color=INK_SECONDARY, fontsize=9)
    ax.grid(axis="x" if horizontal else "y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left" if horizontal else "top"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom" if horizontal else "left"].set_color(GRID)
    ax.tick_params(colors=INK_SECONDARY, labelsize=9, length=0)
    ax.figure.tight_layout()
