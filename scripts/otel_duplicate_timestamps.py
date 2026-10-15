#!/usr/bin/env python3
"""Find the metric series that are written twice with the SAME timestamp and DIFFERENT values.

Grafana Cloud discards such a sample (``reason="sample_duplicate_timestamp"``). The input is the
collector's ``debug`` exporter output (``verbosity: detailed``, tf-modules ``debug_metrics``) as a
CloudWatch dump from ``aws logs filter-log-events``; the output says WHICH resource, metric and labels
collide, and what kind of collision it is, which names the writer.

    python3 otel_duplicate_timestamps.py dump.json
    python3 otel_duplicate_timestamps.py --self-test

Standard library only. Exit status: 0 no conflict, 1 conflicts found, 2 unusable input.

HOW THE DUMP IS READ. The ``awslogs`` driver sends one CloudWatch event PER LINE, and one collector
batch is a multi-line block that starts with a line ``<ts>  info  ResourceMetrics #0``. So the events of
each log stream (= one task) are fed in dump order to a small state machine per stream. A batch is kept
only if the datapoint count it parsed equals the count in the ``Metrics {... "data points": N}`` header the
collector logs just before it: a dump that lost or reordered lines is reported, not trusted.

WHAT COUNTS AS THE SAME SERIES. What Prometheus (and so Grafana Cloud) sees, not what OpenTelemetry sees:
  * the resource is ``service.name`` + ``service.instance.id`` (the OTLP resource that becomes job/instance);
  * metric and label names are sanitised the way the OTLP->Prometheus translation does (``http.method`` and
    ``http_method`` are one label), label VALUES are compared as text (``Int(1)`` and ``Str(1)`` are one value);
  * the timestamp is truncated to MILLISECONDS (Prometheus timestamps are ms): two points a few
    microseconds apart collide.
Same series + same millisecond + a different value is a conflict. Same value repeated is harmless and only counted.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import json
import re
import sys
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Tuple

# ── Reading the CloudWatch dump ─────────────────────────────────────────────────────────────────────────


def iter_events(fp, chunk_size: int = 1 << 20) -> Iterator[dict]:
    """Yield the events of an ``aws logs`` dump without holding the file in memory.

    Accepts the ``{"events": [...]}`` document of ``filter-log-events`` / ``get-log-events``, a bare
    ``[...]`` array (``--query 'events[]'``), and one event per line (NDJSON).
    """
    decoder = json.JSONDecoder()
    buf = fp.read(chunk_size)
    eof = len(buf) < chunk_size
    pos = 0

    def refill() -> bool:
        nonlocal buf, pos, eof
        if eof:
            return False
        more = fp.read(chunk_size)
        if len(more) < chunk_size:
            eof = True
        buf = buf[pos:] + more
        pos = 0
        return bool(more)

    def skip_ws() -> None:
        nonlocal pos
        while True:
            while pos < len(buf) and buf[pos] in " \t\r\n,":
                pos += 1
            if pos < len(buf) or not refill():
                return

    skip_ws()
    if pos >= len(buf):
        return

    if buf[pos] == "[":
        pos += 1
    elif buf[pos] == "{":
        # NDJSON (an event per line) or the document form: tell them apart by what the first object is. A
        # first object that is cut by the chunk edge is retried with more input, unless the "events" array
        # of the document form shows up first.
        events_key = re.compile(r'"events"\s*:\s*\[')
        while True:
            try:
                first, end = decoder.raw_decode(buf, pos)
                break
            except json.JSONDecodeError:
                if events_key.search(buf, pos):
                    first, end = None, None
                    break
                if not refill():
                    raise
        if isinstance(first, dict) and "message" in first:
            yield first
            pos = end
            while True:
                skip_ws()
                if pos >= len(buf):
                    return
                try:
                    obj, pos = decoder.raw_decode(buf, pos)
                except json.JSONDecodeError:
                    if not refill():
                        raise
                    continue
                yield obj
        # The document form: find the "events" array.
        while True:
            m = re.compile(r'"events"\s*:\s*\[').search(buf, pos)
            if m:
                pos = m.end()
                break
            if not refill():
                raise ValueError('no "events" array in the input')
    else:
        raise ValueError("the input is not JSON")

    while True:
        skip_ws()
        if pos >= len(buf):
            return
        if buf[pos] == "]":
            return
        try:
            obj, pos = decoder.raw_decode(buf, pos)
        except json.JSONDecodeError:
            if not refill():
                raise
            continue
        yield obj


# ── Parsing the debug exporter's text ───────────────────────────────────────────────────────────────────

# The first line of a collector log record: ``2026-10-14T10:20:00.123Z<TAB>info<TAB>message``.
RECORD_START = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\t(?P<level>\w+)\t(?P<rest>.*)$")
HEADER_COUNTS = re.compile(
    r'"resource metrics":\s*(?P<r>\d+),\s*"metrics":\s*(?P<m>\d+),\s*"data points":\s*(?P<d>\d+)'
)
ATTR_LINE = re.compile(
    r"^\s+-> (?P<k>.*?): (?P<t>Str|Int|Bool|Double|Bytes|Slice|Map|Empty)\((?P<v>.*?)(?P<close>\))?$"
)
DATAPOINT_START = re.compile(
    r"^(?P<kind>NumberDataPoints|HistogramDataPoints|ExponentialHistogramDataPoints|SummaryDataPoints) #\d+$"
)
TS = re.compile(r"^(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)(?:\.(\d+))? \+0000 UTC$")


def parse_ts(text: str) -> Optional[Tuple[int, int]]:
    """``2026-10-14 10:20:00.123456 +0000 UTC`` -> (epoch milliseconds, nanoseconds within the second)."""
    m = TS.match(text.strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = (m.group(7) or "").ljust(9, "0")[:9]
    seconds = int(dt.datetime(y, mo, d, h, mi, s, tzinfo=dt.timezone.utc).timestamp())
    nanos = int(frac)
    return seconds * 1000 + nanos // 1_000_000, nanos


@dataclasses.dataclass
class Observation:
    """One datapoint as the collector logged it."""

    stream: str
    batch: int  # index of the batch within its stream
    logged_at: int  # CloudWatch timestamp (ms) of the batch's first line
    resource: Tuple[Tuple[str, str], ...]
    scope: str
    metric: str  # as logged
    kind: str
    attrs: Tuple[Tuple[str, str], ...]  # as logged
    ts_ms: int
    ts_ns: int
    value: str  # canonical text of the value fields


def prom_name(name: str) -> str:
    """OpenTelemetry -> Prometheus name sanitising: anything outside [a-zA-Z0-9_:] becomes ``_``."""
    out = re.sub(r"[^a-zA-Z0-9_:]", "_", name)
    return ("_" + out) if out[:1].isdigit() else out


def canon_number(text: str) -> str:
    try:
        number = float(text)
    except ValueError:
        return text
    return repr(number)


class StreamParser:
    """The state machine for ONE log stream (one task's collector)."""

    def __init__(self, stream: str, sink: Callable[[Observation], None]) -> None:
        self.stream = stream
        self.sink = sink
        self.batch = -1
        self.expected: Optional[Tuple[int, int, int]] = None  # counts from the "Metrics {...}" header
        self.stats = collections.Counter()
        self.bad_batches: List[str] = []
        self._reset_batch()

    # -- batch bookkeeping ----------------------------------------------------------------------------------
    def _reset_batch(self) -> None:
        self.in_batch = False
        self.pending: List[Observation] = []
        self.counts = [0, 0, 0]  # resources, metrics, datapoints parsed
        self.mode = ""  # what the indented ``->`` lines belong to
        self.resource: List[Tuple[str, str]] = []
        self.scope = ""
        self.metric = ""
        self.kind = ""
        self.dp: Optional[dict] = None
        self.open_attr: Optional[List[str]] = None  # [target, key, type, value-so-far]
        self.batch_logged_at = 0

    def _flush_dp(self) -> None:
        dp, self.dp = self.dp, None
        if dp is None:
            return
        ts = parse_ts(dp.get("Timestamp", ""))
        if ts is None:
            self.stats["datapoints_without_timestamp"] += 1
            return
        self.counts[2] += 1
        self.pending.append(
            Observation(
                stream=self.stream,
                batch=self.batch,
                logged_at=self.batch_logged_at,
                resource=tuple(self.resource),
                scope=self.scope,
                metric=self.metric,
                kind=dp["kind"],
                attrs=tuple(dp["attrs"]),
                ts_ms=ts[0],
                ts_ns=ts[1],
                value="|".join(dp["value"]),
            )
        )

    def _end_batch(self) -> None:
        if not self.in_batch:
            return
        self._flush_dp()
        parsed = (self.counts[0], self.counts[1], self.counts[2])
        if self.expected is not None and parsed != self.expected:
            self.stats["batches_incomplete"] += 1
            if len(self.bad_batches) < 5:
                self.bad_batches.append(
                    f"stream {self.stream} batch {self.batch}: header said resources/metrics/datapoints "
                    f"{self.expected}, parsed {parsed}"
                )
        else:
            self.stats["batches_ok"] += 1
            for obs in self.pending:
                self.sink(obs)
            self.stats["datapoints"] += len(self.pending)
        self.expected = None
        self._reset_batch()

    # -- one line at a time ---------------------------------------------------------------------------------
    def feed(self, line: str, logged_at: int) -> None:
        start = RECORD_START.match(line)
        if start:
            self._end_batch()
            rest = start.group("rest")
            if rest.startswith("Metrics\t"):
                counts = HEADER_COUNTS.search(rest)
                self.expected = (
                    (int(counts["r"]), int(counts["m"]), int(counts["d"])) if counts else None
                )
            elif rest.startswith("ResourceMetrics #"):
                self.batch += 1
                self.in_batch = True
                self.batch_logged_at = logged_at
                self._line(rest)
            return
        if not self.in_batch:
            return
        if line.startswith('\t{"kind"'):  # the structured-fields tail the logger puts after the block
            self._end_batch()
            return
        self._line(line)

    def _line(self, line: str) -> None:
        if self.open_attr is not None:  # an attribute value that spans lines
            self.open_attr[3] += "\n" + line
            if line.endswith(")"):
                self._close_attr()
            return
        if line.startswith("ResourceMetrics #"):
            self._flush_dp()
            self.counts[0] += 1
            self.resource, self.scope, self.metric, self.mode = [], "", "", ""
            return
        if line == "Resource attributes:":
            self.mode = "resource"
            return
        if line.startswith("ScopeMetrics #"):
            self._flush_dp()
            self.mode = ""
            return
        if line.startswith("InstrumentationScope "):
            self.scope = line[len("InstrumentationScope ") :].strip()
            self.mode = "scope"
            return
        if line.startswith("Metric #"):
            self._flush_dp()
            self.counts[1] += 1
            self.metric, self.kind, self.mode = "", "", "descriptor"
            return
        if line == "Descriptor:":
            self.mode = "descriptor"
            return
        m = DATAPOINT_START.match(line)
        if m:
            self._flush_dp()
            self.dp = {"kind": m.group("kind"), "attrs": [], "value": [], "Timestamp": ""}
            self.mode = "dp"
            return
        if line == "Data point attributes:":
            self.mode = "dpattrs"
            return
        if line in ("Exemplars:", "Exemplar #0") or line.startswith("Exemplar #"):
            self.mode = "exemplars"
            return
        if self.mode in ("resource", "dpattrs") and line.startswith(" "):
            self._attr(line)
            return
        if self.mode == "descriptor" and line.startswith("     -> "):
            name, _, value = line[len("     -> ") :].partition(": ")
            if name == "Name":
                self.metric = value
            elif name == "DataType":
                self.kind = value
            return
        if self.dp is not None and self.mode in ("dp", "dpattrs"):
            self.mode = "dp"
            if line.startswith("StartTimestamp:"):
                return  # not part of a series' identity
            if line.startswith("Timestamp:"):
                self.dp["Timestamp"] = line[len("Timestamp:") :].strip()
                return
            if line.startswith("Flags:"):
                self.dp["value"].append(line.strip())
                return
            self.dp["value"].append(re.sub(r"(-?\d+\.\d+|-?\d+)\s*$", lambda mm: canon_number(mm.group(1)), line))

    def _attr(self, line: str) -> None:
        m = ATTR_LINE.match(line)
        if not m:
            return
        target = "resource" if self.mode == "resource" else "dp"
        if m.group("close"):
            self._store_attr(target, m.group("k"), m.group("v"))
        else:  # the value has a newline in it; the closing ``)`` is on a later line
            self.open_attr = [target, m.group("k"), m.group("t"), m.group("v")]

    def _close_attr(self) -> None:
        target, key, _type, value = self.open_attr  # type: ignore[misc]
        self.open_attr = None
        self._store_attr(target, key, value[:-1] if value.endswith(")") else value)

    def _store_attr(self, target: str, key: str, value: str) -> None:
        if target == "resource":
            self.resource.append((key, value))
        elif self.dp is not None:
            self.dp["attrs"].append((key, value))

    def close(self) -> None:
        self._end_batch()


# ── Grouping and classification ─────────────────────────────────────────────────────────────────────────


def resource_id(resource: Tuple[Tuple[str, str], ...]) -> str:
    d = dict(resource)
    return f"{d.get('service.name', '?')} / {d.get('service.instance.id', '?')}"


def series_key(obs: Observation) -> Tuple:
    labels = tuple(sorted((prom_name(k), v) for k, v in obs.attrs))
    return (resource_id(obs.resource), prom_name(obs.metric), labels, obs.ts_ms)


@dataclasses.dataclass
class Conflict:
    key: Tuple
    observations: List[Observation]

    @property
    def resource(self) -> str:
        return self.key[0]

    @property
    def metric(self) -> str:
        return self.key[1]

    def tags(self) -> List[str]:
        obs = self.observations
        tags = []
        batches = {(o.stream, o.batch) for o in obs}
        streams = {o.stream for o in obs}
        tags.append("same-batch" if len(batches) == 1 else "across-batches")
        tags.append("same-task" if len(streams) == 1 else "ACROSS-TASKS")
        scopes = {o.scope for o in obs}
        tags.append("one-scope" if len(scopes) == 1 else "ACROSS-SCOPES")
        if len({o.resource for o in obs}) > 1:
            tags.append("RESOURCE-ATTRS-DIFFER")
        if len({o.metric for o in obs}) > 1 or len({tuple(sorted(k for k, _ in o.attrs)) for o in obs}) > 1:
            tags.append("NAMES-COLLIDE-AFTER-SANITISING")
        if len({(o.ts_ms, o.ts_ns) for o in obs}) > 1:
            tags.append("same-ms-different-ns")
        return tags


class Analysis:
    def __init__(self) -> None:
        self.groups: Dict[Tuple, List[Observation]] = collections.defaultdict(list)
        self.streams_of_resource: Dict[str, set] = collections.defaultdict(set)
        self.parsers: Dict[str, StreamParser] = {}
        self.events = 0
        self.lines = 0
        self.unparsed_events = 0

    def add(self, obs: Observation) -> None:
        self.groups[series_key(obs)].append(obs)
        self.streams_of_resource[resource_id(obs.resource)].add(obs.stream)

    def read(self, events: Iterable[dict], default_stream: str = "(stream)") -> None:
        for event in events:
            message = event.get("message")
            if not isinstance(message, str):
                self.unparsed_events += 1
                continue
            self.events += 1
            stream = event.get("logStreamName") or default_stream
            parser = self.parsers.get(stream)
            if parser is None:
                parser = self.parsers[stream] = StreamParser(stream, self.add)
            logged_at = int(event.get("timestamp") or 0)
            for line in message.split("\n"):
                self.lines += 1
                parser.feed(line.rstrip("\r"), logged_at)
        for parser in self.parsers.values():
            parser.close()

    # -- results --------------------------------------------------------------------------------------------
    def conflicts(self) -> List[Conflict]:
        out = []
        for key, observations in self.groups.items():
            if len(observations) > 1 and len({o.value for o in observations}) > 1:
                out.append(Conflict(key, observations))
        return out

    def harmless_repeats(self) -> int:
        return sum(
            1
            for observations in self.groups.values()
            if len(observations) > 1 and len({o.value for o in observations}) == 1
        )

    def totals(self) -> collections.Counter:
        total: collections.Counter = collections.Counter()
        for parser in self.parsers.values():
            total.update(parser.stats)
        return total


# ── Report ──────────────────────────────────────────────────────────────────────────────────────────────


def tag_key(conflict: Conflict) -> str:
    return " + ".join(conflict.tags())


def render(analysis: Analysis, top: int, examples: int) -> str:
    out: List[str] = []
    totals = analysis.totals()
    conflicts = analysis.conflicts()
    out.append("== input ==")
    out.append(
        f"events {analysis.events}, lines {analysis.lines}, streams {len(analysis.parsers)}, "
        f"batches ok {totals['batches_ok']}, batches dropped as incomplete {totals['batches_incomplete']}, "
        f"datapoints {totals['datapoints']}"
    )
    if analysis.unparsed_events:
        out.append(f"events without a message: {analysis.unparsed_events}")
    for parser in analysis.parsers.values():
        for text in parser.bad_batches:
            out.append(f"  INCOMPLETE: {text}")
    if totals["batches_incomplete"]:
        out.append(
            "  (a batch whose parsed counts differ from the collector's own header is NOT used: the dump "
            "lost or reordered lines. Re-run the export for a narrower window, or per stream.)"
        )
    if totals["datapoints"] == 0:
        out.append(
            "  NO DATAPOINTS PARSED: is this the otel-agent stream with debug_metrics on? The log lines must "
            "contain 'ResourceMetrics #0'."
        )
    out.append("")

    # identity clash across tasks: the same resource id written by more than one task
    clashes = {r: s for r, s in analysis.streams_of_resource.items() if len(s) > 1}
    out.append("== resources written by MORE THAN ONE task (same service.name + service.instance.id) ==")
    if clashes:
        for rid, streams in sorted(clashes.items(), key=lambda kv: -len(kv[1])):
            out.append(f"  {rid}: {len(streams)} streams: {', '.join(sorted(streams))}")
    else:
        out.append("  none")
    out.append("")

    out.append(
        f"== conflicts: {len(conflicts)} series-timestamps with different values "
        f"(harmless identical repeats: {analysis.harmless_repeats()}) =="
    )
    if not conflicts:
        out.append("  none in this window")
        return "\n".join(out)
    out.append("")

    out.append("== by KIND of collision (this is the pattern that names the writer) ==")
    by_tags = collections.Counter(tag_key(c) for c in conflicts)
    for tags, count in by_tags.most_common():
        out.append(f"  {count:7d}  {tags}")
    out.append("  how to read: ACROSS-TASKS = two tasks share a resource id; ACROSS-SCOPES = one instrument under two")
    out.append("  scopes; same-task + one-scope + same-batch = one process recorded the point twice (two providers /")
    out.append("  readers, or two instruments with one name); RESOURCE-ATTRS-DIFFER = same service id, different")
    out.append("  resource attributes; NAMES-COLLIDE-AFTER-SANITISING = 'a.b' and 'a_b' are one Prometheus name/label.")
    out.append("")

    out.append(f"== by metric (top {top}) ==")
    by_metric = collections.defaultdict(list)
    for c in conflicts:
        by_metric[c.metric].append(c)
    for metric, items in sorted(by_metric.items(), key=lambda kv: -len(kv[1]))[:top]:
        res = collections.Counter(c.resource for c in items)
        scopes = sorted({o.scope for c in items for o in c.observations})
        out.append(f"  {len(items):7d}  {metric}")
        out.append(f"           scopes: {'; '.join(scopes)}")
        out.append("           resources: " + ", ".join(f"{r} x{n}" for r, n in res.most_common(3)))
    out.append("")

    out.append(f"== by resource (top {top}) ==")
    by_resource = collections.defaultdict(list)
    for c in conflicts:
        by_resource[c.resource].append(c)
    for rid, items in sorted(by_resource.items(), key=lambda kv: -len(kv[1]))[:top]:
        metrics = collections.Counter(c.metric for c in items)
        streams = sorted({o.stream for c in items for o in c.observations})
        out.append(f"  {len(items):7d}  {rid}   ({len(streams)} stream(s): {', '.join(streams)})")
        out.append("           metrics: " + ", ".join(f"{m} x{n}" for m, n in metrics.most_common(5)))
    out.append("")

    out.append(f"== examples (worst {examples} series-timestamps, by number of writes) ==")
    for c in sorted(conflicts, key=lambda c: -len(c.observations))[:examples]:
        _res, metric, labels, ts_ms = c.key
        when = dt.datetime.fromtimestamp(ts_ms / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        out.append(f"  {c.resource}  {metric}{{{', '.join(f'{k}={v}' for k, v in labels)}}}  @ {when}Z   [{tag_key(c)}]")
        for o in c.observations:
            logged = dt.datetime.fromtimestamp(o.logged_at / 1000, tz=dt.timezone.utc).strftime("%H:%M:%S")
            names_differ = len({x.metric for x in c.observations}) > 1
            extra = f" (logged as {o.metric})" if names_differ else ""
            value = o.value[len("Value: ") :] if o.value.startswith("Value: ") and "|" not in o.value else o.value
            out.append(f"      {o.stream} batch {o.batch} @ {logged}  scope [{o.scope}]  {o.kind}{extra}  value {value}")
        resources = {o.resource for o in c.observations}
        if len(resources) > 1:
            dicts = [dict(r) for r in resources]
            keys = sorted({k for d in dicts for k in d if len({d.get(k) for d in dicts}) > 1})
            out.append(f"      resource attributes that differ: {', '.join(keys)}")
    return "\n".join(out)


def to_json(analysis: Analysis) -> dict:
    return {
        "events": analysis.events,
        "datapoints": analysis.totals()["datapoints"],
        "batches_incomplete": analysis.totals()["batches_incomplete"],
        "conflicts": [
            {
                "resource": c.resource,
                "metric": c.metric,
                "labels": dict(c.key[2]),
                "timestamp_ms": c.key[3],
                "tags": c.tags(),
                "observations": [
                    {
                        "stream": o.stream,
                        "batch": o.batch,
                        "scope": o.scope,
                        "metric": o.metric,
                        "value": o.value,
                    }
                    for o in c.observations
                ],
            }
            for c in analysis.conflicts()
        ],
    }


# ── Self-test: a synthetic debug-exporter log with a known duplicate ────────────────────────────────────


def _sample_batch(instance: str, dup: bool) -> str:
    """The text the debug exporter writes (format captured from aws-otel-collector v0.43.3)."""
    res = "".join(f"     -> {k}: Str({v})\n" for k, v in {"service.name": "svc-a", "service.instance.id": instance}.items())
    points = [("5", "/v1/x"), ("3", "/v1/y")] + ([("9", "/v1/x")] if dup else [])
    dps = "".join(
        f"NumberDataPoints #{i}\nData point attributes:\n     -> route: Str({route})\nStartTimestamp: 2026-10-14 10:19:00 +0000 UTC\nTimestamp: 2026-10-14 10:20:00 +0000 UTC\nValue: {value}\n"
        for i, (value, route) in enumerate(points)
    )
    return (
        "ResourceMetrics #0\nResource SchemaURL: \nResource attributes:\n" + res
        + "ScopeMetrics #0\nScopeMetrics SchemaURL: \nInstrumentationScope qnsc dev\nMetric #0\nDescriptor:\n"
        "     -> Name: jobs.total\n     -> Description: \n     -> Unit: \n     -> DataType: Sum\n"
        "     -> IsMonotonic: true\n     -> AggregationTemporality: Cumulative\n" + dps
    )


def synthetic_events(shared_instance: bool = False) -> List[dict]:
    """CloudWatch events (one per line, as the awslogs driver sends them) with ONE known duplicate:
    svc-a / inst-1 / jobs.total{route=/v1/x} written as 5 and as 9 at 10:20:00 in the same batch of task aaaa.
    Task bbbb is a clean control (another instance id). With ``shared_instance`` task bbbb also claims inst-1,
    which is the identity clash across tasks."""
    events: List[dict] = []
    stamp = 1760437200000

    def add(stream: str, text: str, at: int) -> None:
        for line in text.split("\n"):
            events.append({"logStreamName": stream, "timestamp": at, "message": line})

    plan = (
        ("otel-agent/otel-agent/aaaa", "inst-1", True),
        ("otel-agent/otel-agent/bbbb", "inst-1" if shared_instance else "inst-2", False),
    )
    for stream, instance, dup in plan:
        counts = 3 if dup else 2
        add(stream, f'2026-10-14T10:20:01.000Z\tinfo\tMetrics\t{{"kind": "exporter", "data_type": "metrics", "name": "debug", "resource metrics": 1, "metrics": 1, "data points": {counts}}}', stamp)
        body = _sample_batch(instance, dup).rstrip("\n")
        first, rest = body.split("\n", 1)
        add(stream, "2026-10-14T10:20:01.000Z\tinfo\t" + first + "\n" + rest + '\n\t{"kind": "exporter", "data_type": "metrics", "name": "debug"}', stamp)
    return events


def self_test() -> int:
    events = synthetic_events()
    analysis = Analysis()
    analysis.read(events)
    conflicts = analysis.conflicts()
    failures = []
    if len(conflicts) != 1:
        failures.append(f"expected exactly 1 conflict, found {len(conflicts)}")
    else:
        c = conflicts[0]
        if (c.resource, c.metric) != ("svc-a / inst-1", "jobs_total"):
            failures.append(f"wrong series: {c.resource} {c.metric}")
        if sorted(o.value for o in c.observations) != ["Value: 5.0", "Value: 9.0"]:
            failures.append(f"wrong values: {[o.value for o in c.observations]}")
        if "same-batch" not in c.tags() or "same-task" not in c.tags():
            failures.append(f"wrong classification: {c.tags()}")
    clashes = {r for r, s in analysis.streams_of_resource.items() if len(s) > 1}
    if clashes:
        failures.append(f"a clean control task was reported as sharing a resource id: {clashes}")
    if analysis.totals()["batches_incomplete"]:
        failures.append("a complete synthetic batch was dropped as incomplete")
    if failures:
        print("SELF-TEST FAILED:\n  " + "\n  ".join(failures), file=sys.stderr)
        return 1
    print("self-test ok: 1 known duplicate found, classified", conflicts[0].tags())
    return 0


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dump", nargs="?", help="JSON from `aws logs filter-log-events` ('-' = stdin)")
    ap.add_argument("--top", type=int, default=15, help="rows in the by-metric / by-resource tables")
    ap.add_argument("--examples", type=int, default=8, help="worst series-timestamps shown in full")
    ap.add_argument("--json", action="store_true", help="print the conflicts as JSON instead of the report")
    ap.add_argument("--self-test", action="store_true", help="run on a built-in synthetic log and exit")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.dump:
        ap.error("a dump file is required (or --self-test)")
    analysis = Analysis()
    try:
        fp = sys.stdin if args.dump == "-" else open(args.dump, encoding="utf-8")
        with fp:
            analysis.read(iter_events(fp))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"cannot read {args.dump}: {error}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(to_json(analysis), indent=2))
    else:
        print(render(analysis, args.top, args.examples))
    return 1 if analysis.conflicts() else 0


if __name__ == "__main__":
    sys.exit(main())
