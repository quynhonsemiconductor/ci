#!/usr/bin/env python3
"""Decide whether the AI code review should run, and say honestly what it did.

Used by `.github/workflows/code-review.yml`. Five subcommands, one per question:

  scope     Is this pull request dependency-only? Then the reviewer has nothing to
            say, and reading a 13,000-line lockfile is how a 3-file bump spent
            509,506 tokens against a 400,000 budget (rova#652).
  size      Is it too large to re-review on every push? Measured with OCR's own
            `--preview` (no model call), so excludes count exactly as OCR applies them.
  tier      Will the budget NOT cover everything? Then keep the high-risk files
            and exclude the rest, so what runs out of budget is the low-risk
            tail, not whatever sorts first alphabetically.
  probe     Can the model be reached right now? One tiny request, read for the
            provider's own error code, BEFORE the review fans out.
  verdict   What actually happened? Turns the OCR result file into one sentence
            for the pull request and decides whether the job fails.

── WHY A PROBE ──────────────────────────────────────────────────────────────

On 2026-10-06 every review in the organisation failed with HTTP 429: a 75-file
pull request made 630 attempts in four minutes and reported "check your LLM
configuration and API key". The key was valid. OCR records the status code but
never the body, and the body is where Z.AI says WHICH 429 it is — 1302 (slow
down), 1308/1310 (quota spent, resets at a stated time), 1113/1309 (no balance,
plan expired). Those need different responses, and none of them is something
the pull request's author caused.

── WHY THE VERDICT LOOKS AT COVERAGE ────────────────────────────────────────

Every review of a pull request beyond a handful of files was PARTIAL: rova#653
had 12–19 of 75 files reviewed per run, the rest stopped by the token budget,
while the check was green and the comment said "found nothing blocking". A
partial review must say it is partial and name what it did not read.

── WHAT FAILS THE JOB ───────────────────────────────────────────────────────

Only what a person has to fix: the provider rejecting the key or plan, or the
reviewer crashing. A spent quota or a partial review is a warning — red for a
reason the author cannot act on teaches everyone to ignore red.

Every decision here fails OPEN towards reviewing: a question that cannot be
answered with evidence leaves the review running exactly as it would without
this script.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import PurePosixPath

MARKER = "<!-- qnsc-review-verdict -->"

# ── scope ─────────────────────────────────────────────────────────────────────

# Machine-written; a change to these alone is dependency-only.
LOCKFILES = {
    "pnpm-lock.yaml", "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "bun.lockb", "poetry.lock", "uv.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    "pubspec.lock", ".terraform.lock.hcl", "composer.lock", "Gemfile.lock",
}

# Hand-edited manifests: dependency-only when every changed line is a version
# specifier, a section key or a comment. `"postinstall": "curl … | sh"` is a
# quoted string too, which is why the VALUE must look like a version.
MANIFESTS = {
    "package.json", "pnpm-workspace.yaml", "go.mod", "Cargo.toml", "pubspec.yaml",
    ".nvmrc", ".node-version", ".python-version",
}
MANIFEST_GLOBS = ("requirements*.txt",)

_SPEC = r"(?:[\^~<>=!*]*\s*v?\d[\w.\-+*]*|(?:workspace|catalog|npm|jsr):[^\s\"']*)"
_SPECS = rf"{_SPEC}(?:\s*(?:\|\||,)?\s*{_SPEC})*"
_KEY = r"[\"']?[@\w./\-<>=^~*| ]+[\"']?"
_OP = r"(?:==|>=|<=|~=|!=|>|<)"
VERSION_LINE = [
    re.compile(rf"^\s*{_KEY}\s*:\s*[\"']{_SPECS}[\"']\s*,?\s*$"),          # "pkg": "^1.2.3",
    re.compile(rf"^\s*{_KEY}\s*:\s*{_SPECS}\s*$"),                         # pkg: 1.2.3
    re.compile(r"^\s*\"packageManager\"\s*:\s*\"[\w-]+@\d[\w.\-+]*\"\s*,?\s*$"),
    re.compile(rf"^\s*[\w.\-\[\]]+\s*{_OP}\s*{_SPEC}(?:\s*,\s*{_OP}\s*{_SPEC})*\s*$"),  # pip
    re.compile(r"^\s*(?:require\s+)?[\w.\-/]+\s+v\d[\w.\-+]*(?:\s*//\s*indirect)?\s*$"),  # go.mod
    re.compile(r"^\s*v?\d[\w.\-+]*\s*$"),                                  # .nvmrc
    re.compile(r"^\s*[\"']?[\w-]+[\"']?\s*:\s*[{\[]?\s*$"),                # `overrides:`
    re.compile(r"^\s*[}\]],?\s*$"),
    re.compile(r"^\s*(?:#|//).*$"),
    re.compile(r"^\s*$"),
]


def _is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in LOCKFILES


def _is_manifest(path: str) -> bool:
    name = PurePosixPath(path).name
    return name in MANIFESTS or any(fnmatch.fnmatch(name, g) for g in MANIFEST_GLOBS)


def _changed_lines(patch: str) -> list[str]:
    return [line[1:] for line in patch.splitlines()
            if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def classify_files(files: list[dict]) -> tuple[bool, str]:
    """(dependency_only, reason). Any doubt — no files, a missing patch — reviews."""
    if not files:
        return False, "no changed files listed"
    for f in files:
        path = f.get("filename", "")
        if _is_lockfile(path):
            continue
        if not _is_manifest(path):
            return False, f"{path} is not a dependency file"
        patch = f.get("patch")
        if patch is None:
            # GitHub omits the patch for large diffs: nothing to prove it with.
            return False, f"{path} has no patch to inspect"
        for line in _changed_lines(patch):
            if not any(p.match(line) for p in VERSION_LINE):
                return False, f"{path} changes more than versions: {line.strip()[:80]}"
    return True, f"{len(files)} file(s), lockfiles and version specifiers only"


def read_json_lines(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def cmd_scope(args) -> int:
    try:
        files = read_json_lines(args.files)
    except (OSError, ValueError) as exc:
        print(f"::warning::could not read the changed-file list ({exc}); reviewing")
        files = []
    dep_only, reason = classify_files(files)
    print(f"dependency_only={str(dep_only).lower()}: {reason}")
    write_outputs({"dependency_only": str(dep_only).lower(), "scope_reason": reason})
    return 0


# ── size ──────────────────────────────────────────────────────────────────────

# The events that ask for a fresh look at the whole pull request.
FRESH_LOOK = {"opened", "reopened", "ready_for_review"}


def measure(preview: dict) -> tuple[int, int]:
    """(files, changed lines) OCR will actually review, from `ocr review --preview`."""
    files = [f for f in preview.get("files") or [] if f.get("will_review")]
    return len(files), sum(int(f.get("insertions") or 0) + int(f.get("deletions") or 0)
                           for f in files)


def size_decision(preview: dict | None, threshold: int, action: str) -> dict[str, str]:
    if preview is None:
        # No preview, no evidence: review exactly as without this gate.
        return {"reviewable": "", "review_lines": "", "large": "false", "defer": "false"}
    files, lines = measure(preview)
    large = threshold > 0 and lines > threshold
    return {"reviewable": str(files), "review_lines": str(lines), "large": str(large).lower(),
            "defer": str(large and action not in FRESH_LOOK).lower()}


def cmd_size(args) -> int:
    try:
        with open(args.preview, encoding="utf-8") as fh:
            preview = json.load(fh)
        if not isinstance(preview, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        print(f"::warning::could not read the review preview ({exc}); reviewing without a size check")
        preview = None
    out = size_decision(preview, _int(os.environ.get("LARGE_PR_LINES")),
                        os.environ.get("EVENT_ACTION", ""))
    print(" ".join(f"{k}={v}" for k, v in out.items()))
    write_outputs(out)
    return 0


# ── tier ──────────────────────────────────────────────────────────────────────

# OCR dispatches file groups in the order its grouping produces and stops at the
# token budget; what that leaves unread is arbitrary (rova#821: 20 of 30 files
# reviewed, the merge stopping in the middle of `apps/web/src/pages/guide/...`
# while `functions/_lib/guide-gate.ts` — where the run's only security finding
# sat — never got a turn). This pass is deterministic and free: rank the
# reviewable files by path, and when the budget cannot cover everything, shrink
# the review to the higher-risk end so whatever goes unread is the low-risk tail.
#
# Three tiers, because "high-risk" and "everything else" is too coarse: ordinary
# source code is worth more model attention than data and config, but less than
# the paths where a defect is a security incident.
HIGH_RISK = [
    "functions/**",          # edge/pages functions run at the trust boundary
    "**/functions/**",
    "**/auth/**",
    "**/session/**",
    ".github/workflows/**",  # CI/CD is the org's supply chain
    "**/migrations/**",      # schema changes are one-way doors
    "**/*.sql",
    "**/Dockerfile*",
    "Dockerfile*",
    "**/*.Dockerfile",
    "**/*.tf",               # IaC
    "**/*.tfvars",
    "**/*.tofu",
]

CODE_EXTS = {
    ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue",
    ".svelte", ".astro", ".py", ".pyi", ".go", ".rs", ".java", ".kt", ".kts",
    ".swift", ".dart", ".php", ".rb", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp",
    ".sh", ".bash", ".ps1",
}

# Mirror of OCR's own pre-run estimate (internal/agent/estimate.go), which is a
# FLOOR: per changed-diff token count T (chars/4, conservative for GLM's
# tokenizer), 8 passes over the diff+overhead plus fixed per-file output.
PER_FILE_FIXED_TOKENS = 8 * 2000 + 400 + 7 * 700
DIFF_PASSES = 8  # 1 (plan) + avgMainRoundsPerFile (7) input re-sends
CHARS_PER_TOKEN = 4

GLOB_SPECIAL = set("*?[]!\\")


def glob_match(path: str, pattern: str) -> bool:
    """gitignore-style `**` semantics via fnmatch: a `**/` segment also matches
    zero directories, matching the doublestar engine OCR uses."""
    candidates = {pattern}
    if pattern.startswith("**/"):
        candidates.add(pattern[3:])
    candidates.add(pattern.replace("/**/", "/"))
    return any(fnmatch.fnmatch(path, c) for c in candidates)


def file_tier(path: str) -> str:
    if any(glob_match(path, p) for p in HIGH_RISK):
        return "high"
    if PurePosixPath(path).suffix.lower() in CODE_EXTS:
        return "code"
    return "low"


def estimate_file_tokens(diff_chars: int) -> int:
    diff_tokens = diff_chars // CHARS_PER_TOKEN
    return diff_tokens * DIFF_PASSES + PER_FILE_FIXED_TOKENS


def diff_char_counts(from_ref: str, to_ref: str, paths: list[str]) -> dict[str, int]:
    """Characters of unified diff per path, measured from git itself so the
    estimate tracks what the model will actually be shown."""
    counts: dict[str, int] = {}
    for path in paths:
        try:
            proc = subprocess.run(["git", "diff", "--no-color", "--no-ext-diff",
                                   from_ref, to_ref, "--", path],
                                  capture_output=True, text=True)
        except OSError:
            break  # no git at all: no estimate, so no tiering (fail open)
        if proc.returncode == 0:
            counts[path] = len(proc.stdout)
    return counts


def tier_decision(preview: dict | None, budget: int, counts: dict[str, int]) -> dict:
    """Pick which tiers to keep. Fail-open everywhere: no preview, no usable
    estimate or an empty keep-set means no tiering, and the review runs exactly
    as it would without this pass."""
    out = {"tiered": "none", "excludes": [], "skipped": [], "estimate_all": 0,
           "estimate_keep": 0}
    if preview is None or budget <= 0:
        return out
    files = [f.get("path", "") for f in preview.get("files") or [] if f.get("will_review")]
    files = [f for f in files if f]
    if not files:
        return out
    # A path whose estimate cannot be measured must not be excluded on a guess.
    measurable = [f for f in files if f in counts]
    if not measurable:
        return out
    est = {f: estimate_file_tokens(counts[f]) for f in measurable}
    est_all = sum(est[f] for f in measurable)
    out["estimate_all"] = est_all
    if est_all <= budget:
        return out  # everything fits: no tiering, full coverage

    by_tier: dict[str, list[str]] = {"high": [], "code": [], "low": []}
    for f in measurable:
        by_tier[file_tier(f)].append(f)

    def safe_pattern(path: str) -> str | None:
        # An exact path only works as a gitignore pattern if it carries no glob
        # metacharacters; anything else stays reviewed rather than mis-excluded.
        return None if GLOB_SPECIAL & set(path) else path

    def keep(tiers: list[str]) -> tuple[list[str], list[str], int]:
        kept = [f for t in tiers for f in by_tier[t]]
        skipped = [f for f in measurable if f not in set(kept)]
        return kept, skipped, sum(est[f] for f in kept)

    # Deepest exclusion worth attempting: drop the low tier, then the code tier
    # too. The last level with a non-empty keep-set wins even if its estimate
    # still overflows — a soft budget spent on code beats one spent on data.
    best: tuple[str, list[str], int] | None = None
    for level, tiers in (("low", ["high", "code"]), ("code", ["high"])):
        kept, skipped, est_keep = keep(tiers)
        if not kept:
            break  # no higher tier to protect: fail open, review as before
        best = (level, skipped, est_keep)
        if est_keep <= budget:
            break
    if best is None:
        return out
    out["tiered"], out["skipped"], out["estimate_keep"] = best
    patterns = [p for p in (safe_pattern(f) for f in out["skipped"]) if p]
    if len(patterns) != len(out["skipped"]):
        # A path we cannot safely exclude stays in the review; keep coverage
        # honest by also keeping it out of the "skipped" list.
        excluded = set(patterns)
        out["skipped"] = [f for f in out["skipped"] if f in excluded]
    if not patterns:
        out["tiered"] = "none"  # nothing could be safely excluded: fail open
        out["skipped"] = []
    out["excludes"] = patterns
    return out


def cmd_tier(args) -> int:
    try:
        with open(args.preview, encoding="utf-8") as fh:
            preview = json.load(fh)
        if not isinstance(preview, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        print(f"::warning::could not read the review preview ({exc}); no risk tiering")
        preview = None
    budget = _int(os.environ.get("MAX_TOKENS_BUDGET"))
    decision = tier_decision(preview, budget,
                             diff_char_counts(args.from_ref, args.to_ref,
                                              [f.get("path", "") for f in (preview or {}).get("files") or []
                                               if f.get("will_review")]) if preview else {})
    level = decision["tiered"]
    print(f"tiered={level} est_all={decision['estimate_all']:,} "
          f"est_keep={decision['estimate_keep']:,} budget={budget:,} "
          f"skipped={len(decision['skipped'])}")

    skipped_file = args.skipped_out
    with open(skipped_file, "w", encoding="utf-8") as fh:
        fh.write("\n".join(decision["skipped"]))

    if level != "none" and decision["excludes"]:
        rule_file = os.environ.get("QNSC_RULE_FILE", "")
        try:
            with open(rule_file, encoding="utf-8") as fh:
                doc = json.load(fh)
            doc["exclude"] = list(dict.fromkeys(doc.get("exclude", []) + decision["excludes"]))
            tier_file = rule_file.replace(".json", ".tier.json")
            with open(tier_file, "w", encoding="utf-8") as fh:
                json.dump(doc, fh, indent=2, ensure_ascii=False)
            if env_file := os.environ.get("GITHUB_ENV"):
                with open(env_file, "a", encoding="utf-8") as fh:
                    fh.write(f"QNSC_RULE_FILE={tier_file}\n")
            print(f"rule file for this run: {tier_file} "
                  f"(+{len(decision['excludes'])} low-risk exclude(s))")
        except (OSError, ValueError) as exc:
            print(f"::warning::could not write the tiered rule file ({exc}); reviewing un-tiered")
    write_outputs({"tiered": level,
                   "tier_skipped_count": str(len(decision["skipped"]))})
    return 0


# ── probe ─────────────────────────────────────────────────────────────────────

# Z.AI business codes (https://docs.z.ai/api-reference/api-code), as strings.
ZAI_QUOTA = {"1308", "1310", "1316", "1317", "1318", "1319", "1320", "1321"}
ZAI_TRANSIENT = {"1302", "1305"}
ZAI_ACCOUNT = {"1000", "1001", "1002", "1003", "1004", "1005", "1113", "1211",
               "1220", "1309", "1311", "1313", "1314", "1315"}


@dataclass
class ProbeResult:
    status: str          # ok | unavailable | config | unknown
    code: str = ""
    message: str = ""


def _provider_error(body: bytes) -> tuple[str, str]:
    text = body.decode("utf-8", "replace")
    try:
        doc = json.loads(text)
    except ValueError:
        return "", text[:300]
    if not isinstance(doc, dict):
        return "", ""
    err = doc.get("error")
    if isinstance(err, dict):
        return str(err.get("code") or err.get("type") or ""), str(err.get("message") or "")
    return str(doc.get("code") or ""), str(doc.get("message") or doc.get("msg") or "")


def classify_http(status: int, body: bytes) -> tuple[str, str, str]:
    """(verdict, code, message). verdict: ok | unavailable | config | retry | unknown."""
    if 200 <= status < 300:
        return "ok", "", ""
    code, message = _provider_error(body)
    shown = code or str(status)
    if code in ZAI_QUOTA or code == "insufficient_quota":
        return "unavailable", shown, message
    if code in ZAI_ACCOUNT or status in (401, 403):
        return "config", shown, message
    if code in ZAI_TRANSIENT or status in (429, 500, 502, 503, 504, 529):
        return "retry", shown, message
    # A 400 on this tiny request says nothing reliable about the real one.
    return "unknown", shown, message


def build_request(url: str, token: str, model: str, anthropic: bool,
                  extra_body: str) -> urllib.request.Request:
    try:
        extra = json.loads(extra_body) if extra_body.strip() else {}
    except ValueError:
        extra = {}
    body = {"model": model, "max_tokens": 16,
            "messages": [{"role": "user", "content": "Reply with: ok"}]}
    if anthropic:
        headers = {"x-api-key": token, "anthropic-version": "2023-06-01"}
        target = url
    else:
        headers = {"Authorization": f"Bearer {token}"}
        target = url.rstrip("/") + "/chat/completions"
        body["stream"] = False
    # Same extra body as the real request, so one the provider rejects shows here.
    if isinstance(extra, dict):
        body.update(extra)
    headers["Content-Type"] = "application/json"
    return urllib.request.Request(target, data=json.dumps(body).encode(), headers=headers,
                                  method="POST")


def probe(url: str, token: str, model: str, anthropic: bool, extra_body: str,
          delays: list[float], timeout: float = 90.0) -> ProbeResult:
    last = ProbeResult("unknown")
    for attempt in range(len(delays) + 1):
        try:
            req = build_request(url, token, model, anthropic, extra_body)
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - caller's endpoint
                verdict, code, message = classify_http(resp.status, resp.read())
        except urllib.error.HTTPError as exc:
            verdict, code, message = classify_http(exc.code, exc.read() or b"")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            verdict, code, message = "network", "", str(exc)
        if verdict == "ok":
            return ProbeResult("ok")
        if verdict in ("unavailable", "config", "unknown"):
            return ProbeResult(verdict, code, message)
        # Rate limited, overloaded or unreachable: retry, then decide. A network
        # error stays `unknown` so the review still gets its own chance.
        last = ProbeResult("unavailable" if verdict == "retry" else "unknown", code, message)
        if attempt < len(delays):
            time.sleep(delays[attempt])
    return last


def cmd_probe(_args) -> int:
    token, url = os.environ.get("LLM_TOKEN", ""), os.environ.get("LLM_URL", "")
    if not token or not url:
        write_outputs({"probe": "unknown", "probe_code": "", "probe_message": "no url or token"})
        return 0
    # Same rule as the action: empty, true, 1 or yes selects Anthropic.
    anthropic = os.environ.get("USE_ANTHROPIC", "").strip().lower() in ("", "true", "1", "yes")
    delays = [float(d) for d in os.environ.get("PROBE_DELAYS", "15,45").split(",") if d.strip()]
    result = probe(url, token, os.environ.get("LLM_MODEL", ""), anthropic,
                   os.environ.get("EXTRA_BODY", "{}"), delays,
                   float(os.environ.get("PROBE_TIMEOUT", "90")))
    message = one_line(result.message)
    print(f"probe={result.status} code={result.code or '-'} {message}")
    write_outputs({"probe": result.status, "probe_code": result.code, "probe_message": message})
    return 0


# ── verdict ───────────────────────────────────────────────────────────────────

@dataclass
class Coverage:
    selected: int = 0
    reviewed: int = 0
    failed: dict[str, list[str]] = field(default_factory=dict)  # classification -> paths
    tokens: int = 0
    elapsed: str = ""
    rate_limited: int = 0

    @property
    def failed_count(self) -> int:
        return sum(len(v) for v in self.failed.values())


def read_coverage(path: str) -> Coverage | None:
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or "manifest" not in doc:
        return None
    cov = (doc.get("manifest") or {}).get("coverage") or {}
    failed: dict[str, list[str]] = {}
    for item in cov.get("failed") or []:
        failed.setdefault(item.get("classification") or "unknown", []).append(item.get("path", "?"))
    summary = doc.get("summary") or {}
    attempts = [a for r in (doc.get("retry_report") or {}).get("requests") or []
                for a in r.get("attempts") or []]
    return Coverage(
        selected=len(cov.get("selected") or []),
        reviewed=len(cov.get("completed") or []) + len(cov.get("reused") or []),
        failed=failed,
        tokens=int(summary.get("total_tokens") or 0),
        elapsed=str(summary.get("elapsed") or ""),
        rate_limited=sum(1 for a in attempts if a.get("status_code") == 429),
    )


def one_line(text: str, limit: int = 300) -> str:
    """Provider text is untrusted: one line, no backticks, bounded."""
    flat = " ".join((text or "").split()).replace("`", "'")
    return flat[:limit] + ("…" if len(flat) > limit else "")


def _int(value: str | None) -> int:
    try:
        return int(value or 0)
    except ValueError:
        return 0


@dataclass
class Verdict:
    state: str   # skipped | deferred | unchanged | unavailable | config | error | partial | complete
    fail: bool
    body: str
    stats: str = ""


RERUN = ("Nothing was recorded as reviewed, so the next push reviews everything since the last "
         "complete review — or re-run this workflow once the limit resets.")


def decide(env: dict[str, str], cov: Coverage | None) -> Verdict:
    if env.get("DEPENDENCY_ONLY") == "true":
        return Verdict("skipped", False,
                       "ℹ️ **QNSC code review skipped: dependency-only change.** Only lockfiles and "
                       "version specifiers changed; that risk is covered by osv-scanner, Semgrep and "
                       "Renovate's `minimumReleaseAge`, not by this reviewer.")

    if env.get("REVIEWABLE") == "0":
        return Verdict("skipped", False,
                       "ℹ️ **QNSC code review skipped: nothing reviewable changed.** Every changed "
                       "file is documentation, a test, generated or excluded by the profile rules.")

    if env.get("DEFER") == "true":
        return Verdict("deferred", False,
                       "ℹ️ **QNSC code review not re-run for this push: large pull request** "
                       f"({env.get('REVIEWABLE', '?')} reviewable file(s), "
                       f"{_int(env.get('REVIEW_LINES')):,} changed lines). A change this size does "
                       "not fit one review's budget, so the review cannot complete, cannot record a "
                       "checkpoint, and every push would pay for the same partial review again. It "
                       "is reviewed when the pull request is opened, reopened or marked ready for "
                       "review; findings from that review stand. To get a fresh review, convert to "
                       "draft and mark it ready again — or, better, split it.")

    said = one_line(": ".join(x for x in (env.get("PROBE_CODE"), env.get("PROBE_MESSAGE")) if x))
    if env.get("PROBE") == "unavailable":
        return Verdict("unavailable", False,
                       "⏸️ **QNSC code review did not run: the model provider is out of capacity** "
                       f"(`{said or 'rate limited'}`). This is not a finding about the code. {RERUN}")
    if env.get("PROBE") == "config":
        return Verdict("config", True,
                       "❌ **QNSC code review cannot run: the model provider rejected the key or "
                       f"plan** (`{said or 'unauthorised'}`). Not a finding about the code — the "
                       "platform team needs to fix the `llm_token` secret or the plan.")

    if env.get("RANGE_REASON") == "same_head_noop":
        # A re-run on the head the last complete review covered: OCR reviewed an empty range and the
        # action leaves its summary alone. So does this — the verdict already posted is still true.
        return Verdict("unchanged", False, "")

    if cov is None:
        return Verdict("error", True,
                       f"⚠️ **QNSC code review did not finish** (`{env.get('REVIEW_OUTCOME') or 'no result'}`). "
                       "Nothing here should be read as approval — the absence of findings is the "
                       "absence of a review, not a clean result.")

    stats = (f"{cov.reviewed}/{cov.selected} file(s) reviewed · {cov.tokens:,} tokens · "
             f"{cov.elapsed or '?'}")
    if cov.selected and cov.reviewed == 0:
        classes = set(cov.failed)
        if classes <= {"provider"}:
            return Verdict("unavailable", False,
                           "⏸️ **QNSC code review did not run: the model provider refused every "
                           f"request** ({cov.rate_limited} HTTP 429 responses). This is not a "
                           f"finding about the code. {RERUN}", stats)
        if classes != {"budget"}:
            return Verdict("error", True,
                           f"⚠️ **QNSC code review did not finish**: all {cov.selected} file(s) "
                           f"failed ({', '.join(sorted(classes))}). Nothing here should be read as "
                           "approval.", stats)

    rng = env.get("RANGE") or "full"
    total, inline = _int(env.get("TOTAL")), _int(env.get("INLINE"))
    failed_posts, routed = _int(env.get("FAILED")), _int(env.get("ROUTED"))

    if cov.failed_count:
        reasons = ", ".join(f"{k}: {len(v)}" for k, v in sorted(cov.failed.items()))
        missed = sorted(p for paths in cov.failed.values() for p in paths)
        listed = "\n".join(f"- `{p}`" for p in missed[:25])
        if len(missed) > 25:
            listed += f"\n- …and {len(missed) - 25} more"
        threads = f" {inline} thread(s) need an answer before merge." if inline else ""
        hint = (" The change does not fit the token budget: split the pull request, or ask the "
                "platform team for a larger `max_tokens_budget`." if "budget" in cov.failed else "")
        return Verdict("partial", False,
                       f"⚠️ **QNSC code review is partial: {cov.reviewed} of {cov.selected} "
                       f"file(s) reviewed** ({reasons}). Findings cover the reviewed files only — "
                       f"the rest were not read, so this is not a clean result.{threads}{hint}\n\n"
                       f"<details><summary>Not reviewed</summary>\n\n{listed}\n\n</details>", stats)

    if failed_posts:
        body = (f"⚠️ **QNSC code review finished, but {failed_posts} comment(s) failed to post.** "
                f"Findings may be missing from this pull request. Range reviewed: `{rng}`.")
    elif inline == 0:
        body = ("✅ **QNSC code review found nothing blocking.** Nothing needs resolving before "
                f"merge.\n\nReviewed: `{rng}`. {total} finding(s) in total, {routed} of them "
                "advisory and collected in the summary comment above rather than as threads.")
    else:
        body = (f"🔎 **QNSC code review opened {inline} thread(s) that need an answer before "
                f"merge.**\n\nReviewed: `{rng}`. Resolving a thread with a reply explaining why a "
                "finding is wrong is a valid answer — the reply is the record.")
    return Verdict("complete", False, body, stats)


def cmd_verdict(args) -> int:
    env = dict(os.environ)
    cov = read_coverage(args.result) if env.get("REVIEW_RAN") == "true" else None
    v = decide(env, cov)
    # Files the tier pass deliberately left out so the budget reached the
    # higher-risk paths. Named in the verdict because "complete" would otherwise
    # read as "everything was read".
    if v.body and args.tier_skipped and os.path.exists(args.tier_skipped):
        with open(args.tier_skipped, encoding="utf-8") as fh:
            paths = [line for line in fh.read().splitlines() if line]
        if paths:
            listed = "\n".join(f"- `{p}`" for p in paths[:25])
            if len(paths) > 25:
                listed += f"\n- …and {len(paths) - 25} more"
            v.body += ("\n\n<details><summary>Deliberately not reviewed — low-risk tier, "
                       "budget held for higher-risk paths</summary>\n\n"
                       "Prose, data and config paths, ranked below the code this run "
                       f"did read:\n\n{listed}\n\n</details>")
    body = "" if not v.body else (
        f"{MARKER}\n{v.body}" + (f"\n\n<sub>{v.stats}</sub>" if v.stats else ""))
    with open(args.body_out, "w", encoding="utf-8") as fh:
        fh.write(body)
    level = {"config": "error", "error": "error",
             "unavailable": "warning", "partial": "warning"}.get(v.state)
    if level:
        print(f"::{level}::{re.sub(r'[*`]', '', v.body.split(chr(10), 1)[0])}")
    print(f"state={v.state} fail={str(v.fail).lower()} {v.stats}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### Code review: {v.state}\n\n{v.body}\n\n{v.stats}\n")
    write_outputs({"state": v.state, "fail": str(v.fail).lower()})
    return 0


# ── plumbing ──────────────────────────────────────────────────────────────────

def write_outputs(values: dict[str, str]) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for key, value in values.items():
            fh.write(f"{key}={one_line(value, 1000)}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QNSC code-review gate")
    sub = parser.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scope", help="is this pull request dependency-only?")
    s.add_argument("--files", required=True, help="JSON lines, one {filename, patch} per file")
    s.set_defaults(func=cmd_scope)
    z = sub.add_parser("size", help="is this pull request too large to re-review per push?")
    z.add_argument("--preview", required=True, help="output of `ocr review --preview --format json`")
    z.set_defaults(func=cmd_size)
    t = sub.add_parser("tier", help="will the budget not cover everything? keep the high-risk files")
    t.add_argument("--preview", required=True, help="output of `ocr review --preview --format json`")
    t.add_argument("--from", dest="from_ref", required=True, help="merge-base ref to diff from")
    t.add_argument("--to", dest="to_ref", required=True, help="head ref to diff to")
    t.add_argument("--skipped-out", required=True, help="where to write the not-reviewed list")
    t.set_defaults(func=cmd_tier)
    sub.add_parser("probe", help="can the model be reached?").set_defaults(func=cmd_probe)
    v = sub.add_parser("verdict", help="what did the review actually cover?")
    v.add_argument("--result", default="/tmp/ocr-result.json")
    v.add_argument("--body-out", required=True)
    v.add_argument("--tier-skipped", default="",
                   help="file listing paths the tier pass excluded (optional)")
    v.set_defaults(func=cmd_verdict)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
