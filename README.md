# EdgeFogSim

A locally runnable Python simulator that places computing tasks on Edge, Fog or Cloud nodes, simulates VMs and tenant isolation, and reports QoS results. ARM 305 Cloud, Dev, Edge and Fog Computing mini project.

> **Status:** Phase 0 (project setup). The menu and simulation arrive in later phases. See [docs/SPEC.md](docs/SPEC.md) for the full plan.

## Setup

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m edgefogsim --help
```

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

Every default lives in `config/`. Edit those files, or pass your own with `--config`, `--nodes` and `--tasks` (details in [docs/SPEC.md §3a](docs/SPEC.md)).
