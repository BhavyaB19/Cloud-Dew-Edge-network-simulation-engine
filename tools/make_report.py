"""Write the project report: ``python tools/make_report.py`` → ``docs/report/EdgeFogSim_Report.docx``.

Runs the four experiments into ``docs/evidence/`` first, then builds a Word document whose numbers, tables and
charts all come from that run and from the live settings. Edit the generated
file in Word for final polish; re-run this script if the code or settings change.
"""

import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import ROOT, build_experiments  # noqa: E402
from team import CONTRIBUTIONS, TEAM, team_line  # noqa: E402

from edgefogsim.config import load_settings  # noqa: E402
from edgefogsim.experiments import ExperimentRun  # noqa: E402
from edgefogsim.simulator import run_workload  # noqa: E402
from edgefogsim.workload import load_tasks  # noqa: E402

OUTPUT = ROOT / "docs" / "report" / "EdgeFogSim_Report.docx"
INK, MUTED, HEADER_FILL = RGBColor(0x0B, 0x0B, 0x0B), RGBColor(0x52, 0x51, 0x4E), "E8F1FC"


def main() -> int:
    """Rebuild the evidence and write the report."""
    print(write_report(build_experiments()))
    return 0


def write_report(run: ExperimentRun, path: Path = OUTPUT) -> Path:
    """Write the report for an experiment run.

    Args:
        run: The experiments whose numbers, tables and charts go into the report.
        path: Destination ``.docx``.

    Returns:
        The path written.
    """
    settings = load_settings()
    sim = settings.simulation
    doc = _new_document()
    e1, e2, e3, e4 = run.experiments

    _title(doc, "EdgeFogSim: Edge, Fog and Cloud Task Placement Simulator",
           "ARM 305 – Cloud, Dev, Edge and Fog Computing · Mini Project Report",
           f"Team: {team_line()}",
           "Repository: github.com/moksh-m9u/Cloud-Dew-Edge-network-simulation-engine")

    _heading(doc, "1. Objective")
    _para(doc, "Edge and fog computing move processing closer to where data is produced, so urgent jobs can be "
               "answered in milliseconds, while large jobs still go to the cloud. Deciding where each job should run "
               "is a trade-off: nearby nodes are fast to reach but small, the cloud is huge but far away.")
    _para(doc, "EdgeFogSim is a locally runnable Python simulator of that decision. It accepts computing tasks, "
               "places each on an Edge, Fog or Cloud node with a rule-based algorithm, simulates the resources it "
               "uses through virtual-machine records, keeps tenants' records apart, and reports placement decisions, "
               "latency, utilisation, success and failure. No real cloud, VMs or hypervisor are needed. Every "
               "number the simulator uses is a setting that can be changed without touching the code.")

    _heading(doc, "2. Architecture")
    _figure(doc, ROOT / "docs" / "architecture.png", "Figure 1. EdgeFogSim architecture.", width_cm=16.5)
    _bullets(doc, [
        ("Users and interfaces. ", "Tenants (hospital-a, hospital-b) and an admin log in by choosing a tenant id; "
         "no passwords exist. The same engine is driven from a command-line menu or a Streamlit web app."),
        ("Access control. ", "Every request passes one rule: a tenant may see and act on their own records, the "
         "admin on all. Anything else is refused with ACCESS DENIED and written to a CSV audit log."),
        ("Workload. ", "Tasks have CPU, memory, a latency sensitivity (high, medium, low) and an amount of work. "
         "They are generated with a fixed seed, loaded from CSV/JSON, or typed in."),
        ("Placement engine and QoS model. ", "A policy picks a node for each task using the latency model below; "
         "every decision records its reason."),
        ("VM manager and nodes. ", "Tasks run inside tenant-owned VMs on the chosen Edge, Fog or Cloud node. This "
         "is the only component that changes node usage."),
        ("Results. ", "Decisions, summaries, VMs and nodes are saved as CSV/JSON with PNG charts, plus the settings "
         "used so any run can be repeated."),
    ])

    _heading(doc, "3. Placement algorithm")
    nodes = settings.nodes
    _para(doc, "Default nodes: " + "; ".join(
        f"{n.tier.capitalize()} {n.cpu_cores:g} CPU, {n.memory_gb:g} GB, {n.base_latency_ms:g} ms away, "
        f"speed {n.speed_factor:g}" for n in nodes) + ". Each task's deadline depends on its sensitivity: " +
        ", ".join(f"{k} {v:g} ms" for k, v in sim["qos"]["deadlines_ms"].items()) + ".")
    _heading(doc, "Latency model", level=2)
    _para(doc, "latency = network latency + (work ÷ node speed) × congestion,   congestion = 1 ÷ (1 − CPU load after "
               f"placement), with load capped at {sim['qos']['congestion_cap']:.0%}.", italic=True)
    _para(doc, "Congestion is a queueing (M/M/1-style) approximation: 1 on an idle node, 2 at half load, 10 at 90% "
               "load. A task is successful if it is placed and its latency is within its deadline.")
    _heading(doc, "Capacity-Aware: the rule-based algorithm", level=2)
    weights = sim["policy"]["capacity_weights"]
    _numbered(doc, [
        "Order the tiers by the task's sensitivity: high → Edge, Fog, Cloud; medium → Fog, Edge, Cloud; "
        "low → Cloud, Fog, Edge.",
        "Capacity filter: the node must be able to host the task (in a VM of the task's tenant with room, or in a "
        f"new VM on unreserved capacity) and its CPU load must stay at or below {sim['policy']['headroom']:.0%}.",
        "Deadline filter: the estimated latency must be within the task's deadline.",
        f"Score each remaining node: {weights['tier']:g} × tier preference + {weights['slack']:g} × time to spare "
        f"before the deadline + {weights['free']:g} × CPU left free.",
        "Place the task on the highest score. If that node is not in the task's first-choice tier, record it as "
        "an offload, with the reason.",
        "If no node passes, retry once allowing nodes to be fully loaded (soft overload).",
        "If still none passes, reject the task and record which check failed on each node.",
    ])
    _para(doc, "Two baselines are compared with it: Latency-First (nearest node with room, ignoring deadlines) and "
               "Cloud-Only. A fourth policy, TOPSIS, ranks the feasible nodes by closeness to an ideal node on "
               "latency, free CPU and free memory, a multi-criteria method used in fog node selection research.")
    worked = run_workload(settings, load_tasks(ROOT / "examples" / "tasks_sample.csv", settings)[:4], "capacity")
    _table(doc, ["Task", "Needs", "Sensitivity", "Decision", "Latency", "Why"], [
        [d.task.id, f"{d.task.cpu_cores:g} CPU, {d.task.work_units:g} work", d.task.sensitivity,
         f"{d.node_id} (offload)" if d.offloaded else (d.node_id or "rejected"),
         "-" if d.latency_ms is None else f"{d.latency_ms:.1f} ms", _short_reason(d)]
        for d in worked.decisions], widths=[1.3, 2.6, 2.0, 2.6, 1.8, 6.7],
        caption="Table 1. Capacity-Aware on the first four sample tasks, starting from empty nodes.")

    _heading(doc, "4. Implementation")
    _table(doc, ["Module", "Role"], [
        ["config", "Layered, validated settings: defaults → config/*.json → --config file → flags → menu edits"],
        ["models", "Node, Task, Tenant and VM dataclasses"],
        ["workload", "Seeded generator, CSV/JSON task files, typed tasks, row-level validation"],
        ["qos / policies", "Latency model; Latency-First, Cloud-Only, Capacity-Aware and TOPSIS"],
        ["vm_manager / simulator", "Shared tenant VMs (join, create, stop); runs a workload, records decisions"],
        ["security", "Access rule, ACCESS DENIED, CSV audit log"],
        ["results / charts", "pandas tables, CSV/JSON export, matplotlib charts"],
        ["experiments", "E1–E4 with expected outcomes checked against actual numbers"],
        ["cli / web", "Command-line menu (rich) and Streamlit app; no simulation logic of their own"],
    ], widths=[4.2, 12.8], caption="Table 2. Python modules in the edgefogsim package.")
    sizes = sim["vm"]["sizes"]
    _para(doc, "Virtualisation. A VM is a slice of one node owned by one tenant. A placed task joins one of its "
               "tenant's VMs on the chosen node if it has room; otherwise a new VM is created, sized to the tier "
               "default (" + ", ".join(f"{t} {s['cpu_cores']:g} CPU / {s['memory_gb']:g} GB" for t, s in sizes.items())
               + ") or to the task. Nodes therefore track reserved capacity (held by VMs) and load (used by tasks); "
               "load drives latency. VMs can be created ahead of time and stopped, which frees their slice.")
    _para(doc, f"Technology. Python {sys.version_info.major}.{sys.version_info.minor}, pandas for result tables, "
               "matplotlib for charts, rich for the terminal menu and Streamlit for the web app; settings are JSON. "
               f"Quality is checked by {_test_count()} automated pytest tests mapped to the acceptance criteria in "
               "docs/SPEC.md, including tests that drive both interfaces and one that requires a docstring on "
               "every function.")

    _heading(doc, "5. Experiments and results")
    _para(doc, "All four experiments run with python run_experiments.py. Each states its expected outcome before "
               "running and checks it against the actual numbers; " +
               f"{sum(e.passed for e in run.experiments)} of 4 matched "
               f"({sum(h for e in run.experiments for _, h in e.checks)} of "
               f"{sum(len(e.checks) for e in run.experiments)} checks). Full evidence is in docs/evidence/experiments.")
    for exp, figures in ((e1, [0]), (e2, [0]), (e3, []), (e4, [0, 1])):
        _experiment(doc, run, exp, figures)

    _heading(doc, "6. Discussion")
    s1 = {row[0]: row for row in e1.tables[0][2]}
    _bullets(doc, [
        ("Deadline-aware placement pays off. ", f"Capacity-Aware ran {s1['Capacity-Aware'][2]} tasks late and "
         f"TOPSIS {s1['TOPSIS'][2]}, against {s1['Latency-First'][2]} for Latency-First and {s1['Cloud-Only'][2]} "
         "for Cloud-Only. They reject what cannot be finished in time instead of running it late."),
        ("Rejection is the price. ", "The smart policies refuse some urgent tasks when Edge is full and Fog is too "
         "slow. In a real deployment this is the signal to add Edge capacity, which E4a shows helps."),
        ("Utilisation is not the same as quality. ", "Latency-First keeps Edge and Fog fully loaded, but the "
         "congestion makes tasks late; a lower, steadier load gives better service."),
        ("Isolation holds. ", "Every cross-tenant attempt in E3 was refused and logged, while the admin could "
         "still read everything."),
    ])

    _heading(doc, "7. Limitations and future work")
    _bullets(doc, [
        ("Simulated time. ", "Tasks are placed one after another and keep running until their VM is stopped; there "
         "is no task duration, arrival time or network jitter."),
        ("Analytical latency. ", "Latency comes from a formula, not measurement; it captures distance, speed and "
         "congestion but not bandwidth or data size."),
        ("Greedy, per-task decisions. ", "Policies decide one task at a time. Batch optimisers such as genetic "
         "algorithms or PSO, and a learning policy (tabular Q-learning, planned as an optional extension), could "
         "find better global placements."),
        ("TOPSIS rank reversal. ", "Closeness scores can reorder when the set of feasible nodes changes."),
        ("No live migration or real authentication. ", "VMs are never moved, and login is choosing a tenant id, "
         "as the brief requires."),
    ])

    _heading(doc, "8. Team contributions")
    _table(doc, ["Member", "Enrollment number", "Contribution"],
           [[name, number, CONTRIBUTIONS[name]] for name, number in TEAM], widths=[3.6, 3.6, 9.8])

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(path)
    return path


def _experiment(doc, run: ExperimentRun, exp, figure_indexes: list[int]) -> None:
    """Write one experiment: setup, expected, actual table(s), outcome and selected charts."""
    _heading(doc, f"{exp.key}: {exp.title}", level=2)
    _labelled(doc, "Setup. ", " ".join(line if line.endswith(".") else line + "." for line in exp.setup))
    _labelled(doc, "Expected. ", exp.expected)
    for title, headers, rows in exp.tables:
        widths = {"timestamp": [4.0, 3.0, 3.2, 4.0, 2.4], "Metric": [6.0, 3.0, 3.0],
                  "Policy": [3.4, 1.8, 1.6, 1.9, 2.0, 1.9, 2.1, 2.3]}.get(headers[0])
        _table(doc, headers, rows, widths=widths, caption=title or None, small=True)
    for quote in exp.quotes[:2] if exp.key == "E2" else exp.quotes:
        _para(doc, quote, size=8.5, italic=True, color=MUTED)
    held = sum(h for _, h in exp.checks)
    _labelled(doc, "Actual. ", f"{held} of {len(exp.checks)} checks held: " +
              "; ".join(statement for statement, _ in exp.checks) + ".")
    for i in figure_indexes:
        rel, caption = exp.figures[i]
        _figure(doc, run.folder / rel, f"{exp.key}: {caption}.", width_cm=14 if "before_after" in rel else 12.5)


def _short_reason(decision) -> str:
    """The first part of a decision's reason, short enough for a table cell."""
    text = decision.reason.split("; scores")[0].split("; runs in")[0]
    return text if len(text) <= 180 else text[:177] + "…"


def _test_count() -> int:
    """How many pytest tests the project has (0 if pytest can't be run)."""
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"],
                             cwd=ROOT, capture_output=True, text=True, timeout=120).stdout
        # pyproject adds -q, so with another -q pytest prints "tests/test_x.py: N" per file.
        return sum(int(line.rsplit(":", 1)[1]) for line in out.splitlines()
                   if line.startswith("tests/") and line.rsplit(":", 1)[1].strip().isdigit())
    except Exception:
        return 0


def _new_document() -> Document:
    """An A4 document with 2 cm margins, Calibri 10.5 pt body and page numbers in the footer."""
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21), Cm(29.7)
    for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
        setattr(section, side, Cm(2))
    style = doc.styles["Normal"]
    style.font.name, style.font.size, style.font.color.rgb = "Calibri", Pt(10.5), INK
    style.paragraph_format.space_after = Pt(5)
    style.paragraph_format.line_spacing = 1.1
    for name, size in (("Heading 1", 14), ("Heading 2", 11.5)):
        heading = doc.styles[name]
        heading.font.name, heading.font.size, heading.font.color.rgb = "Calibri", Pt(size), INK
        heading.paragraph_format.space_before, heading.paragraph_format.space_after = Pt(12 if size > 12 else 8), Pt(4)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _page_number(footer)
    return doc


def _title(doc, title: str, subtitle: str, *details: str) -> None:
    """Title block at the top of page 1: title, subtitle, then smaller detail lines (team, repository)."""
    p = doc.add_paragraph()
    run = p.add_run(title)
    run.bold, run.font.size = True, Pt(18)
    p.paragraph_format.space_after = Pt(2)
    _para(doc, subtitle, size=11, color=MUTED)
    for line in details:
        _para(doc, line, size=9.5, color=MUTED).paragraph_format.space_after = Pt(1)


def _heading(doc, text: str, level: int = 1) -> None:
    """A Word heading (shows in the navigation pane and a table of contents)."""
    doc.add_heading(text, level=level)


def _para(doc, text: str, size: float | None = None, italic: bool = False, color=None):
    """A body paragraph."""
    p = doc.add_paragraph()
    run = p.add_run(text)
    run.italic = italic
    if size:
        run.font.size = Pt(size)
    if color is not None:
        run.font.color.rgb = color
    return p


def _labelled(doc, label: str, text: str) -> None:
    """A paragraph starting with a bold label."""
    p = doc.add_paragraph()
    p.add_run(label).bold = True
    p.add_run(text)


def _bullets(doc, items: list[tuple[str, str]]) -> None:
    """Bulleted list; each item has a bold lead-in and plain text."""
    for lead, text in items:
        p = doc.add_paragraph(style="List Bullet")
        p.add_run(lead).bold = True
        p.add_run(text)
        p.paragraph_format.space_after = Pt(3)


def _numbered(doc, items: list[str]) -> None:
    """Numbered list."""
    for text in items:
        p = doc.add_paragraph(text, style="List Number")
        p.paragraph_format.space_after = Pt(2)


def _table(doc, headers: list[str], rows: list[list], widths: list[float] | None = None,
           caption: str | None = None, small: bool = False) -> None:
    """A table with a shaded header row; widths in cm; optional caption below."""
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    size = Pt(8.5 if small else 9)
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(text))
        run.bold, run.font.size = True, size
        _shade(cell, HEADER_FILL)
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = ""
            cell.paragraphs[0].add_run(str(value)).font.size = size
    if widths:
        # Word reads cell widths, LibreOffice the column grid: set both, and stop auto-fit undoing them.
        table.autofit = False
        for column, width in zip(table.columns, widths):
            column.width = Cm(width)
        for row in table.rows:
            for cell, width in zip(row.cells, widths):
                cell.width = Cm(width)
    for i, row in enumerate(table.rows):
        row_properties = row._tr.get_or_add_trPr()
        row_properties.append(OxmlElement("w:cantSplit"))
        for cell in row.cells:
            paragraph_format = cell.paragraphs[0].paragraph_format
            paragraph_format.space_after = Pt(0)
            paragraph_format.keep_with_next = i < len(table.rows) - 1  # keep the table on one page
    if caption:
        _para(doc, caption, size=8.5, italic=True, color=MUTED)
    else:
        doc.add_paragraph().paragraph_format.space_after = Pt(0)


def _figure(doc, path: Path, caption: str, width_cm: float) -> None:
    """A centred image with an italic caption under it."""
    doc.add_picture(str(path), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = _para(doc, caption, size=8.5, italic=True, color=MUTED)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER


def _shade(cell, fill: str) -> None:
    """Give a table cell a background colour."""
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shading)


def _page_number(paragraph) -> None:
    """Insert a PAGE field (the page number) into a paragraph."""
    run = paragraph.add_run()
    for tag, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if tag:
            element = OxmlElement("w:fldChar")
            element.set(qn("w:fldCharType"), tag)
        else:
            element = OxmlElement("w:instrText")
            element.set(qn("xml:space"), "preserve")
            element.text = text
        run._r.append(element)
    run.font.size = Pt(9)


if __name__ == "__main__":
    sys.exit(main())
