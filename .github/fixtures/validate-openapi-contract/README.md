Fixtures for `.github/workflows/validate-openapi-contract-test.yml`. Every file is a tiny OpenAPI 3.0 document;
none is a real product spec. All pairs compare against a base:

| Pair | oasdiff says | Expected result of the action |
|---|---|---|
| `base.json` -> `breaking.json` | 2 ERR `response-success-status-removed`: POST `/v1/compliance/shadow-it/scan` 200 and POST `/v1/security-posture/sync` 201 (the opshub#354 case) | fails |
| `base.json` -> `compatible.json` | only INFO (a media type and an endpoint were added) | passes |
| `base-warn.json` -> `warning.json` | 1 WARN `response-optional-property-removed` | passes, nothing breaking |
| `base.json` -> `invalid.json` | cannot load (exit 102) | fails, whatever the inputs |
| `with-config/base.json` -> `with-config/breaking.json` | the same ERR pair, next to a `.oasdiff.yaml` with `unmatch-path: ".*"` that would make oasdiff report nothing | fails: the action refuses to run beside an oasdiff config |

The "config in the workspace root" case plants the same `.oasdiff.yaml` at run time, in the checkout's root.
