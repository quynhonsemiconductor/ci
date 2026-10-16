"""Tests for otel_duplicate_timestamps.py — the tool that names the writer of duplicate-timestamp samples.

Two kinds of input: the REAL output of the collector's debug exporter (captured from
aws-otel-collector v0.43.3 with the config tf-modules renders), and synthetic logs for the cases a real run
cannot be asked to produce on demand. The real captures contain known duplicates; the expected answers below
were worked out by hand from the OTLP that was posted.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "otel_duplicate_timestamps.py"
FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
spec = importlib.util.spec_from_file_location("otel_duplicate_timestamps", SCRIPT)
tool = importlib.util.module_from_spec(spec)
sys.modules["otel_duplicate_timestamps"] = tool
spec.loader.exec_module(tool)

STREAM = "otel-agent/otel-agent/0123456789abcdef"


def cloudwatch_events(text: str, stream: str = STREAM, start: int = 1_760_000_000_000) -> list[dict]:
    """What the awslogs driver does to a container's output: one CloudWatch event per line."""
    return [
        {"logStreamName": stream, "timestamp": start + i // 50, "message": line}
        for i, line in enumerate(text.split("\n"))
    ]


def analyse(events: list[dict]) -> "tool.Analysis":
    analysis = tool.Analysis()
    analysis.read(events)
    return analysis


HEADER = (
    '2026-10-14T10:20:00.000Z\tinfo\tMetrics\t{"kind": "exporter", "data_type": "metrics", "name": "debug", '
    '"resource metrics": 1, "metrics": 1, "data points": %d}'
)
FIELDS = '\t{"kind": "exporter", "data_type": "metrics", "name": "debug"}'


def block(points: list[tuple[str, str, str]], *, service="svc", instance="i1", scope="qnsc dev",
          metric="jobs.total", label_key="route", header=True, namespace=None, unit="",
          datatype="Sum", monotonic=True) -> str:
    """A debug-exporter record. points: (timestamp, label value, value line text)."""
    lines = []
    if header:
        lines.append(HEADER % len(points))
    lines += [
        "2026-10-14T10:20:00.000Z\tinfo\tResourceMetrics #0",
        "Resource SchemaURL: ",
        "Resource attributes:",
        f"     -> service.name: Str({service})",
        f"     -> service.instance.id: Str({instance})",
        *([f"     -> service.namespace: Str({namespace})"] if namespace else []),
        "ScopeMetrics #0",
        "ScopeMetrics SchemaURL: ",
        f"InstrumentationScope {scope}",
        "Metric #0",
        "Descriptor:",
        f"     -> Name: {metric}",
        "     -> Description: ",
        f"     -> Unit: {unit}",
        f"     -> DataType: {datatype}",
        *(["     -> IsMonotonic: " + ("true" if monotonic else "false")] if datatype == "Sum" else []),
        "     -> AggregationTemporality: Cumulative",
    ]
    for i, (ts, label, value) in enumerate(points):
        lines += [
            f"NumberDataPoints #{i}",
            "Data point attributes:",
            f"     -> {label_key}: {label}",
            "StartTimestamp: 2026-10-14 10:00:00 +0000 UTC",
            f"Timestamp: {ts}",
            value,
        ]
    lines.append(FIELDS)
    return "\n".join(lines)


T0 = "2026-10-14 10:20:00 +0000 UTC"


# ── the real captures ─────────────────────────────────────────────────────────────────────────────────────


def test_real_capture_with_known_duplicates():
    text = (FIXTURES / "otel_debug_real_v0.43.3_duplicates.txt").read_text()
    analysis = analyse(cloudwatch_events(text))
    totals = analysis.totals()
    assert totals["batches_ok"] == 2 and totals["batches_incomplete"] == 0
    assert totals["datapoints"] == 8  # 7 in the first batch, 1 in the second: the collector's own headers say so

    (conflict,) = analysis.conflicts()
    assert conflict.resource == "rova-api / 11111111-aaaa"
    assert conflict.metric == "http_server_requests_total"  # monotonic sum: the Prometheus name
    assert dict(conflict.key[2]) == {
        "method": "GET",
        "route": "/v1/x",
        "job": "rova/rova-api",  # service.namespace/service.name of the capture
        "instance": "11111111-aaaa",
    }
    assert sorted(o.value for o in conflict.observations) == ["Value: 5.0", "Value: 6.0", "Value: 7.0", "Value: 9.0"]
    assert conflict.tags() == ["across-batches", "same-task", "one-scope", "RESOURCE-ATTRS-DIFFER"]
    # the same series written once is not reported
    assert all(len(o) == 1 for key, o in analysis.groups.items() if dict(key[2]).get("route") == "/v1/y")


def test_real_capture_report_names_what_differs():
    text = (FIXTURES / "otel_debug_real_v0.43.3_duplicates.txt").read_text()
    report = tool.render(analyse(cloudwatch_events(text)), top=5, examples=3)
    assert "rova-api / 11111111-aaaa" in report
    assert "http_server_requests_total" in report
    assert "RESOURCE-ATTRS-DIFFER" in report
    assert "resource attributes that differ: cloud.provider" in report
    assert "value 9.0" in report


def test_real_capture_of_every_datapoint_kind():
    text = (FIXTURES / "otel_debug_real_v0.43.3_kinds.txt").read_text()
    analysis = analyse(cloudwatch_events(text))
    assert analysis.totals()["batches_ok"] == 1  # parsed counts equal the header's: resources 1, metrics 4, points 4
    seen = {o.metric: o for group in analysis.groups.values() for o in group}
    assert {o.kind for o in seen.values()} == {
        "ExponentialHistogramDataPoints",
        "SummaryDataPoints",
        "NumberDataPoints",
    }
    assert set(seen) == {"exp.hist", "summ", "dbl", 'weird "name" with spaces\tand\ttab'}
    weird = seen['weird "name" with spaces\tand\ttab']
    # an attribute value with a newline in it spans two log lines and is put back together
    assert dict(weird.attrs) == {"k with space": "v: with colon -> arrow", "multi": "line1\nline2"}
    # exemplar lines ("-> Timestamp", "-> Value") must not leak into the datapoint
    assert "1.0" not in seen["dbl"].value and seen["dbl"].value == "Value: 1.25"
    assert not analysis.conflicts()


# ── the known duplicate, synthetic ────────────────────────────────────────────────────────────────────────


def test_self_test_passes_and_is_what_the_cli_runs():
    assert tool.self_test() == 0
    done = subprocess.run([sys.executable, str(SCRIPT), "--self-test"], capture_output=True, text=True)
    assert done.returncode == 0 and "self-test ok" in done.stdout


def test_synthetic_duplicate_is_found_and_a_clean_task_is_not():
    analysis = analyse(tool.synthetic_events())
    (conflict,) = analysis.conflicts()
    assert (conflict.resource, conflict.metric) == ("svc-a / inst-1", "jobs_total")
    assert {o.stream for o in conflict.observations} == {"otel-agent/otel-agent/aaaa"}
    assert conflict.tags() == ["same-batch", "same-task", "one-scope"]


def test_two_tasks_that_share_a_service_instance_id_are_reported():
    analysis = analyse(tool.synthetic_events(shared_instance=True))
    assert analysis.streams_of_resource["svc-a / inst-1"] == {
        "otel-agent/otel-agent/aaaa",
        "otel-agent/otel-agent/bbbb",
    }
    (conflict,) = analysis.conflicts()
    assert "ACROSS-TASKS" in conflict.tags()
    report = tool.render(analysis, 5, 5)
    assert "svc-a / inst-1: 2 streams" in report


# ── what counts as the same series ────────────────────────────────────────────────────────────────────────


def one_stream(*blocks: str) -> "tool.Analysis":
    return analyse(cloudwatch_events("\n".join(blocks)))


def test_same_value_repeated_is_harmless_and_counted_separately():
    a = one_stream(block([(T0, "Str(/x)", "Value: 5")]), block([(T0, "Str(/x)", "Value: 5.000000")]))
    assert not a.conflicts() and a.harmless_repeats() == 1  # "5" and "5.000000" are the same number


def test_different_value_same_timestamp_is_a_conflict_but_a_later_timestamp_is_not():
    later = "2026-10-14 10:20:10 +0000 UTC"
    a = one_stream(block([(T0, "Str(/x)", "Value: 5")]), block([(later, "Str(/x)", "Value: 6")]))
    assert not a.conflicts()
    b = one_stream(block([(T0, "Str(/x)", "Value: 5")]), block([(T0, "Str(/x)", "Value: 6")]))
    assert len(b.conflicts()) == 1


@pytest.mark.parametrize(
    "second, collides",
    [
        ("2026-10-14 10:20:00.000300 +0000 UTC", True),  # 300 microseconds later: the same millisecond
        ("2026-10-14 10:20:00.000999999 +0000 UTC", True),  # still the same millisecond
        ("2026-10-14 10:20:00.001 +0000 UTC", False),  # the next millisecond
    ],
)
def test_timestamps_collide_at_millisecond_resolution(second, collides):
    a = one_stream(block([(T0, "Str(/x)", "Value: 5")]), block([(second, "Str(/x)", "Value: 6")]))
    assert bool(a.conflicts()) is collides
    if collides:
        assert "same-ms-different-ns" in a.conflicts()[0].tags()


def test_label_values_are_compared_as_text_not_as_otel_types():
    a = one_stream(block([(T0, "Int(1)", "Value: 5")]), block([(T0, "Str(1)", "Value: 6")]))
    assert len(a.conflicts()) == 1  # Prometheus has "1" either way


def test_names_are_compared_after_prometheus_sanitising():
    a = one_stream(
        block([(T0, "Str(/x)", "Value: 5")], metric="http.server.requests", label_key="http.route"),
        block([(T0, "Str(/x)", "Value: 6")], metric="http_server_requests", label_key="http_route"),
    )
    (conflict,) = a.conflicts()
    assert "NAMES-COLLIDE-AFTER-SANITISING" in conflict.tags()


def test_one_instrument_under_two_scopes_is_across_scopes():
    a = one_stream(
        block([(T0, "Str(/x)", "Value: 5")], scope="qnsc dev"),
        block([(T0, "Str(/x)", "Value: 6")], scope="@opentelemetry/instrumentation-http 0.221.0"),
    )
    (conflict,) = a.conflicts()
    assert "ACROSS-SCOPES" in conflict.tags()


def test_other_services_and_instances_do_not_collide():
    a = one_stream(
        block([(T0, "Str(/x)", "Value: 5")], service="svc-a"),
        block([(T0, "Str(/x)", "Value: 6")], service="svc-b"),
        block([(T0, "Str(/x)", "Value: 7")], instance="i2"),
    )
    assert not a.conflicts()


# ── the OTLP -> Prometheus translation ───────────────────────────────────────────────────────────────────


def test_datapoints_that_differ_only_in_a_job_attribute_collapse_and_collide():
    """The bug that was in production: JobMetrics records an attribute named `job`. Grafana's OTLP endpoint sets
    `job` from service.namespace/service.name, replacing it, so every cron job of a worker became ONE series and
    several values arrived for one timestamp. On the OTLP attributes alone the two points are distinct."""
    a = one_stream(block([(T0, "Str(cleanup)", "Value: 3"), (T0, "Str(reports)", "Value: 8")], label_key="job",
                         service="rova-worker", metric="jobs.runs"))
    (conflict,) = a.conflicts()
    assert conflict.metric == "jobs_runs_total"
    assert dict(conflict.key[2]) == {"job": "rova-worker", "instance": "i1"}  # the `job` attribute is gone
    assert "ATTRS-COLLAPSE-IN-TRANSLATION" in conflict.tags()
    assert "OVERRIDDEN-BY-RESOURCE(job)" in conflict.tags()
    assert sorted(o.value for o in conflict.observations) == ["Value: 3.0", "Value: 8.0"]
    report = tool.render(a, 5, 5)
    assert "OVERRIDDEN-BY-RESOURCE(job)" in report
    assert "OTLP attributes: job=cleanup" in report and "OTLP attributes: job=reports" in report


def test_the_same_two_points_under_a_non_reserved_attribute_name_do_not_collide():
    a = one_stream(block([(T0, "Str(cleanup)", "Value: 3"), (T0, "Str(reports)", "Value: 8")], label_key="task",
                         service="rova-worker", metric="jobs.runs"))
    assert not a.conflicts()  # this is the fix: rename the attribute


def test_an_instance_attribute_is_overridden_by_service_instance_id():
    a = one_stream(block([(T0, "Str(a)", "Value: 1"), (T0, "Str(b)", "Value: 2")], label_key="instance"))
    (conflict,) = a.conflicts()
    assert "OVERRIDDEN-BY-RESOURCE(instance)" in conflict.tags()
    assert dict(conflict.key[2])["instance"] == "i1"


def test_an_attribute_called_job_with_the_resources_own_value_is_not_blamed():
    a = one_stream(block([(T0, "Str(svc)", "Value: 1"), (T0, "Str(svc)", "Value: 2")], label_key="job"))
    (conflict,) = a.conflicts()  # still a duplicate, but not an override: the values were the same
    assert not any(t.startswith("OVERRIDDEN") for t in conflict.tags())


def test_job_is_namespace_slash_name_when_there_is_a_namespace():
    obs = next(iter(one_stream(block([(T0, "Str(x)", "Value: 1")], namespace="qnsc", service="rova-api")).groups.values()))[0]
    assert dict(tool.prom_labels(obs))["job"] == "qnsc/rova-api"
    # and a service.namespace separates two services of the same name
    a = one_stream(block([(T0, "Str(x)", "Value: 1")], namespace="qnsc"), block([(T0, "Str(x)", "Value: 2")], namespace="other"))
    assert not a.conflicts()
    b = one_stream(block([(T0, "Str(x)", "Value: 1")]), block([(T0, "Str(x)", "Value: 2")], namespace="qnsc"))
    assert not b.conflicts()  # "svc" and "qnsc/svc" are two jobs


@pytest.mark.parametrize(
    "metric, unit, datatype, monotonic, expected",
    [
        ("http.server.duration", "s", "Histogram", False, "http_server_duration_seconds"),
        ("http.server.duration.seconds", "s", "Histogram", False, "http_server_duration_seconds"),  # not doubled
        ("process.memory", "By", "Gauge", False, "process_memory_bytes"),
        ("cache.hit.ratio", "1", "Gauge", False, "cache_hit_ratio"),
        ("cpu.utilization", "1", "Gauge", False, "cpu_utilization_ratio"),
        ("jobs.runs", "", "Sum", True, "jobs_runs_total"),
        ("jobs.runs.total", "", "Sum", True, "jobs_runs_total"),  # not doubled
        ("queue.depth", "", "Sum", False, "queue_depth"),  # an up-down counter is a gauge
        ("http.requests", "{request}", "Sum", True, "http_requests_total"),  # annotation units are dropped
        ("bytes.sent", "By", "Sum", True, "bytes_sent_bytes_total"),
        ("disk.io", "By/s", "Gauge", False, "disk_io_bytes_per_second"),
        ("a..b--c", "", "Gauge", False, "a_b_c"),
        ("9lives", "", "Gauge", False, "_9lives"),
    ],
)
def test_metric_names_follow_the_prometheus_translation(metric, unit, datatype, monotonic, expected):
    obs = next(iter(one_stream(block([(T0, "Str(x)", "Value: 1")], metric=metric, unit=unit, datatype=datatype,
                                     monotonic=monotonic)).groups.values()))[0]
    assert tool.prom_metric_name(obs) == expected


@pytest.mark.parametrize(
    "attr, expected",
    [("http.method", "http_method"), ("9x", "key_9x"), ("_x", "key_x"), ("__name__", "__name__"), ("a-b c", "a_b_c")],
)
def test_label_names_follow_the_prometheus_translation(attr, expected):
    assert tool.prom_name(attr) == expected


def test_two_attributes_that_sanitise_to_one_label_are_joined():
    obs = next(iter(one_stream(block([(T0, "Str(x)", "Value: 1")], label_key="a.b")).groups.values()))[0]
    obs = tool.dataclasses.replace(obs, attrs=(("a.b", "1"), ("a_b", "2")))
    assert dict(tool.prom_labels(obs))["a_b"] == "1;2"


def test_a_unit_changes_the_name_so_two_units_of_one_metric_do_not_collide():
    a = one_stream(block([(T0, "Str(x)", "Value: 1")], metric="m", unit="s", datatype="Gauge", monotonic=False),
                   block([(T0, "Str(x)", "Value: 2")], metric="m", unit="ms", datatype="Gauge", monotonic=False))
    assert not a.conflicts()


# ── reading the dump ──────────────────────────────────────────────────────────────────────────────────────


def test_a_batch_whose_counts_do_not_match_the_collectors_header_is_not_trusted():
    good = block([(T0, "Str(/x)", "Value: 5"), (T0, "Str(/y)", "Value: 1")])
    lines = good.split("\n")
    drop = next(i for i, line in enumerate(lines) if line == "NumberDataPoints #1")
    broken = "\n".join(lines[:drop] + lines[drop + 6 :])  # a whole datapoint lost in transit
    a = one_stream(broken)
    assert a.totals()["batches_incomplete"] == 1 and a.totals()["datapoints"] == 0
    report = tool.render(a, 5, 5)
    assert "INCOMPLETE" in report and "data points" not in report.split("INCOMPLETE")[0][-5:]


def test_events_of_different_streams_are_read_independently_when_interleaved():
    one = cloudwatch_events(block([(T0, "Str(/x)", "Value: 5")], instance="i1"), stream="s1")
    two = cloudwatch_events(block([(T0, "Str(/x)", "Value: 6")], instance="i2"), stream="s2")
    interleaved = [e for pair in zip(one, two) for e in pair] + one[len(two):] + two[len(one):]
    a = analyse(interleaved)
    assert a.totals()["batches_ok"] == 2 and not a.conflicts()


def test_lines_around_the_block_are_ignored():
    noise = "2026-10-14T10:19:59.000Z\tinfo\totlpreceiver\tStarting HTTP server\n"
    after = "\n2026-10-14T10:20:30.000Z\tinfo\tretry_sender.go:126\tExporting failed. Will retry"
    a = one_stream(noise + block([(T0, "Str(/x)", "Value: 5")]) + after)
    assert a.totals()["datapoints"] == 1


def test_a_multi_line_message_in_one_event_is_read_like_one_event_per_line():
    text = block([(T0, "Str(/x)", "Value: 5"), (T0, "Str(/x)", "Value: 9")])
    whole = analyse([{"logStreamName": "s", "timestamp": 1, "message": text}])
    assert len(whole.conflicts()) == 1


DUMP_EVENTS = [{"logStreamName": "s", "timestamp": i, "eventId": str(i), "message": f"line {i}"} for i in range(40)]


@pytest.mark.parametrize("chunk", [1, 7, 64, 1 << 20])
@pytest.mark.parametrize(
    "shape",
    ["document", "array", "ndjson"],
)
def test_all_dump_shapes_stream_through_any_chunk_size(shape, chunk):
    if shape == "document":
        text = json.dumps({"events": DUMP_EVENTS, "searchedLogStreams": [{"logStreamName": "s"}]}, indent=2)
    elif shape == "array":
        text = json.dumps(DUMP_EVENTS)
    else:
        text = "\n".join(json.dumps(e) for e in DUMP_EVENTS)
    assert list(tool.iter_events(io.StringIO(text), chunk_size=chunk)) == DUMP_EVENTS


@pytest.mark.parametrize("text", ["", "   ", "not json", '{"nothing": 1}', '{"events": [{"message": "x"'])
def test_unusable_input_is_an_error_not_a_silent_empty_report(text):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        events = list(tool.iter_events(io.StringIO(text), chunk_size=16))
        if not events:
            raise ValueError("no events")


def test_a_dump_with_no_datapoints_says_so():
    a = analyse(cloudwatch_events("just\nsome\nlines"))
    assert "NO DATAPOINTS PARSED" in tool.render(a, 5, 5)


# ── the command line ──────────────────────────────────────────────────────────────────────────────────────


def run_cli(tmp_path, events, *args):
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps({"events": events, "searchedLogStreams": []}))
    return subprocess.run([sys.executable, str(SCRIPT), str(dump), *args], capture_output=True, text=True)


def test_exit_status_one_with_conflicts_zero_without(tmp_path):
    found = run_cli(tmp_path, tool.synthetic_events())
    assert found.returncode == 1 and "svc-a / inst-1" in found.stdout and "jobs_total" in found.stdout
    clean = run_cli(tmp_path, cloudwatch_events(block([(T0, "Str(/x)", "Value: 5")])))
    assert clean.returncode == 0 and "none in this window" in clean.stdout


def test_exit_status_two_for_a_file_that_is_not_a_dump(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("this is not json")
    done = subprocess.run([sys.executable, str(SCRIPT), str(bad)], capture_output=True, text=True)
    assert done.returncode == 2 and "cannot read" in done.stderr
    missing = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.json")], capture_output=True, text=True)
    assert missing.returncode == 2


def test_json_output_is_machine_readable(tmp_path):
    done = run_cli(tmp_path, tool.synthetic_events(), "--json")
    data = json.loads(done.stdout)
    assert data["datapoints"] == 5 and len(data["conflicts"]) == 1
    assert data["conflicts"][0]["metric"] == "jobs_total"
    assert data["conflicts"][0]["labels"] == {"route": "/v1/x", "job": "svc-a", "instance": "inst-1"}
    assert sorted(o["value"] for o in data["conflicts"][0]["observations"]) == ["Value: 5.0", "Value: 9.0"]


# ── it must run anywhere with just Python ────────────────────────────────────────────────────────────────


def test_standard_library_only():
    tree = ast.parse(SCRIPT.read_text())
    imported = {
        (node.module or "").split(".")[0] if isinstance(node, ast.ImportFrom) else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [None])
    }
    assert imported <= set(sys.stdlib_module_names), imported - set(sys.stdlib_module_names)
