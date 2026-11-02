# EdgeFogSim

A locally runnable Python simulator that places computing tasks on Edge, Fog or Cloud nodes, simulates VMs and tenant isolation, and reports QoS results. ARM 305 Cloud, Dev, Edge and Fog Computing mini project.

<p align="center">
  <img src="docs/screenshots/web-comparison.png" alt="Streamlit policy comparison: the same 12 tasks through four policies; Capacity-Aware and TOPSIS run none late, the baselines run 5 to 7 late" width="820">
  <br>
  <em>The same 12 tasks through all four placement policies. The smart policies reject what they can't finish in time instead of running it late.</em>
</p>

> **Status:** Phase 5 (placement, shared VMs, tenant security, results, charts and the four required experiments). The report, slides and submission ZIP arrive in Phase 6. See [docs/SPEC.md](docs/SPEC.md) for the full plan.

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

There are two ways to use the simulator. Both call the same code, so the same settings and seed give the same results.

**Command-line menu**

```bash
python -m edgefogsim
```

**Streamlit app in your browser**

```bash
python -m edgefogsim web
```

It opens at http://localhost:8501 (change it with `--port 8600`). Stop it with Ctrl+C.

### Screenshots

| Command-line menu | Streamlit app |
|---|---|
| <img src="docs/screenshots/cli-menu.png" alt="Command-line menu showing the node table and the numbered menu sections" width="440"> | <img src="docs/screenshots/web-workload.png" alt="Streamlit Workload page with 50 generated tasks, showing only hospital-a's 24" width="440"> |
| Node table with reserved and load figures, and the menu grouped into sections. | Workload page: 50 generated tasks; a tenant sees only their own. |
| <img src="docs/screenshots/cli-placement.png" alt="Command-line placement decisions for Latency-First with a reason for every task" width="440"> | <img src="docs/screenshots/web-placement.png" alt="Streamlit Placement page with metrics, decisions table and nodes after the run" width="440"> |
| Placement decisions: node, VM, latency against deadline, and why. | Placement page: headline metrics, decisions and node usage after the run. |

In either one, log in as a tenant, then:

1. view nodes,
2. build a workload (generate, upload a file or add tasks by hand),
3. run a placement policy and read why each task went where it did,
4. compare all policies on the same workload,
5. view, create and stop VMs (tenant-owned slices of a node that several of that tenant's tasks share), and place a single task on the room that frees up,
6. look up a task or VM by id: another tenant's is refused (ACCESS DENIED) and written to the audit log,
7. export results (CSV, JSON and PNG charts), and as admin change a node and compare before/after,
8. view, change or save settings.

Tenants see only their own tasks, decisions and VMs; `admin` sees everything. Refused attempts are logged to `results/audit.log` (CSV).

**Without the menu** (prints the decisions or the comparison and exits):

```bash
python -m edgefogsim run --policy capacity --tasks examples/tasks_sample.csv
python -m edgefogsim run --policy all --tasks 20 --seed 42
```

Policies: `latency` (Latency-First), `cloud` (Cloud-Only), `capacity` (Capacity-Aware, the main rule-based algorithm) and `topsis` (TOPSIS ranking). Their rules are in [docs/SPEC.md §3](docs/SPEC.md).

Useful options (they work with `menu`, `web` and `run`):

| Option | Example | Effect |
|--------|---------|--------|
| `--tasks N` | `--tasks 20` | number of random tasks |
| `--tasks FILE` | `--tasks examples/tasks_sample.csv` | start with your own task list |
| `--seed N` | `--seed 7` | random seed for generated tasks |
| `--nodes FILE` | `--nodes my_nodes.json` | use your own nodes |
| `--config FILE` | `--config my_settings.json` | override any settings |
| `--deadline LEVEL=MS` | `--deadline high=40` | change a deadline |
| `--headroom X` | `--headroom 0.9` | Capacity-Aware utilisation limit |
| `--set KEY=VALUE` | `--set generator.cpu_range=[1,4]` | change any setting |

`python -m edgefogsim menu --help` lists them all.

## Results and charts

Menu option 14 (or the app's **Results** page) saves the last run and the last policy comparison to a new folder under `results/`:

| File | What it holds |
|------|---------------|
| `decisions.csv` | One row per task: node, VM, latency, deadline, outcome, reason |
| `summary.json` | Totals, success rate, average and p95 latency, CPU reserved and load per node |
| `vms.csv`, `nodes.csv` | Every VM and node at the end of the run |
| `comparison.csv` / `.json` | One row per policy |
| `before_after.csv` | Each metric before and after a node change |
| `*.png` | Charts: task outcomes, placement by tier, latency vs deadline, node CPU, before/after |
| `settings_used.json` | The exact settings, reusable with `--config` to repeat the run |

As admin, menu option 15 (or the Results page) changes one node field, for example `edge-1 cpu_cores 8` or `cloud-1 base_latency_ms 150`, runs the same workload again and shows what changed. You can then keep the change for the rest of the session. A tenant's export contains only their own decisions and VMs.

## Experiments

The four experiments the brief requires run with one command:

```bash
python run_experiments.py
```

| Experiment | What it shows |
|------------|---------------|
| E1 Policy comparison | The same 20 tasks through all four policies: the smart policies run nothing late and get more tasks on time |
| E2 Overload | Edge already 90% busy, then 10 urgent tasks: Capacity-Aware moves tasks to Fog or rejects them with a reason; Latency-First runs 9 of 10 late |
| E3 Unauthorised access | hospital-b tries to read and stop hospital-a's task and VM: all 3 attempts are refused and logged; the admin can read them |
| E4 Node change | (a) Edge CPU 4 → 8: more tasks on Edge and on time. (b) Cloud latency 80 → 150 ms: Cloud tasks slow down, medium tasks can't use it any more, low tasks still finish on time |

Each experiment states its expected outcome, runs, then checks the expectation against the actual numbers. The output folder `results/<time>-experiments/` holds `experiments.md` (setup, expected outcome, actual outcome with tables and charts, checks, evidence links) and one evidence folder per experiment. Change the workloads or node changes in `config/experiments.json`, or pass your own file with `--experiments my_experiments.json`. The admin can also run them from menu option 16 or the app's Results page.

## Test

```bash
pytest
```

## Project layout

| Path | What it holds |
|------|---------------|
| `edgefogsim/` | Simulator source code |
| `config/` | Default settings you can edit: nodes, tenants, simulation, experiments |
| `examples/tasks_sample.csv` | Template for supplying your own task list |
| `tests/` | pytest suite |
| `docs/SPEC.md` | Feature spec, acceptance criteria and delivery phases |
| `docs/screenshots/` | Screenshots used in this README |

## Using your own parameters

Every default lives in `config/`. Edit those files, or override them without touching the defaults:

1. `--config my_settings.json`: any subset of `config/simulation.json`, plus optional `nodes` and `tenants` lists.
2. Command-line options (table above).
3. Menu option 18 or the app's Settings page to change a setting, then menu option 19 or the app's download button to save everything to a file you can reuse with `--config`.

Later layers win. Menu option 17 and the app's Settings page show every setting and where its value came from. A bad value stops with the file, row or key, and the reason, e.g. `my_tasks.csv, row 4 (line 5), cpu_cores: must be > 0 (got -2)`.

Task files use the columns in [examples/tasks_sample.csv](examples/tasks_sample.csv); leave `id` blank to number tasks automatically. Details in [docs/SPEC.md §3a](docs/SPEC.md).
