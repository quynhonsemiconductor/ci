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
| `frontend`   | rova web, qnsc-kb-frontend, qnsc-landing, ceo-suite     |

A caller may name several: `profiles: typescript,frontend,sql,dockerfile,workflows`.

`frontend` exists because there is no accessibility linter in the web applications and roughly fifty
UI files write `aria` attributes by hand, so review is the only guard on it.

## Where the built-ins already cover us

`ts/js/tsx/jsx`, `python`, `terraform`, `astro`, `go`, `package.json`, `json`, `yaml`,
`.github/workflows`, and Verilog/VHDL among others. `sql`, `Dockerfile` and `dart` have **no**
built-in rules, which is why those three profiles carry more of the basics than the rest.

## Choosing the model

The reviewer is provider-agnostic; the tool ships around thirty providers. Two shapes matter.

Anthropic is the default and needs nothing:

```yaml
with:
  product: rova
  profiles: typescript,sql
secrets:
  llm_token: ${{ secrets.ANTHROPIC_API_KEY }}
```

GLM speaks the OpenAI protocol rather than Anthropic's, so it needs three overrides. Sending an
Anthropic-shaped request to a GLM endpoint fails on the request body, which does not name the cause:

```yaml
with:
  product: rova
  profiles: typescript,sql
  llm_url: https://open.bigmodel.cn/api/paas/v4   # coding plan: .../api/coding/paas/v4
  use_anthropic_protocol: 'false'
  llm_extra_body: '{}'                            # the default disables Anthropic thinking
  model: glm-5.2                                  # glm-5.3, 5.2, 5.1, 5, 5-turbo are recognised
secrets:
  llm_token: ${{ secrets.Z_AI_API_KEY }}
```

Rules are prompts, not a DSL, so a weaker model produces weaker review rather than an error. Worth
comparing the two on the same pull request before standardising on either.

## Cost, and why these files are short

Only the FIRST matching rule is sent for a file, and the base text is folded into it — so the base
file is a multiplier paid on every reviewed file, not a one-off. It was 5,955 characters and is now
1,949, which halved the per-file rule cost:

| profile     | before      | after       |
| ----------- | ----------- | ----------- |
| typescript  | ~2,036 tok  | ~1,034 tok  |
| frontend    | ~2,544 tok  | ~1,077 tok  |
| sql         | ~2,043 tok  | ~1,042 tok  |
| terraform   | ~1,709 tok  | ~707 tok    |

The saving came from deleting, not compressing. Gone: hardcoding, secrets-in-code, dependency
review and pull request titles — the built-in rules cover the first two, `osv-scanner` and Renovate
the third, and a required check already enforces the fourth. A rule that repeats another guard costs
tokens on every file and changes no outcome.

This is also a quality argument, not only a cost one. The tool's own design states that matching
rules narrowly exists to eliminate noise and keep the model's attention focused; a long rule file
works against the thing that makes its precision better than a general-purpose agent's. Fewer, sharper
rules produce fewer confident-sounding findings about things nobody asked about.

`max_tokens_budget` on the workflow is the hard ceiling — a run cannot exceed it, and skipped files
are reported rather than silently dropped.

## Editing

Keep a rule specific enough to be actionable and short enough to read, and treat adding one as
spending tokens on every future review of every matching file.

Two questions before adding anything: does a built-in rule, a linter or a required check already
cover it, and would a competent reviewer who had never seen this codebase know it? If the answer to
either is yes, leave it out. Prefer naming the failure that
prompted the rule — a reviewer given the reason reports the problem rather than the pattern.
