# EdgeFogSim

A locally runnable Python simulator that places computing tasks on Edge, Fog or Cloud nodes, simulates VMs and tenant isolation, and reports QoS results. ARM 305 Cloud, Dev, Edge and Fog Computing mini project.

> **Status:** Phase 1 (nodes, workloads, settings). Placement and results arrive in later phases. See [docs/SPEC.md](docs/SPEC.md) for the full plan.

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m edgefogsim
```

Log in as a tenant, then use the menu to view nodes, generate or load tasks, add a task by hand, and view or change settings.

Useful options (they work with the menu and with `run`):

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
3. Menu option 7 (change a setting), then option 8 to save everything to a file you can reuse with `--config`.

Later layers win. Menu option 6 shows every setting and where its value came from. A bad value stops with the file, row or key, and the reason, e.g. `my_tasks.csv, row 4 (line 5), cpu_cores: must be > 0 (got -2)`.

Task files use the columns in [examples/tasks_sample.csv](examples/tasks_sample.csv); leave `id` blank to number tasks automatically. Details in [docs/SPEC.md §3a](docs/SPEC.md).
