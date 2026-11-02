import json

import pytest

from edgefogsim.config import ConfigError, load_settings, save_settings, set_value


def test_partial_config_file_overrides_only_its_keys(write_json, settings):
    """AC16: a --config file setting one deadline leaves everything else at its default."""
    custom = load_settings(config_file=write_json("mine.json", {"qos": {"deadlines_ms": {"high": 40}}}))
    assert custom.get("qos.deadlines_ms.high") == 40
    expected = json.loads(json.dumps(settings.simulation))
    expected["qos"]["deadlines_ms"]["high"] = 40
    assert custom.simulation == expected


def test_command_line_beats_config_file_and_is_saved(write_json, tmp_path):
    """AC17: a flag wins over a config file, and settings_used.json records the final value."""
    custom = load_settings(
        config_file=write_json("mine.json", {"generator": {"seed": 7}}),
        overrides={"generator.seed": 99},
    )
    assert custom.get("generator.seed") == 99
    assert custom.origins["generator.seed"] == "command line"

    saved = json.loads(save_settings(custom, tmp_path / "settings_used.json").read_text())
    assert saved["generator"]["seed"] == 99
    assert "command line" in saved["sources"]


def test_user_nodes_file_with_two_edges_and_no_fog(write_json):
    """AC18: any number of nodes per tier, and a tier may be missing."""
    nodes = {"nodes": [
        {"id": "edge-1", "tier": "edge", "cpu_cores": 4, "memory_gb": 8, "base_latency_ms": 5, "speed_factor": 0.6},
        {"id": "edge-2", "tier": "edge", "cpu_cores": 8, "memory_gb": 16, "base_latency_ms": 6, "speed_factor": 0.8},
        {"id": "cloud-1", "tier": "cloud", "cpu_cores": 64, "memory_gb": 256, "base_latency_ms": 90,
         "speed_factor": 2.0},
    ]}
    custom = load_settings(nodes_file=write_json("my_nodes.json", nodes))
    assert [n.id for n in custom.nodes] == ["edge-1", "edge-2", "cloud-1"]
    assert "fog" not in {n.tier for n in custom.nodes}


@pytest.mark.parametrize(
    "kwargs_factory, expected",
    [
        # AC19: each message names the file (or "command line"), the key and the reason.
        (lambda w: {"nodes_file": w("bad_nodes.json", {"nodes": [
            {"id": "e", "tier": "edge", "cpu_cores": -2, "memory_gb": 8, "base_latency_ms": 5,
             "speed_factor": 1}]})},
         ["bad_nodes.json", "nodes[0].cpu_cores", "must be > 0"]),
        (lambda w: {"nodes_file": w("bad_tier.json", {"nodes": [
            {"id": "e", "tier": "space", "cpu_cores": 2, "memory_gb": 8, "base_latency_ms": 5,
             "speed_factor": 1}]})},
         ["bad_tier.json", "nodes[0].tier", "edge, fog, cloud"]),
        (lambda w: {"config_file": w("typo.json", {"qos": {"deadline_ms": {"high": 40}}})},
         ["typo.json", "qos.deadline_ms", "unknown setting"]),
        (lambda w: {"config_file": w("neg.json", {"qos": {"deadlines_ms": {"low": -5}}})},
         ["neg.json", "qos.deadlines_ms.low", "must be > 0"]),
        (lambda w: {"overrides": {"policy.headroom": 1.5}},
         ["command line", "policy.headroom", "must be <= 1"]),
        (lambda w: {"overrides": {"policy.tier_preference.high": ["edge", "edge"]}},
         ["command line", "policy.tier_preference.high", "without repeats"]),
        (lambda w: {"overrides": {"generator.tenant_mix": {"hospital-z": 1}}},
         ["command line", "generator.tenant_mix.hospital-z", "unknown name"]),
        (lambda w: {"overrides": {"generator.count": 2.5}},
         ["command line", "generator.count", "whole number"]),
    ],
)
def test_invalid_values_name_file_key_and_reason(write_json, kwargs_factory, expected):
    """AC19: invalid input fails loudly with its source, location and reason."""
    with pytest.raises(ConfigError) as info:
        load_settings(**kwargs_factory(write_json))
    message = str(info.value)
    for part in expected:
        assert part in message


def test_free_key_maps_are_replaced_not_merged(write_json):
    custom = load_settings(config_file=write_json("only_high.json",
                                                  {"generator": {"sensitivity_mix": {"high": 1.0}}}))
    assert custom.get("generator.sensitivity_mix") == {"high": 1.0}


def test_set_value_applies_or_leaves_settings_untouched(settings):
    set_value(settings, "qos.deadlines_ms.medium", 120)
    assert settings.get("qos.deadlines_ms.medium") == 120
    assert settings.origins["qos.deadlines_ms.medium"] == "menu"

    with pytest.raises(ConfigError):
        set_value(settings, "qos.deadlines_ms.medium", "fast")
    assert settings.get("qos.deadlines_ms.medium") == 120


def test_bare_list_nodes_file_is_accepted(write_json):
    custom = load_settings(nodes_file=write_json("bare.json", [
        {"id": "fog-9", "tier": "fog", "cpu_cores": 8, "memory_gb": 8, "base_latency_ms": 15, "speed_factor": 1},
    ]))
    assert custom.nodes[0].id == "fog-9"
