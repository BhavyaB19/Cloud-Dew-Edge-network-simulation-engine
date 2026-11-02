"""Load, merge, validate and save every user-editable setting.

Settings come in layers. Later layers win:

1. Built-in defaults in this module (used only if a file is missing).
2. Files in ``config/``: ``simulation.json``, ``nodes.json``, ``tenants.json``.
3. A ``--config`` file with any subset of those keys.
4. A ``--nodes`` file that replaces the node list.
5. Command-line overrides (``--seed``, ``--set KEY=VALUE``, ...).
6. Edits made in the menu or the Streamlit app (:func:`set_value`).

Every value remembers which layer set it (``Settings.origins``), so a bad value
is reported with the file or layer it came from, the dotted key and the reason,
e.g. ``mine.json, qos.deadlines_ms.low: must be > 0 (got -5)``.
"""

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from edgefogsim.models import ROLES, SENSITIVITIES, TIERS, Node, Tenant

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
"""Folder holding the project's default settings files."""

DEFAULTS_SOURCE = "built-in defaults"
"""Origin label for values that no file or override has changed."""

DEFAULT_SIMULATION: dict[str, Any] = {
    "generator": {
        "count": 12,
        "seed": 42,
        "cpu_range": [1, 4],
        "memory_range": [0.5, 8],
        "work_range": {"high": [1, 6], "medium": [5, 40], "low": [10, 100]},
        "sensitivity_mix": {"high": 0.4, "medium": 0.3, "low": 0.3},
        "tenant_mix": {},
    },
    "qos": {
        "deadlines_ms": {"high": 25, "medium": 100, "low": 400},
        "congestion_cap": 0.95,
    },
    "policy": {
        "headroom": 0.85,
        "tier_preference": {
            "high": ["edge", "fog", "cloud"],
            "medium": ["fog", "edge", "cloud"],
            "low": ["cloud", "fog", "edge"],
        },
        "soft_overload_retry": True,
        "capacity_weights": {"tier": 0.5, "slack": 0.3, "free": 0.2},
        "topsis_weights": {"latency": 0.5, "cpu": 0.3, "memory": 0.2},
    },
    "vm": {
        "sizes": {
            "edge": {"cpu_cores": 2, "memory_gb": 4},
            "fog": {"cpu_cores": 4, "memory_gb": 8},
            "cloud": {"cpu_cores": 8, "memory_gb": 16},
        },
    },
    "security": {
        "audit_log": "results/audit.log",
    },
    "qlearning": {
        "alpha": 0.1,
        "gamma": 0.9,
        "epsilon": 0.2,
        "episodes": 500,
        "train_seed": 1000,
    },
}

DEFAULT_NODES: list[dict[str, Any]] = [
    {"id": "edge-1", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 5, "speed_factor": 0.6},
    {"id": "fog-1", "tier": "fog", "cpu_cores": 16, "memory_gb": 32, "base_latency_ms": 20, "speed_factor": 1.0},
    {"id": "cloud-1", "tier": "cloud", "cpu_cores": 128, "memory_gb": 512, "base_latency_ms": 80, "speed_factor": 2.0},
]

DEFAULT_TENANTS: list[dict[str, Any]] = [
    {"tenant_id": "hospital-a", "role": "tenant"},
    {"tenant_id": "hospital-b", "role": "tenant"},
    {"tenant_id": "admin", "role": "admin"},
]

# Maps whose keys are chosen by the user; an override replaces the whole map
# (so {"high": 1.0} means "only high", not "high plus the old medium and low").
FREE_KEY_MAPS = {"generator.sensitivity_mix", "generator.tenant_mix"}


class ConfigError(ValueError):
    """A setting is missing, unknown or invalid. The message names where it came from."""

    def __init__(self, source: str, location: str, message: str):
        """Build the error.

        Args:
            source: Where the bad value came from: a file path, "command line" or "menu".
            location: The dotted key, list index or row that is wrong, e.g. ``nodes[0].cpu_cores``.
            message: What is wrong, in plain words.
        """
        super().__init__(f"{source}, {location}: {message}")
        self.source = source
        self.location = location


@dataclass
class Settings:
    """All resolved settings for one run.

    Attributes:
        simulation: Nested dict shaped like ``config/simulation.json``
            (``generator``, ``qos``, ``policy``, ``vm``, ``security``, ``qlearning``).
        nodes: The nodes to simulate, with live usage starting at zero.
        tenants: Everyone who can log in.
        sources: Every layer that contributed, lowest precedence first.
        origins: Dotted setting path -> the layer that last set it.
    """

    simulation: dict[str, Any]
    nodes: list[Node]
    tenants: list[Tenant]
    sources: list[str] = field(default_factory=list)
    origins: dict[str, str] = field(default_factory=dict)

    def get(self, dotted: str) -> Any:
        """Read one setting by its dotted path.

        Args:
            dotted: Path such as ``"qos.deadlines_ms.high"``.

        Returns:
            The value at that path (a number, list or dict).

        Raises:
            KeyError: If the path does not exist.
        """
        value: Any = self.simulation
        for part in dotted.split("."):
            value = value[part]
        return value

    def tenant(self, tenant_id: str) -> Tenant | None:
        """Find a tenant by id.

        Args:
            tenant_id: The id to look up, e.g. ``"hospital-a"``.

        Returns:
            The matching tenant, or None if there is no such tenant.
        """
        return next((t for t in self.tenants if t.tenant_id == tenant_id), None)


def load_settings(
    config_dir: Path | str = CONFIG_DIR,
    config_file: Path | str | None = None,
    nodes_file: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
) -> Settings:
    """Build validated settings from every layer, lowest precedence first.

    Args:
        config_dir: Folder with the default ``simulation.json``, ``nodes.json`` and
            ``tenants.json``. Missing files fall back to the built-in defaults.
        config_file: Optional user file overriding any subset of the simulation
            settings; it may also contain ``nodes`` and ``tenants`` lists.
        nodes_file: Optional file replacing the node list, either
            ``{"nodes": [...]}`` or a bare list.
        overrides: Dotted path -> value, e.g. ``{"generator.seed": 7}``,
            usually built from command-line flags.

    Returns:
        Fully validated settings, with ``origins`` recording where each value came from.

    Raises:
        ConfigError: If any file is missing or malformed, a key is unknown, or a
            value is invalid. The message names the source, key and reason.
    """
    config_dir = Path(config_dir)
    simulation = copy.deepcopy(DEFAULT_SIMULATION)
    origins: dict[str, str] = {}
    sources = [DEFAULTS_SOURCE]
    nodes_raw, nodes_source = DEFAULT_NODES, DEFAULTS_SOURCE
    tenants_raw, tenants_source = DEFAULT_TENANTS, DEFAULTS_SOURCE

    sim_path = config_dir / "simulation.json"
    if sim_path.exists():
        _merge(simulation, _read_json(sim_path), "", str(sim_path), origins)
        sources.append(str(sim_path))
    nodes_path = config_dir / "nodes.json"
    if nodes_path.exists():
        nodes_raw, nodes_source = _list_from(_read_json(nodes_path), "nodes", nodes_path), str(nodes_path)
        sources.append(str(nodes_path))
    tenants_path = config_dir / "tenants.json"
    if tenants_path.exists():
        tenants_raw, tenants_source = _list_from(_read_json(tenants_path), "tenants", tenants_path), str(tenants_path)
        sources.append(str(tenants_path))

    if config_file:
        data = _read_json(Path(config_file))
        if not isinstance(data, dict):
            raise ConfigError(str(config_file), "top level", "must be a JSON object")
        if "nodes" in data:
            nodes_raw, nodes_source = data.pop("nodes"), str(config_file)
        if "tenants" in data:
            tenants_raw, tenants_source = data.pop("tenants"), str(config_file)
        _merge(simulation, data, "", str(config_file), origins)
        sources.append(str(config_file))

    if nodes_file:
        nodes_raw, nodes_source = _list_from(_read_json(Path(nodes_file)), "nodes", nodes_file), str(nodes_file)
        sources.append(str(nodes_file))

    for dotted, value in (overrides or {}).items():
        _set_path(simulation, dotted, value, "command line", origins)
    if overrides:
        sources.append("command line")

    nodes = parse_nodes(nodes_raw, nodes_source)
    tenants = parse_tenants(tenants_raw, tenants_source)
    settings = Settings(simulation, nodes, tenants, sources, origins)
    validate_simulation(settings)
    return settings


def set_value(settings: Settings, dotted: str, value: Any, source: str = "menu") -> None:
    """Change one setting in place, as the menu and Streamlit app do.

    The change is validated on a copy first, so on any error the settings are
    left exactly as they were.

    Args:
        settings: The settings to change.
        dotted: Path of the setting, e.g. ``"generator.seed"``.
        value: The new value, already converted (see :func:`parse_value`).
        source: Label recorded as the value's origin.

    Raises:
        ConfigError: If the path is unknown or the new value is invalid.
    """
    trial = Settings(
        copy.deepcopy(settings.simulation),
        settings.nodes,
        settings.tenants,
        settings.sources,
        dict(settings.origins),
    )
    _set_path(trial.simulation, dotted, value, source, trial.origins)
    validate_simulation(trial)
    settings.simulation = trial.simulation
    settings.origins = trial.origins
    if source not in settings.sources:
        settings.sources.append(source)


def save_settings(settings: Settings, path: Path | str) -> Path:
    """Write the resolved settings to JSON, so a run can be repeated exactly.

    The file has the same shape as a ``--config`` file (plus ``nodes``,
    ``tenants`` and an informational ``sources`` list), so it can be passed
    straight back with ``--config``.

    Args:
        settings: The settings to save.
        path: Destination file; parent folders are created if needed.

    Returns:
        The path written.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings_as_json(settings))
    return path


def settings_as_json(settings: Settings) -> str:
    """Serialise settings in the ``--config`` file format.

    Args:
        settings: The settings to serialise.

    Returns:
        Indented JSON text with the simulation settings, ``nodes``, ``tenants``
        and an informational ``sources`` list.
    """
    data = {
        **settings.simulation,
        "nodes": [_node_definition(n) for n in settings.nodes],
        "tenants": [asdict(t) for t in settings.tenants],
        "sources": settings.sources,
    }
    return json.dumps(data, indent=2) + "\n"


def describe_settings(settings: Settings) -> list[tuple[str, Any, str]]:
    """List every individual setting for display.

    Args:
        settings: The settings to describe.

    Returns:
        ``(dotted path, value, source)`` for each leaf setting, in file order.
        File sources are shortened to the file name, e.g. ``simulation.json``.
    """
    rows = []

    def walk(data: dict, prefix: str) -> None:
        """Append a row per leaf value under ``data``."""
        for key, value in data.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict) and value:
                walk(value, f"{path}.")
            else:
                source = origin_of(settings.origins, path)
                rows.append((path, value, Path(source).name if "/" in source else source))

    walk(settings.simulation, "")
    return rows


def parse_value(text: str) -> Any:
    """Convert text typed by a user into a JSON value.

    Args:
        text: Raw text, e.g. ``"40"``, ``"true"``, ``"[1, 4]"`` or ``"edge"``.

    Returns:
        The parsed JSON value (``40``, ``True``, ``[1, 4]``), or the original
        text when it is not valid JSON (``"edge"``).
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_nodes(raw: Any, source: str) -> list[Node]:
    """Validate raw node definitions and build Node objects.

    Args:
        raw: List of dicts with ``id, tier, cpu_cores, memory_gb,
            base_latency_ms, speed_factor``. Any number of nodes per tier is allowed.
        source: File or layer the list came from, used in error messages.

    Returns:
        The nodes, in file order, with zero usage.

    Raises:
        ConfigError: On a missing or unknown field, duplicate id, unknown tier,
            or a non-positive size or speed.
    """
    if not isinstance(raw, list) or not raw:
        raise ConfigError(source, "nodes", "must be a non-empty list of nodes")
    required = ("id", "tier", "cpu_cores", "memory_gb", "base_latency_ms", "speed_factor")
    nodes, seen = [], set()
    for i, item in enumerate(raw):
        where = f"nodes[{i}]"
        if not isinstance(item, dict):
            raise ConfigError(source, where, "must be an object")
        _check_fields(item, required, source, where)
        node_id = item["id"]
        if not isinstance(node_id, str) or not node_id.strip():
            raise ConfigError(source, f"{where}.id", "must be a non-empty string")
        if node_id in seen:
            raise ConfigError(source, f"{where}.id", f"duplicate node id '{node_id}'")
        seen.add(node_id)
        if item["tier"] not in TIERS:
            raise ConfigError(source, f"{where}.tier", f"must be one of {', '.join(TIERS)} (got {item['tier']!r})")
        for key in ("cpu_cores", "memory_gb", "speed_factor"):
            _require_number(item[key], source, f"{where}.{key}", minimum=0, inclusive=False)
        _require_number(item["base_latency_ms"], source, f"{where}.base_latency_ms", minimum=0)
        nodes.append(Node(**item))
    return nodes


def parse_tenants(raw: Any, source: str) -> list[Tenant]:
    """Validate raw tenant definitions and build Tenant objects.

    Args:
        raw: List of dicts with ``tenant_id`` and ``role`` ("tenant" or "admin").
        source: File or layer the list came from, used in error messages.

    Returns:
        The tenants, in file order.

    Raises:
        ConfigError: On a missing or unknown field, duplicate id, unknown role,
            or when no tenant has the "tenant" role.
    """
    if not isinstance(raw, list) or not raw:
        raise ConfigError(source, "tenants", "must be a non-empty list of tenants")
    tenants, seen = [], set()
    for i, item in enumerate(raw):
        where = f"tenants[{i}]"
        if not isinstance(item, dict):
            raise ConfigError(source, where, "must be an object")
        _check_fields(item, ("tenant_id", "role"), source, where)
        tenant_id = item["tenant_id"]
        if not isinstance(tenant_id, str) or not tenant_id.strip():
            raise ConfigError(source, f"{where}.tenant_id", "must be a non-empty string")
        if tenant_id in seen:
            raise ConfigError(source, f"{where}.tenant_id", f"duplicate tenant id '{tenant_id}'")
        seen.add(tenant_id)
        if item["role"] not in ROLES:
            raise ConfigError(source, f"{where}.role", f"must be one of {', '.join(ROLES)} (got {item['role']!r})")
        tenants.append(Tenant(**item))
    if not any(t.role == "tenant" for t in tenants):
        raise ConfigError(source, "tenants", "needs at least one tenant with role 'tenant'")
    return tenants


def validate_simulation(settings: Settings) -> None:
    """Check every simulation setting's type and range.

    Args:
        settings: Settings whose ``simulation`` dict has been fully merged.

    Raises:
        ConfigError: For the first invalid value found, naming the layer that
            set it (from ``settings.origins``), its dotted path and the rule broken.
    """
    sim, origins = settings.simulation, settings.origins

    def fail(path: str, message: str) -> None:
        """Raise a ConfigError for ``path``, blaming the layer that set it."""
        raise ConfigError(origin_of(origins, path), path, message)

    def number(path: str, minimum: float | None = None, maximum: float | None = None,
               inclusive_min: bool = True, integer: bool = False) -> None:
        """Require a number at ``path``, optionally whole and within bounds."""
        value = settings.get(path)
        if integer and (not isinstance(value, int) or isinstance(value, bool)):
            fail(path, f"must be a whole number (got {value!r})")
        if not _is_number(value):
            fail(path, f"must be a number (got {value!r})")
        if minimum is not None and (value < minimum or (not inclusive_min and value == minimum)):
            fail(path, f"must be {'>=' if inclusive_min else '>'} {minimum} (got {value})")
        if maximum is not None and value > maximum:
            fail(path, f"must be <= {maximum} (got {value})")

    def value_range(path: str) -> None:
        """Require ``[min, max]`` with ``0 < min <= max`` at ``path``."""
        value = settings.get(path)
        if not (isinstance(value, list) and len(value) == 2 and all(_is_number(v) for v in value)):
            fail(path, f"must be [min, max] (got {value!r})")
        if value[0] <= 0 or value[0] > value[1]:
            fail(path, f"needs 0 < min <= max (got {value})")

    def weights(path: str, keys: tuple[str, ...]) -> None:
        """Require non-negative weights for exactly ``keys``, not all zero."""
        mapping = settings.get(path)
        if not isinstance(mapping, dict):
            fail(path, "must be an object")
        for key in keys:
            if key not in mapping:
                fail(f"{path}.{key}", "is missing")
            number(f"{path}.{key}", minimum=0)
        if sum(mapping[k] for k in keys) <= 0:
            fail(path, "weights must not all be 0")

    def mix(path: str, allowed: list[str]) -> None:
        """Require non-negative shares keyed by names from ``allowed``."""
        mapping = settings.get(path)
        if not isinstance(mapping, dict):
            fail(path, "must be an object")
        for key in mapping:
            if key not in allowed:
                fail(f"{path}.{key}", f"unknown name; expected one of {', '.join(allowed)}")
            number(f"{path}.{key}", minimum=0)
        if mapping and sum(mapping.values()) <= 0:
            fail(path, "shares must not all be 0")

    number("generator.count", minimum=1, integer=True)
    number("generator.seed", integer=True)
    for key in ("cpu_range", "memory_range"):
        value_range(f"generator.{key}")
    for level in SENSITIVITIES:
        value_range(f"generator.work_range.{level}")
    mix("generator.sensitivity_mix", list(SENSITIVITIES))
    if not sim["generator"]["sensitivity_mix"]:
        fail("generator.sensitivity_mix", "must name at least one sensitivity")
    mix("generator.tenant_mix", [t.tenant_id for t in settings.tenants if t.role == "tenant"])

    for level in SENSITIVITIES:
        number(f"qos.deadlines_ms.{level}", minimum=0, inclusive_min=False)
    number("qos.congestion_cap", minimum=0, maximum=0.99, inclusive_min=False)

    number("policy.headroom", minimum=0, maximum=1, inclusive_min=False)
    for level in SENSITIVITIES:
        path = f"policy.tier_preference.{level}"
        order = settings.get(path)
        if (not isinstance(order, list) or not order or len(set(order)) != len(order)
                or any(t not in TIERS for t in order)):
            fail(path, f"must list tiers from {', '.join(TIERS)} without repeats (got {order!r})")
    if not isinstance(sim["policy"]["soft_overload_retry"], bool):
        fail("policy.soft_overload_retry", "must be true or false")
    weights("policy.capacity_weights", ("tier", "slack", "free"))
    weights("policy.topsis_weights", ("latency", "cpu", "memory"))

    for tier in TIERS:
        for key in ("cpu_cores", "memory_gb"):
            number(f"vm.sizes.{tier}.{key}", minimum=0, inclusive_min=False)

    audit_log = settings.get("security.audit_log")
    if not isinstance(audit_log, str) or not audit_log.strip():
        fail("security.audit_log", "must be a file path")

    number("qlearning.alpha", minimum=0, maximum=1, inclusive_min=False)
    number("qlearning.gamma", minimum=0, maximum=1)
    number("qlearning.epsilon", minimum=0, maximum=1)
    number("qlearning.episodes", minimum=1, integer=True)
    number("qlearning.train_seed", integer=True)


def _merge(target: dict, incoming: Any, prefix: str, source: str, origins: dict[str, str]) -> None:
    """Deep-merge ``incoming`` into ``target``, rejecting unknown keys.

    Nested groups merge key by key; leaf values, lists and the maps in
    ``FREE_KEY_MAPS`` are replaced whole.

    Args:
        target: Settings dict to update in place.
        incoming: Dict read from a file.
        prefix: Dotted path of ``target`` within the full settings ("" at the top).
        source: Layer name recorded in ``origins`` and used in errors.
        origins: Origin map to update.

    Raises:
        ConfigError: If ``incoming`` is not a dict or contains an unknown key.
    """
    if not isinstance(incoming, dict):
        raise ConfigError(source, prefix or "top level", "must be a JSON object")
    for key, value in incoming.items():
        path = f"{prefix}{key}"
        if key not in target:
            raise ConfigError(source, path, f"unknown setting; expected one of {', '.join(target)}")
        if path in FREE_KEY_MAPS or not isinstance(target[key], dict):
            target[key] = copy.deepcopy(value)
            _record(origins, path, value, source)
        else:
            _merge(target[key], value, f"{path}.", source, origins)


def _set_path(target: dict, dotted: str, value: Any, source: str, origins: dict[str, str]) -> None:
    """Set one existing setting by dotted path.

    New keys are only allowed inside ``FREE_KEY_MAPS`` (e.g. a new tenant's
    share in ``generator.tenant_mix``). A whole group such as ``qos`` cannot be
    replaced this way, to avoid wiping its other keys by accident.

    Args:
        target: Settings dict to update in place.
        dotted: Path such as ``"policy.headroom"``.
        value: New value.
        source: Layer name recorded in ``origins`` and used in errors.
        origins: Origin map to update.

    Raises:
        ConfigError: If the path is unknown or names a group.
    """
    parts = dotted.split(".")
    node = target
    for i, part in enumerate(parts[:-1]):
        path = ".".join(parts[: i + 1])
        if not isinstance(node, dict) or part not in node:
            raise ConfigError(source, dotted, f"unknown setting '{path}'")
        node = node[part]
    parent = ".".join(parts[:-1])
    if not isinstance(node, dict) or (parts[-1] not in node and parent not in FREE_KEY_MAPS):
        raise ConfigError(source, dotted, "unknown setting")
    if isinstance(node.get(parts[-1]), dict) and dotted not in FREE_KEY_MAPS:
        raise ConfigError(source, dotted, "is a group of settings; set one of its keys instead")
    node[parts[-1]] = value
    _record(origins, dotted, value, source)


def _record(origins: dict[str, str], path: str, value: Any, source: str) -> None:
    """Record ``source`` as the origin of ``path`` and of every key nested under it."""
    for key in [k for k in origins if k.startswith(f"{path}.")]:
        del origins[key]
    origins[path] = source
    if isinstance(value, dict):
        for key, inner in value.items():
            _record(origins, f"{path}.{key}", inner, source)


def origin_of(origins: dict[str, str], path: str) -> str:
    """Find which layer set a value.

    Args:
        origins: Origin map from ``Settings.origins``.
        path: Dotted setting path.

    Returns:
        The origin of ``path`` or of its nearest recorded parent, or
        ``DEFAULTS_SOURCE`` if nothing overrode it.
    """
    while path:
        if path in origins:
            return origins[path]
        path = path.rpartition(".")[0]
    return DEFAULTS_SOURCE


def _read_json(path: Path) -> Any:
    """Read a JSON file, turning file and syntax errors into ConfigError."""
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        raise ConfigError(str(path), "file", "not found") from None
    except json.JSONDecodeError as exc:
        raise ConfigError(str(path), f"line {exc.lineno}", f"invalid JSON: {exc.msg}") from None


def _list_from(data: Any, key: str, source: Path | str) -> Any:
    """Return ``data[key]`` for ``{"nodes": [...]}``-style files, or ``data`` itself for a bare list."""
    if isinstance(data, dict):
        if key not in data:
            raise ConfigError(str(source), key, "is missing")
        return data[key]
    return data


def _check_fields(item: dict, required: tuple[str, ...], source: str, where: str) -> None:
    """Raise ConfigError if ``item`` lacks any ``required`` field or has an extra one."""
    for key in required:
        if key not in item:
            raise ConfigError(source, f"{where}.{key}", "is missing")
    for key in item:
        if key not in required:
            raise ConfigError(source, f"{where}.{key}", f"unknown field; expected {', '.join(required)}")


def _require_number(value: Any, source: str, where: str, minimum: float, inclusive: bool = True) -> None:
    """Raise ConfigError unless ``value`` is a number >= ``minimum`` (or > when not inclusive)."""
    if not _is_number(value):
        raise ConfigError(source, where, f"must be a number (got {value!r})")
    if value < minimum or (not inclusive and value == minimum):
        raise ConfigError(source, where, f"must be {'>=' if inclusive else '>'} {minimum} (got {value})")


def _is_number(value: Any) -> bool:
    """True for ints and floats; False for bools, which Python treats as ints."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _node_definition(node: Node) -> dict[str, Any]:
    """A node's static definition as a dict, without its live usage fields."""
    data = asdict(node)
    for live in ("cpu_used", "memory_used", "cpu_load", "memory_load"):
        data.pop(live)
    return data
