# EdgeFogSim

A locally runnable Python simulator that places computing tasks on Edge, Fog or Cloud nodes, simulates VMs and tenant isolation, and reports QoS results. ARM 305 Cloud, Dev, Edge and Fog Computing mini project.

> **Status:** Phase 3 (placement, shared VMs, tenant security). Results export, charts and experiments arrive in later phases. See [docs/SPEC.md](docs/SPEC.md) for the full plan.

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

In either one, log in as a tenant, then:

1. view nodes,
2. build a workload (generate, upload a file or add tasks by hand),
3. run a placement policy and read why each task went where it did,
4. compare all policies on the same workload,
5. view, create and stop VMs (tenant-owned slices of a node that several of that tenant's tasks share), and place a single task on the room that frees up,
6. look up a task or VM by id: another tenant's is refused (ACCESS DENIED) and written to the audit log,
7. view, change or save settings.

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

## Using your own parameters

Every default lives in `config/`. Edit those files, or override them without touching the defaults:

1. `--config my_settings.json`: any subset of `config/simulation.json`, plus optional `nodes` and `tenants` lists.
2. Command-line options (table above).
3. Menu option 15 or the app's Settings page to change a setting, then menu option 16 or the app's download button to save everything to a file you can reuse with `--config`.

Later layers win. Menu option 14 and the app's Settings page show every setting and where its value came from. A bad value stops with the file, row or key, and the reason, e.g. `my_tasks.csv, row 4 (line 5), cpu_cores: must be > 0 (got -2)`.

Task files use the columns in [examples/tasks_sample.csv](examples/tasks_sample.csv); leave `id` blank to number tasks automatically. Details in [docs/SPEC.md §3a](docs/SPEC.md).
