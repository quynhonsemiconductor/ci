# Code review rules

Rule files for `quynhonsemiconductor/code-review` (our fork of `alibaba/open-code-review`).

## How they combine

`base.json` is merged with one profile by the `code-review.yml` reusable workflow, so a caller
names a profile and gets the org-wide rules for free. The merge is a concatenation of the `rules`
arrays; there is no include mechanism in the format itself.

Every rule sets `merge_system_rule: true`, which keeps the tool's built-in rules in play. Those
already cover hardcoding, magic values, dead code, null handling, React hook misuse, mutable
default arguments and the usual security checks across 52 file patterns. Repeating them here would
add maintenance and lengthen the prompt for no gain.

What belongs in these files is only what a general-purpose reviewer cannot infer: our layering,
our release mechanics, and the specific mistakes this organisation has already made.

## Profiles

| Profile      | For                                                    |
| ------------ | ------------------------------------------------------ |
| `typescript` | rova, opshub, mcp-tools, app-platform, qnsc-kb-frontend |
| `python`     | qnsc-kb-backend, agent-forge, ci                        |
| `terraform`  | infra, tf-modules, infra-template, 9router-pool          |
| `sql`        | any repo with numbered migrations (rova has 133)        |
| `dockerfile` | any repo shipping an image                              |
| `dart`       | solodesk                                                |
| `workflows`  | any repo; pair with another profile                     |

A caller may name several: `profiles: typescript,sql,dockerfile,workflows`.

## Where the built-ins already cover us

`ts/js/tsx/jsx`, `python`, `terraform`, `astro`, `go`, `package.json`, `json`, `yaml`,
`.github/workflows`, and Verilog/VHDL among others. `sql`, `Dockerfile` and `dart` have **no**
built-in rules, which is why those three profiles carry more of the basics than the rest.

## Editing

Keep a rule specific enough to be actionable and short enough to read. A rule that restates a
built-in one costs tokens on every review and changes no outcome. Prefer naming the failure that
prompted the rule — a reviewer given the reason reports the problem rather than the pattern.
