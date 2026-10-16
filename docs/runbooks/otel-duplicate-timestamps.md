# Runbook: find the writer of `sample_duplicate_timestamp`

**Symptom.** `grafanacloud_instance_samples_discarded_per_second{reason="sample_duplicate_timestamp"}` is above 0.
The same series (identical labels) reached Grafana Cloud twice for one timestamp with different values, so the
counters and histograms we alert on are silently wrong.

**Method.** Turn on the collector's `debug` exporter on the DEVELOP sidecars for a short while, dump 20 minutes of
its log, and let `scripts/otel_duplicate_timestamps.py` list every series written twice for one timestamp, with the
resource, scope and task of each write. The pattern of the collisions names the writer.

Develop only. The log holds application data (route names, label values) and costs CloudWatch ingestion
(~5 GB/day for both products, ~US$2.5/day); keep it on for hours, not days.

## 1. Turn it on

`debug_metrics = true` is already in `infra/live/develop/main.tf` of rova and opshub (PRs "develop-only
debug_metrics"). It needs `observability-agent` >= 1.1.0 (tf-modules#161 merged and released).
Apply develop as usual (infra-plan, then apply). The sidecars restart; **wait for the new tasks**: the old ones keep
the old config, and a rolling deploy is itself a source of duplicates, so note the time the new tasks are `RUNNING`.

## 2. Log groups and streams

Region `ap-southeast-1`.

| Product | Log groups |
|---|---|
| rova | `/ecs/rova-develop-api`, `/ecs/rova-develop-worker` |
| opshub | `/ecs/opshub-develop-api`, `/ecs/opshub-develop-worker` |

The group is shared with the app and firelens containers. The collector sidecar writes to the streams
`otel-agent/otel-agent/<task-id>`, one stream per task, so `--log-stream-name-prefix otel-agent/` selects only it
and tasks of an old and a new deploy are separate streams.

## 3. Dump 20 minutes

Pick a window that starts after the new tasks are running and, if you want the deploy spikes, one that includes a
rolling deploy (run a no-op redeploy of the service). Times are epoch milliseconds, UTC.

```bash
export AWS_REGION=ap-southeast-1
END=$(( $(date -u +%s) * 1000 ))
START=$(( END - 20*60*1000 ))

for g in /ecs/rova-develop-api /ecs/rova-develop-worker /ecs/opshub-develop-api /ecs/opshub-develop-worker; do
  aws logs filter-log-events \
    --log-group-name "$g" \
    --log-stream-name-prefix otel-agent/ \
    --start-time "$START" --end-time "$END" \
    --output json > "dump-$(basename "$g").json"
done
```

Expect 66-400 MB per 20 minutes (see the tf-modules README, "Diagnostic: `debug_metrics`"). If the CLI is too slow
or memory-hungry, use 5-minute windows and run the script once per file.

Analyse **each file separately**, and the api and worker of a product together too (see step 5): a clash between
api and worker is only visible when both are in one run, but the files can be passed one after another (step 4).

## 4. Run the script

Python 3.10+, standard library only. The report compares series as Grafana Cloud stores them, after the
OTLP-to-Prometheus translation (`job`, `instance` from the resource, sanitised names, unit and `_total` suffixes),
not as OTLP sends them.

```bash
python3 scripts/otel_duplicate_timestamps.py --self-test      # once: proves the parser on a known duplicate
python3 scripts/otel_duplicate_timestamps.py dump-rova-develop-api.json    > report-rova-api.txt
python3 scripts/otel_duplicate_timestamps.py dump-rova-develop-worker.json > report-rova-worker.txt
python3 scripts/otel_duplicate_timestamps.py dump-opshub-develop-api.json  > report-opshub-api.txt
python3 scripts/otel_duplicate_timestamps.py dump-opshub-develop-worker.json > report-opshub-worker.txt
```

Memory: about 1.2 KB per datapoint (300 000 datapoints: 370 MB, 6 s). `--json` prints the conflicts as JSON;
`--top` and `--examples` size the tables. Exit status 0 = no conflict, 1 = conflicts found, 2 = unusable input.

To read api and worker together, concatenate the `events` of two dumps:

```bash
python3 -c 'import json,sys; e=[x for f in sys.argv[1:] for x in json.load(open(f))["events"]]; json.dump({"events": e}, sys.stdout)' \
  dump-rova-develop-api.json dump-rova-develop-worker.json > dump-rova-all.json
```

If the report says `INCOMPLETE`: lines were lost or reordered in the dump (`filter-log-events` does not promise an
order inside one millisecond). Those batches are not used. Re-dump the affected stream with
`aws logs get-log-events --log-group-name ... --log-stream-name <stream> --start-from-head`, which is ordered.

## 5. Send the report

Send `report-*.txt` (the "by KIND of collision" table and the examples are what matter). They contain metric
names, label values and service ids, no secrets. Not the dumps.

How the kind of collision points to the writer:

| Tags | Means | Writer |
|---|---|---|
| `same-batch` + `same-task` + `one-scope` | one process recorded the point twice in one export | two readers/providers in one process, or two instruments with one name |
| `ACROSS-SCOPES` | one instrument under two scopes with identical exported labels | the same metric registered by two meters (e.g. `qnsc` and an instrumentation library) |
| `ACROSS-TASKS` / "resources written by more than one task" | two tasks share `service.name` + `service.instance.id` | identity collision (api/worker/migrator, old/new task) |
| `RESOURCE-ATTRS-DIFFER` | same service id, different resource attributes | two resources that collapse to one Prometheus series |
| `NAMES-COLLIDE-AFTER-SANITISING` | `a.b` and `a_b` are one Prometheus name | two instruments that differ only by `.` vs `_` |
| `ATTRS-COLLAPSE-IN-TRANSLATION` | datapoints that differ in OTLP attributes are one Prometheus series | an attribute is lost in the OTLP-to-Prometheus translation |
| `OVERRIDDEN-BY-RESOURCE(job)` / `(instance)` | the instrument records an attribute named `job` or `instance`; Grafana replaces it with `service.namespace/service.name` / `service.instance.id` | rename the attribute (this was the cause in 2026-10: `JobMetrics` recorded `job`) |
| `across-batches` + `same-task` | the same task exported the point in two batches | the batch/export interval overlaps itself, or retry after a timeout |

## 6. Turn it off

Do not leave it on. Open a PR that deletes the `debug_metrics = true` line (and its comment) in
`infra/live/develop/main.tf` of rova and opshub, merge and apply. Prod never had it.
The sidecar returns to its previous config byte for byte (`debug_metrics = false` renders an identical config).

Then delete the local `dump-*.json` and `report-*.txt`; they hold application data. The CloudWatch streams age out
with the log group's retention.
