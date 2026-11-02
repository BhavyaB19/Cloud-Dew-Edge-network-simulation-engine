"""Write the presentation: ``python tools/make_slides.py`` → ``docs/report/EdgeFogSim_Slides.pptx``.

Seven 16:9 slides (title, system, algorithm, three results slides, conclusion)
with speaker notes. Numbers come from a fresh experiment run in
``docs/evidence/`` and the E1 chart is a native PowerPoint chart, so it can be
restyled in PowerPoint. Re-run this script after changing code or settings.
"""

import sys
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import ROOT, build_experiments  # noqa: E402
from team import TEAM  # noqa: E402

from edgefogsim.config import load_settings  # noqa: E402
from edgefogsim.experiments import ExperimentRun  # noqa: E402
from edgefogsim.simulator import run_workload  # noqa: E402
from edgefogsim.workload import load_tasks  # noqa: E402

OUTPUT = ROOT / "docs" / "report" / "EdgeFogSim_Slides.pptx"

NAVY, INK, MUTED, WHITE, CARD = "14213D", "1F2937", "5B6472", "FFFFFF", "F3F6FA"
TIER = {"edge": "2A78D6", "fog": "EB6834", "cloud": "1BAF7A"}
GOOD, WARN, BAD = "0CA30C", "FAB219", "D03B3B"
HEAD, BODY = "Cambria", "Calibri"
W, H = Inches(13.333), Inches(7.5)


def main() -> int:
    """Rebuild the evidence and write the slides."""
    print(write_slides(build_experiments()))
    return 0


def write_slides(run: ExperimentRun, path: Path = OUTPUT) -> Path:
    """Write the deck for an experiment run.

    Args:
        run: The experiments whose numbers go on the results slides.
        path: Destination ``.pptx``.

    Returns:
        The path written.
    """
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    e1, e2, e3, e4 = run.experiments
    title_slide(prs)
    system_slide(prs)
    algorithm_slide(prs)
    policy_slide(prs, e1)
    stress_slide(prs, e2, e3)
    change_slide(prs, e4)
    conclusion_slide(prs, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)
    return path


def title_slide(prs) -> None:
    """Slide 1: name, one-line pitch, team, and the three-tier motif."""
    s = _slide(prs, NAVY)
    _tier_dots(s, Inches(0.8), Inches(1.4), Inches(0.42))
    _text(s, "EdgeFogSim", Inches(0.8), Inches(2.2), Inches(11), Inches(1.3), 60, WHITE, font=HEAD, bold=True)
    _text(s, "Where should a task run: Edge, Fog or Cloud? A rule-based placement simulator with VMs, "
             "tenant security and QoS results.", Inches(0.8), Inches(3.6), Inches(10.5), Inches(1.2), 22, "CADCFC")
    _text(s, "ARM 305 – Cloud, Dev, Edge and Fog Computing · Mini Project", Inches(0.8), Inches(5.5),
          Inches(10), Inches(0.5), 16, "CADCFC")
    _text(s, "   ·   ".join(f"{name} {number}" for name, number in TEAM), Inches(0.8), Inches(6.0),
          Inches(11.8), Inches(0.5), 15, WHITE)
    _notes(s, "Introduce the problem: urgent jobs need nearby, small edge nodes; heavy jobs can wait for the "
              "big, distant cloud. EdgeFogSim simulates choosing where each task runs and measures the result.")


def system_slide(prs) -> None:
    """Slide 2: the architecture diagram."""
    s = _slide(prs, WHITE)
    _title(s, "Every task passes access control, a policy and a shared VM")
    picture = s.shapes.add_picture(str(ROOT / "docs" / "architecture.png"), 0, Inches(1.45), height=Inches(5.75))
    picture.left = int((W - picture.width) / 2)
    _notes(s, "Walk left to right: tenants log in through the CLI menu or the Streamlit app; access control "
              "refuses other tenants' records; the placement engine picks a node using the QoS model; the VM "
              "manager runs the task inside one of that tenant's VMs; results are exported as CSV, JSON and charts.")


def algorithm_slide(prs) -> None:
    """Slide 3: Capacity-Aware rules, the latency model and a worked example."""
    settings = load_settings()
    policy, qos = settings.simulation["policy"], settings.simulation["qos"]
    w = policy["capacity_weights"]
    s = _slide(prs, WHITE)
    _title(s, "Capacity-Aware: filter, score, then offload or reject")
    steps = [
        ("Prefer tiers by urgency", "high → Edge, medium → Fog, low → Cloud"),
        ("Filter out nodes", f"no room for the task's VM, CPU load over {policy['headroom']:.0%}, or the deadline "
                             "would be missed"),
        ("Score the rest", f"{w['tier']:g} × tier preference + {w['slack']:g} × time to spare + "
                           f"{w['free']:g} × free CPU"),
        ("Place or reject", "best score wins (offload if not first tier); if none fits, reject with the reason"),
    ]
    y = Inches(1.55)
    for i, (head, body) in enumerate(steps, start=1):
        _circle_number(s, i, Inches(0.8), y + Inches(0.05))
        _text(s, head, Inches(1.55), y, Inches(5.4), Inches(0.45), 18, INK, bold=True)
        _text(s, body, Inches(1.55), y + Inches(0.45), Inches(5.4), Inches(0.75), 14, MUTED)
        y += Inches(1.3)
    _card(s, Inches(7.4), Inches(1.55), Inches(5.2), Inches(1.75))
    _text(s, "Latency model", Inches(7.65), Inches(1.65), Inches(4.8), Inches(0.4), 16, INK, bold=True)
    _text(s, "network + (work ÷ speed) × congestion\ncongestion = 1 ÷ (1 − CPU load)", Inches(7.65), Inches(2.1),
          Inches(4.8), Inches(0.8), 15, INK)
    deadlines = qos["deadlines_ms"]
    _text(s, f"Deadlines: high {deadlines['high']:g} ms · medium {deadlines['medium']:g} ms · low "
             f"{deadlines['low']:g} ms", Inches(7.65), Inches(2.85), Inches(4.8), Inches(0.4), 12, MUTED)
    worked = run_workload(settings, load_tasks(ROOT / "examples" / "tasks_sample.csv", settings)[:4], "capacity")
    rows = [["Task", "Sensitivity", "Result"]] + [
        [d.task.id, d.task.sensitivity,
         ("rejected" if not d.placed else f"{d.node_id}{' (offload)' if d.offloaded else ''}, {d.latency_ms:.0f} ms")]
        for d in worked.decisions]
    _table(s, rows, Inches(7.4), Inches(3.6), Inches(5.2), [Inches(0.9), Inches(1.5), Inches(2.8)])
    _text(s, "Sample tasks T01–T04 on empty nodes.", Inches(7.4), Inches(6.2), Inches(5.2), Inches(0.4), 12, MUTED)
    _notes(s, "Capacity-Aware is the rule-based algorithm the brief asks for. Explain the four steps, then the "
              "worked example: T01 fits on Edge; T02 is offloaded to Fog because Edge would be full; T03 goes "
              "to Cloud; T04 is too big for Edge and Fog and Cloud is too far for a high-urgency deadline.")


def policy_slide(prs, e1) -> None:
    """Slide 4: E1 policy comparison as a native stacked bar chart with callouts."""
    s = _slide(prs, WHITE)
    rows = {r[0]: r for r in e1.tables[0][2]}
    total = sum(rows["Latency-First"][1:4])
    _title(s, f"Smart policies run 0 late; baselines run {rows['Latency-First'][2]} and "
              f"{rows['Cloud-Only'][2]} of {total} late")
    data = CategoryChartData()
    labels = list(rows)[::-1]
    data.categories = labels
    for name, col, color in (("On time", 1, GOOD), ("Late", 2, WARN), ("Rejected", 3, BAD)):
        data.add_series(name, [rows[label][col] or None for label in labels])  # None: no "0" label
    frame = s.shapes.add_chart(XL_CHART_TYPE.BAR_STACKED, Inches(0.6), Inches(1.5), Inches(8.0), Inches(5.3), data)
    chart = frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size, chart.legend.font.name = Pt(13), BODY
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.position = XL_LABEL_POSITION.CENTER
    plot.data_labels.font.size, plot.data_labels.font.name = Pt(13), BODY
    plot.data_labels.font.color.rgb = RGBColor.from_string(WHITE)
    for series, color in zip(plot.series, (GOOD, WARN, BAD)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = RGBColor.from_string(color)
    chart.category_axis.tick_labels.font.size = chart.value_axis.tick_labels.font.size = Pt(13)
    chart.value_axis.has_major_gridlines = False
    chart.value_axis.visible = False
    workload = e1.setup[0].replace("Workload: ", "")
    _stat(s, str(rows["Capacity-Aware"][2]), "late with Capacity-Aware", Inches(9.0), Inches(1.6), GOOD)
    _stat(s, str(rows["Latency-First"][2]), "late with Latency-First", Inches(9.0), Inches(3.3), BAD)
    _text(s, workload, Inches(9.0), Inches(5.2), Inches(3.8), Inches(1.0), 12, MUTED)
    _notes(s, f"E1: {workload} Each policy starts from empty nodes. Capacity-Aware and TOPSIS check the deadline "
              "before placing, so they reject what they cannot finish in time instead of running it late.")


def stress_slide(prs, e2, e3) -> None:
    """Slide 5: E2 overload and E3 unauthorised access side by side."""
    s = _slide(prs, WHITE)
    _title(s, "Overload is offloaded or rejected; other tenants are refused")
    rows = {r[0]: r for r in e2.tables[0][2]}
    cap, lf = rows["Capacity-Aware"], rows["Latency-First"]
    _card(s, Inches(0.6), Inches(1.5), Inches(5.95), Inches(5.3))
    _text(s, "E2 · Overload", Inches(0.9), Inches(1.65), Inches(5.4), Inches(0.5), 20, INK, bold=True, font=HEAD)
    _text(s, " ".join(e2.setup[:2]), Inches(0.9), Inches(2.15), Inches(5.4), Inches(0.8), 13, MUTED)
    for i, (value, label, color) in enumerate(((cap[4], "offloaded to Fog", TIER["fog"]),
                                               (cap[3], "rejected, with a reason", BAD),
                                               (cap[2], "late", GOOD))):
        _stat(s, str(value), label, Inches(0.9) + Inches(1.8) * i, Inches(3.1), color, width=Inches(1.7), size=40)
    _text(s, f"Latency-First, same burst: {lf[1]} on time, {lf[2]} late.", Inches(0.9), Inches(4.75), Inches(5.4),
          Inches(0.5), 14, INK)
    _text(s, "No node is ever allocated beyond its capacity.", Inches(0.9), Inches(5.3), Inches(5.4),
          Inches(0.5), 14, INK)
    _card(s, Inches(6.8), Inches(1.5), Inches(5.95), Inches(5.3))
    _text(s, "E3 · Unauthorised access", Inches(7.1), Inches(1.65), Inches(5.4), Inches(0.5), 20, INK, bold=True,
          font=HEAD)
    attempts = [q.split(" → ")[1].split(":")[0] for q in e3.quotes if " → " in q and "ACCESS DENIED" in q]
    actor = e3.quotes[0].split(" → ")[0]
    _text(s, f"Logged in as {actor}, trying another tenant's records:", Inches(7.1), Inches(2.15), Inches(5.4),
          Inches(0.5), 13, MUTED)
    y = Inches(2.75)
    for attempt in attempts:
        _pill(s, "DENIED", Inches(7.1), y)
        _text(s, attempt, Inches(8.4), y + Inches(0.06), Inches(4.1), Inches(0.4), 15, INK)
        y += Inches(0.6)
    held = sum(h for _, h in e3.checks)
    _text(s, f"Each refusal is one line in the audit log; the VM keeps running; the admin can read both records "
             f"({held}/{len(e3.checks)} checks).", Inches(7.1), Inches(4.75), Inches(5.4), Inches(1.0), 14, INK)
    _notes(s, "E2 shows the brief's overload scenario: tasks that don't fit are moved to another suitable node "
              "or rejected with a reason. E3 shows the unauthorised access attempt: ACCESS DENIED for every "
              "attempt, recorded in a CSV audit log.")


def change_slide(prs, e4) -> None:
    """Slide 6: E4 before/after node capacity and latency changes."""
    s = _slide(prs, WHITE)
    _title(s, "More Edge CPU helps; a slower Cloud pushes medium tasks out")
    for i, (title, headers, rows) in enumerate(e4.tables):
        x = Inches(0.6) + Inches(6.2) * i
        _card(s, x, Inches(1.5), Inches(5.95), Inches(5.3))
        _text(s, title.split(": ", 1)[1], x + Inches(0.3), Inches(1.65), Inches(5.4), Inches(0.5), 19, INK,
              bold=True, font=HEAD)
        keep = [r for r in rows if r[0] in ("on time", "rejected", "avg latency ms", "tasks on edge",
                                            "tasks on cloud")]
        _table(s, [headers] + keep, x + Inches(0.3), Inches(2.3), Inches(5.35),
               [Inches(2.35), Inches(1.5), Inches(1.5)], size=15)
        checks = e4.checks[3 * i:3 * i + 3]
        _text(s, "\n".join(f"{'✓' if held else '✗'} {statement}" for statement, held in checks),
              x + Inches(0.3), Inches(5.05), Inches(5.35), Inches(1.6), 13, INK)
    _notes(s, "E4 changes one node at a time and re-runs the same 20 tasks. Doubling Edge CPU lets Edge take more "
              "urgent tasks. Raising Cloud latency from 80 to 150 ms makes Cloud too slow for medium tasks' 100 ms "
              "deadline, while low-sensitivity tasks still finish on time.")


def conclusion_slide(prs, run: ExperimentRun) -> None:
    """Slide 7: takeaways, limitations and how to run it."""
    s = _slide(prs, NAVY)
    _tier_dots(s, Inches(0.8), Inches(0.75), Inches(0.3))
    _text(s, "What we learned", Inches(0.8), Inches(1.2), Inches(6), Inches(0.7), 32, WHITE, bold=True, font=HEAD)
    held = sum(h for e in run.experiments for _, h in e.checks)
    total = sum(len(e.checks) for e in run.experiments)
    _bullets(s, [f"All 4 experiments matched their expected outcome ({held}/{total} checks)",
                 "Checking the deadline before placing beats placing on the nearest node",
                 "Shared tenant VMs and one access rule keep tenants apart",
                 "Every number is a setting; runs are repeatable from settings_used.json"],
             Inches(0.8), Inches(2.05), Inches(6.0), Inches(3.6), WHITE)
    _text(s, "Limitations", Inches(7.3), Inches(1.2), Inches(5.3), Inches(0.7), 32, WHITE, bold=True, font=HEAD)
    _bullets(s, ["No task duration or arrival time; tasks run until their VM stops",
                 "Latency is a formula, not a measurement",
                 "Greedy, one task at a time; GA/PSO or Q-learning could do better",
                 "No VM migration; login is a tenant id by design"],
             Inches(7.3), Inches(2.05), Inches(5.4), Inches(3.6), "CADCFC")
    _text(s, "Try it:  python -m edgefogsim   ·   python -m edgefogsim web   ·   python run_experiments.py",
          Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.5), 15, WHITE)
    _notes(s, "Close with the takeaways, then the limitations; offer a live demo of the menu or the Streamlit app.")


def _slide(prs, background: str):
    """A blank slide with a solid background colour."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string(background)
    return slide


def _title(slide, text: str) -> None:
    """The slide title, same place and style on every content slide (kept to one line)."""
    _text(slide, text, Inches(0.6), Inches(0.45), Inches(12.1), Inches(0.8), 28, INK, bold=True, font=HEAD)


def _text(slide, text: str, x, y, w, h, size: float, color: str, bold: bool = False, font: str = BODY,
          align=PP_ALIGN.LEFT):
    """A word-wrapped text box; ``\\n`` starts a new paragraph."""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for i, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = align
        run = paragraph.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, font
        run.font.color.rgb = RGBColor.from_string(color)
    return box


def _bullets(slide, items: list[str], x, y, w, h, color: str) -> None:
    """A bulleted list (real bullets, 18 pt, spaced paragraphs)."""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for i, item in enumerate(items):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(10)
        properties = paragraph._p.get_or_add_pPr()
        properties.set("marL", str(Emu(Inches(0.3))))
        properties.set("indent", str(-Emu(Inches(0.3))))
        bullet = properties.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buChar",
                                        {"char": "•"})
        properties.append(bullet)
        run = paragraph.add_run()
        run.text = item
        run.font.size, run.font.name = Pt(18), BODY
        run.font.color.rgb = RGBColor.from_string(color)


def _card(slide, x, y, w, h) -> None:
    """A tinted rounded rectangle behind a block of content."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shape.adjustments[0] = 0.05
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(CARD)
    shape.line.fill.background()
    shape.shadow.inherit = False


def _stat(slide, value: str, label: str, x, y, color: str, width=Inches(3.8), size: float = 60) -> None:
    """A big number with a small label under it."""
    _text(slide, value, x, y, width, Inches(1.0), size, color, bold=True, font=HEAD)
    _text(slide, label, x, y + Inches(0.95 if size >= 60 else 0.75), width, Inches(0.6), 14, MUTED)


def _circle_number(slide, n: int, x, y) -> None:
    """A numbered navy circle (the step markers)."""
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, Inches(0.5), Inches(0.5))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(NAVY)
    shape.line.fill.background()
    shape.shadow.inherit = False
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = str(n)
    run.font.size, run.font.bold, run.font.name = Pt(16), True, BODY
    run.font.color.rgb = RGBColor.from_string(WHITE)


def _pill(slide, text: str, x, y) -> None:
    """A small red rounded label, e.g. DENIED."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, Inches(1.1), Inches(0.4))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(BAD)
    shape.line.fill.background()
    shape.shadow.inherit = False
    frame = shape.text_frame
    frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = text
    run.font.size, run.font.bold, run.font.name = Pt(12), True, BODY
    run.font.color.rgb = RGBColor.from_string(WHITE)


def _tier_dots(slide, x, y, size) -> None:
    """The deck's motif: three circles in the Edge, Fog and Cloud colours."""
    for i, tier in enumerate(("edge", "fog", "cloud")):
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, x + int(size * 1.35) * i, y, size, size)
        dot.fill.solid()
        dot.fill.fore_color.rgb = RGBColor.from_string(TIER[tier])
        dot.line.fill.background()
        dot.shadow.inherit = False


def _table(slide, rows: list[list], x, y, w, widths: list, size: float = 14) -> None:
    """A table with a navy header row."""
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(0.42) * len(rows))
    table = shape.table
    for j, width in enumerate(widths):
        table.columns[j].width = width
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(NAVY if i == 0 else WHITE)
            frame = cell.text_frame
            frame.paragraphs[0].text = ""
            run = frame.paragraphs[0].add_run()
            run.text = str(value)
            run.font.size, run.font.name, run.font.bold = Pt(size), BODY, i == 0
            run.font.color.rgb = RGBColor.from_string(WHITE if i == 0 else INK)


def _notes(slide, text: str) -> None:
    """Speaker notes for the slide."""
    slide.notes_slide.notes_text_frame.text = text


if __name__ == "__main__":
    sys.exit(main())
