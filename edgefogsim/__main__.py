"""Command-line entry point: ``python -m edgefogsim [menu|run] [options]``.

Parses options, turns them into setting overrides, loads and validates the
settings, then starts the chosen command. With no command, the menu starts.
A settings error prints one clear line and exits with status 2.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from edgefogsim import __version__
from edgefogsim.config import ConfigError, Settings, load_settings, parse_value
from edgefogsim.models import Task
from edgefogsim.workload import load_tasks

COMMANDS = ("menu", "web", "run", "experiments")
"""Sub-commands; ``menu`` is assumed when none is given."""

WEB_ARGS_ENV = "EDGEFOGSIM_ARGS"
"""Environment variable carrying the ``web`` command's options (a JSON list) to the Streamlit app."""


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser.

    Options shared by every command (settings files and overrides) live on a
    parent parser, so ``menu --seed 7`` and ``run --seed 7`` both work.

    Returns:
        The configured parser.
    """
    parser = argparse.ArgumentParser(
        prog="edgefogsim",
        description="Simulate placing computing tasks on Edge, Fog and Cloud nodes.",
        epilog="With no command, the interactive menu starts. "
               "Run 'python -m edgefogsim menu --help' to see every option.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--config", metavar="FILE", help="JSON file overriding any subset of the default settings")
    shared.add_argument("--nodes", metavar="FILE", help="JSON file with your own node definitions")
    shared.add_argument("--tasks", metavar="N|FILE",
                        help="number of random tasks to generate, or a CSV/JSON task file")
    shared.add_argument("--seed", type=int, help="random seed for generated tasks")
    shared.add_argument("--deadline", metavar="LEVEL=MS", action="append", default=[],
                        help="deadline for a sensitivity level, e.g. high=40 (repeatable)")
    shared.add_argument("--headroom", type=float, help="max node utilisation for Capacity-Aware, e.g. 0.9")
    shared.add_argument("--set", metavar="KEY=VALUE", action="append", default=[], dest="settings",
                        help="change any setting, e.g. generator.count=20 (repeatable)")

    sub = parser.add_subparsers(dest="command", metavar="{menu,web,run,experiments}")
    sub.add_parser("menu", parents=[shared], help="interactive command-line menu (default)")
    web = sub.add_parser("web", parents=[shared], help="open the Streamlit app in your browser")
    web.add_argument("--port", type=int, default=8501, help="port for the Streamlit server (default: 8501)")
    experiments = sub.add_parser("experiments", parents=[shared],
                                 help="run the four required experiments and write experiments.md")
    experiments.add_argument("--experiments", metavar="FILE", dest="experiments_file",
                             help="experiment definitions (default: config/experiments.json)")
    run = sub.add_parser("run", parents=[shared], help="run a workload through a policy without the menu")
    run.add_argument(
        "--policy",
        choices=["latency", "cloud", "capacity", "topsis", "all"],
        default="capacity",
        help="placement policy, or 'all' to compare every policy (default: capacity)",
    )
    return parser


def collect_overrides(args: argparse.Namespace) -> dict:
    """Turn command-line flags into dotted setting overrides.

    Args:
        args: Parsed arguments from :func:`build_parser`.

    Returns:
        Dotted path -> value, e.g. ``{"generator.seed": 7, "qos.deadlines_ms.high": 40}``.
        ``--tasks N`` sets ``generator.count``; ``--tasks FILE`` is handled by :func:`main`.

    Raises:
        ConfigError: If a ``--set`` item is not ``KEY=VALUE``.
    """
    overrides = {}
    if args.seed is not None:
        overrides["generator.seed"] = args.seed
    if args.tasks and args.tasks.isdigit():
        overrides["generator.count"] = int(args.tasks)
    if args.headroom is not None:
        overrides["policy.headroom"] = args.headroom
    for item in args.deadline:
        level, _, ms = item.partition("=")
        overrides[f"qos.deadlines_ms.{level.strip()}"] = parse_value(ms)
    for item in args.settings:
        key, sep, value = item.partition("=")
        if not sep:
            raise ConfigError("command line", item, "expected KEY=VALUE")
        overrides[key.strip()] = parse_value(value.strip())
    return overrides


def prepare(args: argparse.Namespace) -> tuple[Settings, list[Task]]:
    """Load settings and the starting workload for any command.

    Args:
        args: Parsed arguments from :func:`build_parser`.

    Returns:
        The validated settings and the tasks from ``--tasks FILE`` (empty otherwise).

    Raises:
        ConfigError: If a settings file, override or task file is invalid.
    """
    settings = load_settings(config_file=args.config, nodes_file=args.nodes, overrides=collect_overrides(args))
    tasks = load_tasks(args.tasks, settings) if args.tasks and not args.tasks.isdigit() else []
    return settings, tasks


def launch_web(options: list[str], port: int) -> int:
    """Start the Streamlit app, passing the shared options through an environment variable.

    Args:
        options: The command-line options given after ``web`` (minus ``--port``),
            re-parsed by the app so it starts with the same settings.
        port: Port for the Streamlit server.

    Returns:
        Streamlit's exit status.
    """
    app = Path(__file__).resolve().parent / "web.py"
    env = {**os.environ, WEB_ARGS_ENV: json.dumps(options)}
    command = [sys.executable, "-m", "streamlit", "run", str(app), "--server.port", str(port)]
    try:
        return subprocess.call(command, env=env)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    """Run the program.

    Args:
        argv: Arguments without the program name; defaults to ``sys.argv[1:]``.

    Returns:
        Exit status: 0 on success, 2 on a settings or task-file error.
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "menu")
    args = build_parser().parse_args(argv)

    try:
        settings, tasks = prepare(args)
    except ConfigError as exc:
        print(f"Settings error: {exc}", file=sys.stderr)
        return 2

    if args.command == "web":
        options = _without_port(argv[1:])
        return launch_web(options, args.port)

    if args.command == "run":
        return run_command(settings, tasks, args.policy)
    if args.command == "experiments":
        return experiments_command(settings, args.experiments_file)

    from edgefogsim.cli import App

    try:
        App(settings, tasks).run()
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")
    return 0


def run_command(settings: Settings, tasks: list[Task], policy: str) -> int:
    """Place a workload without the menu and print the decisions (or a comparison).

    Args:
        settings: Resolved settings.
        tasks: Tasks from ``--tasks FILE``; when empty, ``generator.count`` random
            tasks are generated with ``generator.seed``.
        policy: A policy key, or ``"all"`` to compare every policy.

    Returns:
        Exit status 0.
    """
    from rich.console import Console

    from edgefogsim.cli import print_comparison, print_run
    from edgefogsim.simulator import compare_policies, run_workload
    from edgefogsim.workload import generate_tasks

    console = Console()
    tasks = tasks or generate_tasks(settings)
    if policy == "all":
        print_comparison(console, compare_policies(settings, tasks))
    else:
        print_run(console, run_workload(settings, tasks, policy))
    return 0


def experiments_command(settings: Settings, experiments_file: str | None) -> int:
    """Run E1-E4, print a summary and where the evidence and ``experiments.md`` were written.

    Args:
        settings: Resolved settings.
        experiments_file: Optional experiment definitions file; defaults to ``config/experiments.json``.

    Returns:
        Exit status: 0 when the experiments ran (whatever their results), 2 on a definitions error.
    """
    from rich.console import Console

    from edgefogsim.cli import print_experiments
    from edgefogsim.experiments import EXPERIMENTS_FILE, load_experiments, run_all

    try:
        run = run_all(settings, load_experiments(experiments_file or EXPERIMENTS_FILE))
    except ConfigError as exc:
        print(f"Experiments error: {exc}", file=sys.stderr)
        return 2
    print_experiments(Console(), run)
    return 0


def _without_port(options: list[str]) -> list[str]:
    """Drop ``--port N`` / ``--port=N`` from an option list; the app itself doesn't take it."""
    kept, skip = [], False
    for item in options:
        if skip:
            skip = False
        elif item == "--port":
            skip = True
        elif not item.startswith("--port="):
            kept.append(item)
    return kept


if __name__ == "__main__":
    sys.exit(main())
