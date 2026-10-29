# Changelog

## [1.27.0](https://github.com/quynhonsemiconductor/ci/compare/v1.26.0...v1.27.0) (2026-10-29)


### Features

* **leak-guard:** azure-subscription pattern, key-scoped allowlist entries ([#264](https://github.com/quynhonsemiconductor/ci/issues/264)) ([79a723e](https://github.com/quynhonsemiconductor/ci/commit/79a723e0e0687a2bbca10c0969bcb124811ef379))

## [1.26.0](https://github.com/quynhonsemiconductor/ci/compare/v1.25.0...v1.26.0) (2026-10-28)


### Features

* **leak-guard:** deterministic internal-name check for public repos ([#262](https://github.com/quynhonsemiconductor/ci/issues/262)) ([efc1e8c](https://github.com/quynhonsemiconductor/ci/commit/efc1e8cbbba794fcb5dce8d7ef6a9df7b0fc274e))

## [1.25.0](https://github.com/quynhonsemiconductor/ci/compare/v1.24.5...v1.25.0) (2026-10-28)


### Features

* **code-review:** default model glm-5.3, add llm_reasoning_effort, raise token budget ([#260](https://github.com/quynhonsemiconductor/ci/issues/260)) ([b746792](https://github.com/quynhonsemiconductor/ci/commit/b7467923610e710c04b7c226e993c73e0c6a51fa))

## [1.24.5](https://github.com/quynhonsemiconductor/ci/compare/v1.24.4...v1.24.5) (2026-10-27)


### Bug Fixes

* **iac-lint:** install the real tofu binary (tofu_wrapper: false) ([#258](https://github.com/quynhonsemiconductor/ci/issues/258)) ([3c06b98](https://github.com/quynhonsemiconductor/ci/commit/3c06b98bad283a2273b88b1e18889af567fd11f9))

## [1.24.4](https://github.com/quynhonsemiconductor/ci/compare/v1.24.3...v1.24.4) (2026-10-27)


### Bug Fixes

* **release:** cut this repo's releases with the qnsc-automation App token ([#255](https://github.com/quynhonsemiconductor/ci/issues/255)) ([0d5c605](https://github.com/quynhonsemiconductor/ci/commit/0d5c6052a84c9ef35df12949dc6b1e0cac19792a))

## [1.24.3](https://github.com/quynhonsemiconductor/ci/compare/v1.24.2...v1.24.3) (2026-10-26)


### Bug Fixes

* **deploy:** account ids come from vars, not secrets; drop the EKS workflows ([#252](https://github.com/quynhonsemiconductor/ci/issues/252)) ([c9d32d7](https://github.com/quynhonsemiconductor/ci/commit/c9d32d7a5be550d7ee807865e4c6ee6ac1d88476))
* **deploy:** drop the Slack deploy notifications ([#254](https://github.com/quynhonsemiconductor/ci/issues/254)) ([6dbfced](https://github.com/quynhonsemiconductor/ci/commit/6dbfced5d2f2500686c4e52ad354530caa9bf4e0))

## [1.24.2](https://github.com/quynhonsemiconductor/ci/compare/v1.24.1...v1.24.2) (2026-10-26)


### Bug Fixes

* **ci:** pin the wrangler the Pages deploy action installs ([#250](https://github.com/quynhonsemiconductor/ci/issues/250)) ([074e1b7](https://github.com/quynhonsemiconductor/ci/commit/074e1b7ab0a275ee3934a4e908d427aebf007d03))

## [1.24.1](https://github.com/quynhonsemiconductor/ci/compare/v1.24.0...v1.24.1) (2026-10-26)


### Bug Fixes

* **ci:** let setup-node-pnpm fall back to packageManager when no pnpm version is passed ([#247](https://github.com/quynhonsemiconductor/ci/issues/247)) ([3efe734](https://github.com/quynhonsemiconductor/ci/commit/3efe73447aba7297ea140cee6eb2ad6477eddae4))

## [1.24.0](https://github.com/quynhonsemiconductor/ci/compare/v1.23.1...v1.24.0) (2026-10-24)


### Features

* **build-push-ecr:** scan-scanners and labels inputs for pre-push scans ([#243](https://github.com/quynhonsemiconductor/ci/issues/243)) ([a6146a0](https://github.com/quynhonsemiconductor/ci/commit/a6146a0980d2d9329b4cbc8b9fcf41118700a261))
* **ci:** reusable ghcr-publish workflow (on-prem build path) ([#242](https://github.com/quynhonsemiconductor/ci/issues/242)) ([034964c](https://github.com/quynhonsemiconductor/ci/commit/034964c48e181ab2ccb13e09f2f7cec302e2bb33))

## [1.23.1](https://github.com/quynhonsemiconductor/ci/compare/v1.23.0...v1.23.1) (2026-10-22)


### Bug Fixes

* **infra-plan:** skip deleted stacks in detect-changes ([#239](https://github.com/quynhonsemiconductor/ci/issues/239)) ([8ee4d7a](https://github.com/quynhonsemiconductor/ci/commit/8ee4d7ac4103f8bb3a85e3dda147594b18b3ae71))

## [1.23.0](https://github.com/quynhonsemiconductor/ci/compare/v1.22.0...v1.23.0) (2026-10-21)


### Features

* **changed-paths:** compare the merge-queue head against its base ([#235](https://github.com/quynhonsemiconductor/ci/issues/235)) ([4cacc94](https://github.com/quynhonsemiconductor/ci/commit/4cacc94493580e0514d343687beb23415509c9f7))
* **k8s-deploy:** mint the gitops token from the qnsc-automation app ([#232](https://github.com/quynhonsemiconductor/ci/issues/232)) ([95a374e](https://github.com/quynhonsemiconductor/ci/commit/95a374ea458620760cbdcc933f900894a2695d18))
* **release:** retire the floating v1 tags; consumers pin vX.Y.Z by digest ([#230](https://github.com/quynhonsemiconductor/ci/issues/230)) ([67e5365](https://github.com/quynhonsemiconductor/ci/commit/67e53658d3c40d98891fbe8f1d60ebc7d3ec4f77))
* **workflows:** call ci siblings by exact release ref, never [@v1](https://github.com/v1) or [@main](https://github.com/main) ([#234](https://github.com/quynhonsemiconductor/ci/issues/234)) ([ba31d52](https://github.com/quynhonsemiconductor/ci/commit/ba31d52d54c760c40fb5cde36194aad32c162583))

## [1.22.0](https://github.com/quynhonsemiconductor/ci/compare/v1.21.0...v1.22.0) (2026-10-20)


### Features

* **actions:** add fetch-openapi-base-spec ([#190](https://github.com/quynhonsemiconductor/ci/issues/190)) ([dc0f170](https://github.com/quynhonsemiconductor/ci/commit/dc0f170016d10fe2b9cf9e5294acae37f7fb2784))
* **backend-deploy:** multi_arch: build amd64 and arm64 natively and merge one manifest ([#195](https://github.com/quynhonsemiconductor/ci/issues/195)) ([7ebbc5a](https://github.com/quynhonsemiconductor/ci/commit/7ebbc5a4812e4c9746fdbe99015002d74c77b1df))
* **changed-paths:** skip a workflow's heavy jobs when every changed file is ignorable ([#211](https://github.com/quynhonsemiconductor/ci/issues/211)) ([f79b879](https://github.com/quynhonsemiconductor/ci/commit/f79b87923204cecf42c8de8fbc67d24629fc71de))
* **code-review:** spend the model quota only on reviews that can finish ([#175](https://github.com/quynhonsemiconductor/ci/issues/175)) ([c5e36f6](https://github.com/quynhonsemiconductor/ci/commit/c5e36f6165365eaa4d1886b0104ea955b8280e34))
* **destructive-guard:** a composite action that refuses plans which delete or replace DNS or identity resources ([#192](https://github.com/quynhonsemiconductor/ci/issues/192)) ([3d0e2bd](https://github.com/quynhonsemiconductor/ci/commit/3d0e2bdd20ac0c1a5287f61ead1b4dc2e77dc985))
* **destructive-guard:** a drift mode for the nightly drift jobs ([#193](https://github.com/quynhonsemiconductor/ci/issues/193)) ([64ccd33](https://github.com/quynhonsemiconductor/ci/commit/64ccd3385f5720a5f179129a0547ad7a5eb9af89))
* **destructive-guard:** annotate every override, and say why a label lookup failed ([#197](https://github.com/quynhonsemiconductor/ci/issues/197)) ([d4692d2](https://github.com/quynhonsemiconductor/ci/commit/d4692d24a8977d6ebdcb7f36164646300ccbb6ce))
* **labeler:** apply size labels in the same job as area labels ([#177](https://github.com/quynhonsemiconductor/ci/issues/177)) ([b728e1c](https://github.com/quynhonsemiconductor/ci/commit/b728e1cfc4ba7cd30739093a48d67c7ea967ace3))
* **plan-guard:** gate target-group and parameter-group destroys like data ([#227](https://github.com/quynhonsemiconductor/ci/issues/227)) ([1570547](https://github.com/quynhonsemiconductor/ci/commit/157054766ccb4bd8fac7bd5b08f147ab58f859a2))
* **pr-size:** label pull requests by lines of code, warn when too large ([#176](https://github.com/quynhonsemiconductor/ci/issues/176)) ([d6445d8](https://github.com/quynhonsemiconductor/ci/commit/d6445d8a2f9ad3ef61bf1d8aa23f67f00a019492))
* review pull requests against our own rules ([#152](https://github.com/quynhonsemiconductor/ci/issues/152)) ([5f3846b](https://github.com/quynhonsemiconductor/ci/commit/5f3846b0537ea3313e8b4928ed85dbe96d5684dc))
* say whether anything is blocking, including when nothing is ([#165](https://github.com/quynhonsemiconductor/ci/issues/165)) ([55abee0](https://github.com/quynhonsemiconductor/ci/commit/55abee0eee07da8f61d0a60ad8d31d7dd725ba8a))
* **scripts:** find the writer of duplicate-timestamp metric samples ([#202](https://github.com/quynhonsemiconductor/ci/issues/202)) ([1fdc806](https://github.com/quynhonsemiconductor/ci/commit/1fdc806001c9721023025db69949d8dcaa4d3ae2))
* **security:** composite actions for the scans, Trivy on a local image, and PR labels ([#209](https://github.com/quynhonsemiconductor/ci/issues/209)) ([0d8aceb](https://github.com/quynhonsemiconductor/ci/commit/0d8aceb307b8132d16a2a6e75e490afd2891b954))
* **security:** opt-in combined scan jobs and a labeler built from steps ([#214](https://github.com/quynhonsemiconductor/ci/issues/214)) ([243c4bc](https://github.com/quynhonsemiconductor/ci/commit/243c4bc36d1cdb36fed9147c7aa8297501f2665d))
* **web-deploy:** workers target with versions upload and an approved prod rollout ([#233](https://github.com/quynhonsemiconductor/ci/issues/233)) ([82df441](https://github.com/quynhonsemiconductor/ci/commit/82df441137cf798421cf18233abe90f1dbf582ba))
* **workflows:** read cross-repository code with the read-only qnsc-repo-reader App ([#179](https://github.com/quynhonsemiconductor/ci/issues/179)) ([6336b25](https://github.com/quynhonsemiconductor/ci/commit/6336b2540fbe08b65a1ba120ac3e6f106b5c05ef))


### Bug Fixes

* a reasoning model needs longer than the 300s default ([#166](https://github.com/quynhonsemiconductor/ci/issues/166)) ([5a7a8df](https://github.com/quynhonsemiconductor/ci/commit/5a7a8df19b0d5e03a0b3546985ebbd010051b998))
* **actions:** setup-node-pnpm authenticates on pnpm 11 without writing the token anywhere ([#182](https://github.com/quynhonsemiconductor/ci/issues/182)) ([f1dd992](https://github.com/quynhonsemiconductor/ci/commit/f1dd992dc8cc274c210fcc51fb9e30522b47f654))
* **actions:** validate-openapi-contract fails on ERR-level changes ([#184](https://github.com/quynhonsemiconductor/ci/issues/184)) ([7101dd9](https://github.com/quynhonsemiconductor/ci/commit/7101dd97a20978403e5e53e5ee7641c1b1f6c32a))
* **backend-deploy:** move every container on the service image, verify tags, wait for the worker ([#199](https://github.com/quynhonsemiconductor/ci/issues/199)) ([d431b3e](https://github.com/quynhonsemiconductor/ci/commit/d431b3e2ab102729cb1f7d2ae912cf08cb480bc7))
* **backend-deploy:** say which re-run works when the immutable tag holds different images ([#198](https://github.com/quynhonsemiconductor/ci/issues/198)) ([74fa8e5](https://github.com/quynhonsemiconductor/ci/commit/74fa8e54af28539588cffcd75153abd70cb2dc98))
* **backend-deploy:** scan before push; stop pulling images from ECR ([#220](https://github.com/quynhonsemiconductor/ci/issues/220)) ([42f750d](https://github.com/quynhonsemiconductor/ci/commit/42f750d6224824d94679ac66d37192e305f0813b))
* **build-push-ecr:** keep trivy's cache out of the build context ([#223](https://github.com/quynhonsemiconductor/ci/issues/223)) ([f5fe8ff](https://github.com/quynhonsemiconductor/ci/commit/f5fe8ff6599b40d3be981ec40c414034aa23b568))
* **bump-gitops-tag:** a comment inside run: broke the action template ([#172](https://github.com/quynhonsemiconductor/ci/issues/172)) ([52b7f31](https://github.com/quynhonsemiconductor/ci/commit/52b7f31b217942289ffb7db3ccc839ee9cbb39b2))
* **code-review:** report why the rules download failed, and retry it ([#196](https://github.com/quynhonsemiconductor/ci/issues/196)) ([8672af0](https://github.com/quynhonsemiconductor/ci/commit/8672af0f141c5132f049f3c10fb700b90ab89abf))
* compute the routing threshold where an empty value is expressible ([#164](https://github.com/quynhonsemiconductor/ci/issues/164)) ([ac4fe8d](https://github.com/quynhonsemiconductor/ci/commit/ac4fe8d3e55a3d143d932e48554097235c17818d))
* **k8s-deploy:** attest the digest, not the tag ([#170](https://github.com/quynhonsemiconductor/ci/issues/170)) ([639c83d](https://github.com/quynhonsemiconductor/ci/commit/639c83d5bd63e0340a90cae6fe2e07627a95026d))
* **k8s-deploy:** build arm64 on an arm64 runner, not under QEMU ([#168](https://github.com/quynhonsemiconductor/ci/issues/168)) ([d09f5cf](https://github.com/quynhonsemiconductor/ci/commit/d09f5cff83768f7dea9719ba294da2cce736cc48))
* **k8s-deploy:** build the right Dockerfile stage per service ([#171](https://github.com/quynhonsemiconductor/ci/issues/171)) ([f339097](https://github.com/quynhonsemiconductor/ci/commit/f339097cf9d2d3b4862ae1ddfc38a78070125b5f))
* **k8s-deploy:** grant packages:read, which the caller's grant could not supply ([#169](https://github.com/quynhonsemiconductor/ci/issues/169)) ([643be94](https://github.com/quynhonsemiconductor/ci/commit/643be9452658fe07ea843a77db3ce39c96bc9b57))
* **plan-guard:** describe gated resources consistently ([#228](https://github.com/quynhonsemiconductor/ci/issues/228)) ([73ad75e](https://github.com/quynhonsemiconductor/ci/commit/73ad75e8bbe8a12ebe22e49ae873132c54c3e570))
* **platform-conformance:** retire the schedulable contract, alert on a red scheduled run ([#208](https://github.com/quynhonsemiconductor/ci/issues/208)) ([95cd2f1](https://github.com/quynhonsemiconductor/ci/commit/95cd2f14082c3ce05b2e9e2dcfe98cfdc9481ca3))
* **release-commenter:** create the release label once, before the action labels PRs in parallel ([#203](https://github.com/quynhonsemiconductor/ci/issues/203)) ([066a633](https://github.com/quynhonsemiconductor/ci/commit/066a6339ec132666fa021195c342646a6c5e5b20))
* **scripts:** compare series after the OTLP to Prometheus translation ([#204](https://github.com/quynhonsemiconductor/ci/issues/204)) ([dc80e54](https://github.com/quynhonsemiconductor/ci/commit/dc80e540f200c1c9b19d88361949677807014aa1))
* **stack-conformance:** open an issue when the scheduled report fails ([#206](https://github.com/quynhonsemiconductor/ci/issues/206)) ([c5ab28f](https://github.com/quynhonsemiconductor/ci/commit/c5ab28f5f5f7d152bad79657cd898d371e471f27))
* **stack-conformance:** record the worker health check decision, drop the wrong dkim reason ([#207](https://github.com/quynhonsemiconductor/ci/issues/207)) ([4510a2d](https://github.com/quynhonsemiconductor/ci/commit/4510a2db0f50d48e3fd60b4c762fad1251230122))
* the `all` branch of the severity mapping could never fire ([#163](https://github.com/quynhonsemiconductor/ci/issues/163)) ([8797dbd](https://github.com/quynhonsemiconductor/ci/commit/8797dbd8c91ea050ff68f870c39dea498e9adee3))
* **update-task-definition:** refuse a container that injects SERVICE_VERSION from a secret ([#201](https://github.com/quynhonsemiconductor/ci/issues/201)) ([102fa9e](https://github.com/quynhonsemiconductor/ci/commit/102fa9e7a236fe079a35931aae19884d0917078f))
* **update-task-definition:** set SERVICE_VERSION to the deployed tag in every container it rewrites ([#200](https://github.com/quynhonsemiconductor/ci/issues/200)) ([671d870](https://github.com/quynhonsemiconductor/ci/commit/671d870b20785368ffe7a2017b481958c47f5583))
* **workflows:** down-scope GitHub App tokens to named repositories and permissions ([#178](https://github.com/quynhonsemiconductor/ci/issues/178)) ([f8b2ebd](https://github.com/quynhonsemiconductor/ci/commit/f8b2ebdc0659f8154f495152bf77d188e3ee3e29))


### Performance Improvements

* **build-push-ecr:** write the build cache only from the default branch ([#210](https://github.com/quynhonsemiconductor/ci/issues/210)) ([e5fa5d7](https://github.com/quynhonsemiconductor/ci/commit/e5fa5d788477417e281ca532eefbdd7b218395a0))

## [1.21.0](https://github.com/quynhonsemiconductor/ci/compare/v1.20.0...v1.21.0) (2026-09-20)


### Features

* refuse a plan that destroys data, instead of prevent_destroy ([#154](https://github.com/quynhonsemiconductor/ci/issues/154)) ([d236a8a](https://github.com/quynhonsemiconductor/ci/commit/d236a8a87764384869e2acafc9ff07a378554400))

## [1.20.0](https://github.com/quynhonsemiconductor/ci/compare/v1.19.2...v1.20.0) (2026-09-20)


### Features

* a schedulable conformance contract, and stop publishing :latest ([#151](https://github.com/quynhonsemiconductor/ci/issues/151)) ([9378397](https://github.com/quynhonsemiconductor/ci/commit/937839759770a0d922ccf0cca8f8e657e2481fe2))

## [1.19.2](https://github.com/quynhonsemiconductor/ci/compare/v1.19.1...v1.19.2) (2026-09-17)


### Bug Fixes

* **scan-secrets:** gitleaks 8.30.1 — 8.21.2 flags a secretStoreRef as a secret ([#149](https://github.com/quynhonsemiconductor/ci/issues/149)) ([31a2ac0](https://github.com/quynhonsemiconductor/ci/commit/31a2ac0ddc5beef782248619dbb4756acbe204dd))

## [1.19.1](https://github.com/quynhonsemiconductor/ci/compare/v1.19.0...v1.19.1) (2026-09-16)


### Bug Fixes

* **conformance:** stacks are flat — live/&lt;product&gt;-&lt;env&gt;, one level ([#146](https://github.com/quynhonsemiconductor/ci/issues/146)) ([e570961](https://github.com/quynhonsemiconductor/ci/commit/e57096181d2d37decb069487dd1b089b10f179df))

## [1.19.0](https://github.com/quynhonsemiconductor/ci/compare/v1.18.0...v1.19.0) (2026-09-16)


### Features

* **actions:** add wait-for-run, a cross-workflow gate that survives a rate limit ([#144](https://github.com/quynhonsemiconductor/ci/issues/144)) ([e8b722c](https://github.com/quynhonsemiconductor/ci/commit/e8b722c18721f9f66bc2e6f7f69d822604842c4f))


### Bug Fixes

* **iac-lint:** lint nested stacks, and check that a module ref resolves ([#143](https://github.com/quynhonsemiconductor/ci/issues/143)) ([182bb56](https://github.com/quynhonsemiconductor/ci/commit/182bb56c1cca0ece7950f8abac31d61f9cb15f8b))

## [1.18.0](https://github.com/quynhonsemiconductor/ci/compare/v1.17.0...v1.18.0) (2026-09-16)


### Features

* kubernetes delivery path and estate-wide conformance ([#142](https://github.com/quynhonsemiconductor/ci/issues/142)) ([52999cc](https://github.com/quynhonsemiconductor/ci/commit/52999cc1a1e4ca6e211847d7f6185b15b3e064cf))
* **scripts:** report divergence between the product stack modules ([#134](https://github.com/quynhonsemiconductor/ci/issues/134)) ([5015096](https://github.com/quynhonsemiconductor/ci/commit/501509660d0fb3491569327afc65fdb5c5403a41))

## [1.17.0](https://github.com/quynhonsemiconductor/ci/compare/v1.16.3...v1.17.0) (2026-09-10)


### Features

* **actions:** add assert-jobs-succeeded, an aggregate CI gate ([#132](https://github.com/quynhonsemiconductor/ci/issues/132)) ([ad9ede8](https://github.com/quynhonsemiconductor/ci/commit/ad9ede81dd562135c2d4ae80464c0d158e64951b))


### Bug Fixes

* **actions:** drop expression syntax from assert-jobs-succeeded prose ([#133](https://github.com/quynhonsemiconductor/ci/issues/133)) ([ddfa08a](https://github.com/quynhonsemiconductor/ci/commit/ddfa08a70b2b872062775d25da0c568e25acf0e6))
* **ci:** run CI on stacked pull requests, not only PRs aimed at main ([#130](https://github.com/quynhonsemiconductor/ci/issues/130)) ([52406e7](https://github.com/quynhonsemiconductor/ci/commit/52406e78851285050a34cf934f4d328f2e85de50))

## [1.16.3](https://github.com/quynhonsemiconductor/ci/compare/v1.16.2...v1.16.3) (2026-09-09)


### Bug Fixes

* **actions:** iac-lint stopped scanning at the first directory with findings ([#127](https://github.com/quynhonsemiconductor/ci/issues/127)) ([433e5a1](https://github.com/quynhonsemiconductor/ci/commit/433e5a1a3e48a372c69659fa6f27572e255512c9))

## [1.16.2](https://github.com/quynhonsemiconductor/ci/compare/v1.16.1...v1.16.2) (2026-09-09)


### Bug Fixes

* **actions:** remove expression syntax from iac-lint prose, and smoke-test both ([#125](https://github.com/quynhonsemiconductor/ci/issues/125)) ([d2eb87a](https://github.com/quynhonsemiconductor/ci/commit/d2eb87ad7705d6e9686039ed0bc453bf57d34d68))

## [1.16.1](https://github.com/quynhonsemiconductor/ci/compare/v1.16.0...v1.16.1) (2026-09-09)


### Bug Fixes

* **actions:** iac-lint failed to load — an expression in an input description ([#123](https://github.com/quynhonsemiconductor/ci/issues/123)) ([82e7800](https://github.com/quynhonsemiconductor/ci/commit/82e7800adfc81dcc9b6e58febd1461af4f886927))

## [1.16.0](https://github.com/quynhonsemiconductor/ci/compare/v1.15.0...v1.16.0) (2026-09-09)


### Features

* **actions:** add iac-lint and iac-checkov composites for the three IaC repos ([#122](https://github.com/quynhonsemiconductor/ci/issues/122)) ([a3eea37](https://github.com/quynhonsemiconductor/ci/commit/a3eea37a84ae448d3db808b9bb7a5fd270ef61e6))
* **ci:** check PR titles against Conventional Commits ([#119](https://github.com/quynhonsemiconductor/ci/issues/119)) ([14f5408](https://github.com/quynhonsemiconductor/ci/commit/14f5408a01d02a88faafdccab90d44f78b11d022))

## [1.15.0](https://github.com/quynhonsemiconductor/ci/compare/v1.14.0...v1.15.0) (2026-09-08)


### Features

* **actions-security:** add actionlint alongside zizmor ([#111](https://github.com/quynhonsemiconductor/ci/issues/111)) ([4fba1a8](https://github.com/quynhonsemiconductor/ci/commit/4fba1a8de0d0b6704341e91ca362a41714cc78e2))

## [1.14.0](https://github.com/quynhonsemiconductor/ci/compare/v1.13.2...v1.14.0) (2026-09-08)


### Features

* **pr-title:** extract the conventional-commits check as a composite action ([#110](https://github.com/quynhonsemiconductor/ci/issues/110)) ([755ec13](https://github.com/quynhonsemiconductor/ci/commit/755ec137871b1d0a99dd31f2cabcaedfab91705a))


### Bug Fixes

* **deploy:** correct attestation signer-workflow path ([#109](https://github.com/quynhonsemiconductor/ci/issues/109)) ([659ad59](https://github.com/quynhonsemiconductor/ci/commit/659ad590a5811674365f1cc049a7f0dad1952483))
* **infra-plan:** auth private module fetch via RELEASE_BOT app token ([#105](https://github.com/quynhonsemiconductor/ci/issues/105)) ([1adf6c7](https://github.com/quynhonsemiconductor/ci/commit/1adf6c7a6dd7b2e8ce105ec607d20da0f65af634))

## [1.13.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.13.1...v1.13.2) (2026-08-31)


### Bug Fixes

* **promote-ecr-images:** raise the ECR poll budget from 10 to 17 minutes ([#101](https://github.com/QNSC-VN/qnsc-ci/issues/101)) ([43f6daf](https://github.com/QNSC-VN/qnsc-ci/commit/43f6daf7b7e9d56b3e2eb44907caa2c7a31442dc))

## [1.13.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.13.0...v1.13.1) (2026-08-26)


### Bug Fixes

* **agent-forge:** the reusable reports `test-guard / test-guard`, not `test-guard` ([#99](https://github.com/QNSC-VN/qnsc-ci/issues/99)) ([cb1cc09](https://github.com/QNSC-VN/qnsc-ci/commit/cb1cc09454e56cfad5c638dd1ee84269188edce3))

## [1.13.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.12.1...v1.13.0) (2026-08-26)


### Features

* **agent-forge:** share the test-guard instead of copying it into every repo ([#96](https://github.com/QNSC-VN/qnsc-ci/issues/96)) ([8a365f7](https://github.com/QNSC-VN/qnsc-ci/commit/8a365f73c0311894282c616f387d17044da37ca7))


### Bug Fixes

* **ci:** release-please could cut a release but not label the pull request ([#97](https://github.com/QNSC-VN/qnsc-ci/issues/97)) ([cedd741](https://github.com/QNSC-VN/qnsc-ci/commit/cedd7412681a021151075aa709a5e524092520e3))

## [1.12.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.12.0...v1.12.1) (2026-08-25)


### Bug Fixes

* **ci:** clear the zizmor low-confidence backlog (125 findings) ([#95](https://github.com/QNSC-VN/qnsc-ci/issues/95)) ([9ddfd3e](https://github.com/QNSC-VN/qnsc-ci/commit/9ddfd3e726509bafba575ab59da35336b77c002b))
* **ci:** fix high-confidence zizmor findings, gate on high severity ([#93](https://github.com/QNSC-VN/qnsc-ci/issues/93)) ([be05af0](https://github.com/QNSC-VN/qnsc-ci/commit/be05af074d90976358a98dbaf51147a7b7d195ff))

## [1.12.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.11.0...v1.12.0) (2026-08-24)


### Features

* **ci:** self-run zizmor Actions-security scan ([#90](https://github.com/QNSC-VN/qnsc-ci/issues/90)) ([f11d8a7](https://github.com/QNSC-VN/qnsc-ci/commit/f11d8a7c2d5cb352441791991c6d58087e4ac507))

## [1.11.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.10.0...v1.11.0) (2026-08-24)


### Features

* **security:** add reusable Actions-security scan (zizmor) ([#88](https://github.com/QNSC-VN/qnsc-ci/issues/88)) ([1b48f38](https://github.com/QNSC-VN/qnsc-ci/commit/1b48f3835be15b21d3723c90de57a54389b1067d))

## [1.10.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.9.2...v1.10.0) (2026-08-17)


### Features

* **build-push-ecr:** add a `none` cache backend, and correct the cost note ([#86](https://github.com/QNSC-VN/qnsc-ci/issues/86)) ([1ef2773](https://github.com/QNSC-VN/qnsc-ci/commit/1ef27731c95a6f2e4853e3665c8d76b6e70683ac))

## [1.9.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.9.1...v1.9.2) (2026-08-13)


### Performance Improvements

* **backend-deploy:** wake the environment alongside the build ([#84](https://github.com/QNSC-VN/qnsc-ci/issues/84)) ([221d26d](https://github.com/QNSC-VN/qnsc-ci/commit/221d26d91f09e4582f4ee00567a945346d035c5a))

## [1.9.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.9.0...v1.9.1) (2026-08-13)


### Performance Improvements

* **backend-deploy:** build the images in parallel ([#80](https://github.com/QNSC-VN/qnsc-ci/issues/80)) ([1baf46f](https://github.com/QNSC-VN/qnsc-ci/commit/1baf46f25fe36e3a903e528817faa3987f09e2b7))
* **build-push-ecr:** cache to the registry instead of the GitHub Actions cache ([#82](https://github.com/QNSC-VN/qnsc-ci/issues/82)) ([d0a7906](https://github.com/QNSC-VN/qnsc-ci/commit/d0a7906cb042ecfb14917e99c7078be60d5918cb))

## [1.9.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.8.0...v1.9.0) (2026-08-12)


### Features

* **ci:** discover pin-drift coverage instead of listing it ([#78](https://github.com/QNSC-VN/qnsc-ci/issues/78)) ([43a0379](https://github.com/QNSC-VN/qnsc-ci/commit/43a0379a0a86ab534e8095a15949608d745aa23d))

## [1.8.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.7.2...v1.8.0) (2026-08-12)


### Features

* **ci:** report shared pin drift across the product repos weekly ([#75](https://github.com/QNSC-VN/qnsc-ci/issues/75)) ([9df6b34](https://github.com/QNSC-VN/qnsc-ci/commit/9df6b3407e72cbc25963fd61fa1820ac2874a687))

## [1.7.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.7.1...v1.7.2) (2026-08-11)


### Bug Fixes

* **infra-plan:** plan without reading secret values ([#73](https://github.com/QNSC-VN/qnsc-ci/issues/73)) ([a37701b](https://github.com/QNSC-VN/qnsc-ci/commit/a37701b5937df9e2ab0a87b8a53ab5a2b5231179))

## [1.7.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.7.0...v1.7.1) (2026-08-10)


### Bug Fixes

* **web-deploy:** export VITE_API_BASE_URL and assert it reaches the bundle ([#71](https://github.com/QNSC-VN/qnsc-ci/issues/71)) ([87cf061](https://github.com/QNSC-VN/qnsc-ci/commit/87cf0618d06d33d625863a8205206062be817e9c))

## [1.7.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.6...v1.7.0) (2026-08-08)


### Features

* **backend-deploy:** add health_path input for the post-deploy readiness gate ([#69](https://github.com/QNSC-VN/qnsc-ci/issues/69)) ([cdccb5b](https://github.com/QNSC-VN/qnsc-ci/commit/cdccb5b85f25bde49326c1134bd617ee3b725737))

## [1.6.6](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.5...v1.6.6) (2026-08-05)


### Bug Fixes

* **backend-deploy:** give a cold RDS 15 minutes to wake, from one pair of constants ([#66](https://github.com/QNSC-VN/qnsc-ci/issues/66)) ([d83838e](https://github.com/QNSC-VN/qnsc-ci/commit/d83838e93e663ef6604f60818efca34e4c7484e6))

## [1.6.5](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.4...v1.6.5) (2026-07-30)


### Bug Fixes

* **backend-deploy:** verify readiness, not liveness, after a deploy ([#62](https://github.com/QNSC-VN/qnsc-ci/issues/62)) ([a7bd2c3](https://github.com/QNSC-VN/qnsc-ci/commit/a7bd2c3b03fa19100ab26d255f33af1cbbf0c9c8))

## [1.6.4](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.3...v1.6.4) (2026-07-29)


### Bug Fixes

* **infra-plan:** plan every workspace when a local path module changes ([#60](https://github.com/QNSC-VN/qnsc-ci/issues/60)) ([6e2c982](https://github.com/QNSC-VN/qnsc-ci/commit/6e2c982680429c2af1faf79b75ce6f3f712a3742))

## [1.6.3](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.2...v1.6.3) (2026-07-29)


### Bug Fixes

* **promote-ecr-images:** make promotion idempotent so a prod deploy can be re-run ([#58](https://github.com/QNSC-VN/qnsc-ci/issues/58)) ([caf4731](https://github.com/QNSC-VN/qnsc-ci/commit/caf4731b665538e05988719544b55a4243d164a4))

## [1.6.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.1...v1.6.2) (2026-07-28)


### Bug Fixes

* **actions:** let the health check actually retry ([#55](https://github.com/QNSC-VN/qnsc-ci/issues/55)) ([a977460](https://github.com/QNSC-VN/qnsc-ci/commit/a97746070639e057502eccf1a36695a8fb4030a6))

## [1.6.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.6.0...v1.6.1) (2026-07-28)


### Bug Fixes

* **deploy:** scan the image platform that was actually built ([#53](https://github.com/QNSC-VN/qnsc-ci/issues/53)) ([c46230d](https://github.com/QNSC-VN/qnsc-ci/commit/c46230d0b3c2ca149c382945cef5deb89e90c681))

## [1.6.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.5.1...v1.6.0) (2026-07-27)


### Features

* **deploy:** support ARM64 image builds and SSM secret preflight ([#51](https://github.com/QNSC-VN/qnsc-ci/issues/51)) ([8d641b6](https://github.com/QNSC-VN/qnsc-ci/commit/8d641b62ee16805099145df36f950270eda87a2f))

## [1.5.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.5.0...v1.5.1) (2026-07-27)


### Bug Fixes

* **backend-deploy:** skip RDS-managed secrets in the preflight ([#49](https://github.com/QNSC-VN/qnsc-ci/issues/49)) ([54e4d5e](https://github.com/QNSC-VN/qnsc-ci/commit/54e4d5e6b826100e394d424102bad7bba38cab14))

## [1.5.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.4.2...v1.5.0) (2026-07-26)


### Features

* **deploy:** secret preflight + reaper for gate-parked deploy runs ([#47](https://github.com/QNSC-VN/qnsc-ci/issues/47)) ([2c95e46](https://github.com/QNSC-VN/qnsc-ci/commit/2c95e4638511629cf95ffcde7ffc1e6b8fab1522))

## [1.4.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.4.1...v1.4.2) (2026-07-26)


### Bug Fixes

* resolve actionlint/shellcheck findings ([#44](https://github.com/QNSC-VN/qnsc-ci/issues/44)) ([26d5c0b](https://github.com/QNSC-VN/qnsc-ci/commit/26d5c0b1969fef2361d49e05a4e70d3816d23a5b))

## [1.4.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.4.0...v1.4.1) (2026-07-22)


### Bug Fixes

* **web-deploy:** pin wrangler-action to the caller's package manager ([#39](https://github.com/QNSC-VN/qnsc-ci/issues/39)) ([1cbb3a1](https://github.com/QNSC-VN/qnsc-ci/commit/1cbb3a1af41d6b4b9de51f5f0cd689bff12c992c))

## [1.4.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.3.4...v1.4.0) (2026-07-18)


### Features

* **web-deploy:** D1 pre-migration backup, health-check gate, pinned wrangler ([#36](https://github.com/QNSC-VN/qnsc-ci/issues/36)) ([8eecf04](https://github.com/QNSC-VN/qnsc-ci/commit/8eecf04f27b25da80f1850ac6a9982e99159bae2))

## [1.3.4](https://github.com/QNSC-VN/qnsc-ci/compare/v1.3.3...v1.3.4) (2026-07-16)


### Bug Fixes

* use correct apexskier placeholder syntax in release-commenter ([#34](https://github.com/QNSC-VN/qnsc-ci/issues/34)) ([3364f86](https://github.com/QNSC-VN/qnsc-ci/commit/3364f86150d6df19ed1397d327cde3468f642f83))

## [1.3.3](https://github.com/QNSC-VN/qnsc-ci/compare/v1.3.2...v1.3.3) (2026-07-15)


### Bug Fixes

* **backend-deploy:** pin signer-workflow when verifying attestation ([#32](https://github.com/QNSC-VN/qnsc-ci/issues/32)) ([b480fcd](https://github.com/QNSC-VN/qnsc-ci/commit/b480fcd0fd5518db4766d36ab0a591fab4ddbf0f))

## [1.3.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.3.1...v1.3.2) (2026-07-15)


### Bug Fixes

* **backend-deploy:** ECR login in deploy job for attestation verify ([#30](https://github.com/QNSC-VN/qnsc-ci/issues/30)) ([ca0e33c](https://github.com/QNSC-VN/qnsc-ci/commit/ca0e33c043b7799574c3712b8bf1644ce01cd85a))

## [1.3.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.3.0...v1.3.1) (2026-07-15)


### Bug Fixes

* **backend-deploy:** verify attestation without ecr:DescribeRegistry/DescribeImages ([#28](https://github.com/QNSC-VN/qnsc-ci/issues/28)) ([e99aef9](https://github.com/QNSC-VN/qnsc-ci/commit/e99aef9eb83a1c12950c128609353cd20e694565))

## [1.3.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.2.3...v1.3.0) (2026-07-14)


### Features

* **deploy:** circuit-breaker rollback, migrator pinning, verified attestation ([#27](https://github.com/QNSC-VN/qnsc-ci/issues/27)) ([6667aa5](https://github.com/QNSC-VN/qnsc-ci/commit/6667aa5b0330fc5a3272b264568d094fea51b217))
* **web-deploy:** add working_directory input for monorepo Pages Functions ([#24](https://github.com/QNSC-VN/qnsc-ci/issues/24)) ([6ae6c5d](https://github.com/QNSC-VN/qnsc-ci/commit/6ae6c5d1988d3090c2f9204c5355df0daba0c3fb))


### Bug Fixes

* **infra-plan:** stop referencing secrets context in a step if ([#22](https://github.com/QNSC-VN/qnsc-ci/issues/22)) ([af99dce](https://github.com/QNSC-VN/qnsc-ci/commit/af99dce42157e868a7d4e7b63ee97831f4b021a0))
* **run-db-migration:** pin internal ecs-run-task to [@v1](https://github.com/v1) for tag-sync updates ([#25](https://github.com/QNSC-VN/qnsc-ci/issues/25)) ([ba4658d](https://github.com/QNSC-VN/qnsc-ci/commit/ba4658d9ae1ec4554bbebec53e79bdd824bfe474))
* **web-deploy:** grant packages:read + NODE_AUTH_TOKEN so pnpm install can pull private @scope/* deps ([08617c2](https://github.com/QNSC-VN/qnsc-ci/commit/08617c2f4d9946c28c98694e93e45def45ea658c))

## [1.2.3](https://github.com/QNSC-VN/qnsc-ci/compare/v1.2.2...v1.2.3) (2026-07-12)


### Bug Fixes

* disable setup-opentofu wrapper so tofu exit codes are honest ([#20](https://github.com/QNSC-VN/qnsc-ci/issues/20)) ([2e6b06d](https://github.com/QNSC-VN/qnsc-ci/commit/2e6b06d43c59146d85e0ce511acb91fb33fe901e))

## [1.2.2](https://github.com/QNSC-VN/qnsc-ci/compare/v1.2.1...v1.2.2) (2026-07-12)


### Bug Fixes

* **ci:** authenticate image builds to GitHub Packages for @qnsc-vn/* ([#18](https://github.com/QNSC-VN/qnsc-ci/issues/18)) ([7c36836](https://github.com/QNSC-VN/qnsc-ci/commit/7c36836ab1da8a86278e8bcd6924e27d71a47e58))

## [1.2.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.2.0...v1.2.1) (2026-07-09)


### Bug Fixes

* **validate-openapi-contract:** bump oasdiff to v1.22.0 for OpenAPI 3.1 ([#11](https://github.com/QNSC-VN/qnsc-ci/issues/11)) ([200bf53](https://github.com/QNSC-VN/qnsc-ci/commit/200bf53df259aceddf9553a2483bfa89273b2dd5))

## [1.2.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.1.1...v1.2.0) (2026-07-08)


### Features

* **security:** add scan_container toggle to skip Trivy for CF-native apps ([16e9ba7](https://github.com/QNSC-VN/qnsc-ci/commit/16e9ba7628bde30e94f1ee38c52d6bf707760edf))


### Bug Fixes

* **security:** repair security suite + add scan_container toggle ([ae25363](https://github.com/QNSC-VN/qnsc-ci/commit/ae25363190ba789abc43d05f59167af35e25e89f))

## [1.1.1](https://github.com/QNSC-VN/qnsc-ci/compare/v1.1.0...v1.1.1) (2026-07-08)


### Bug Fixes

* **ci:** repair security suite — trivy ref, semgrep via docker, phased enforcement ([70111c0](https://github.com/QNSC-VN/qnsc-ci/commit/70111c0e9e4daf85e776d1da2b341abb2decb7a5))
* **ci:** repair security suite (trivy ref, semgrep docker, phased enforcement) ([4833532](https://github.com/QNSC-VN/qnsc-ci/commit/48335328de34bc9dd5ac92683b871685556d6135))

## [1.1.0](https://github.com/QNSC-VN/qnsc-ci/compare/v1.0.5...v1.1.0) (2026-07-08)


### Features

* **actions:** add promote-ecr-images composite action ([9b9e3cf](https://github.com/QNSC-VN/qnsc-ci/commit/9b9e3cf1061e35be4e432aece62abb2ba39e2a64))
* **actions:** add setup-tofu-aws for infra OIDC pipelines ([c0fd16d](https://github.com/QNSC-VN/qnsc-ci/commit/c0fd16d2ff6f6ff2864af7d860c2dcf8e83c1b77))
* add reusable tofu-plan/tofu-apply + backend/web-deploy workflows ([8a4b983](https://github.com/QNSC-VN/qnsc-ci/commit/8a4b983e9ae1d932eda2501d86728b7f109ddf76))
* **ci:** add reusable security, release-please, labeler, release-commenter workflows ([910895a](https://github.com/QNSC-VN/qnsc-ci/commit/910895a1a3992f04833407be5eb671d23a2dd4ea))
* **ci:** add reusable security/release/labeler/commenter workflows ([0d7b293](https://github.com/QNSC-VN/qnsc-ci/commit/0d7b2939eaee0717743fd6deaeecddffeffe464c))


### Bug Fixes

* **actions:** anchor verify-ecs-deploy grep; harden health-check curl handling ([fd7c01a](https://github.com/QNSC-VN/qnsc-ci/commit/fd7c01a8ef4d9d05ac532bf5d98fc170c72e9d8a))
* **actions:** update broken pinned SHAs for setup-opentofu and configure-aws-credentials ([7d9ae4f](https://github.com/QNSC-VN/qnsc-ci/commit/7d9ae4f6ae73f20d4c7fe544497d57972c0fa993))
* **ci:** correct invalid pinned action SHAs ([fc8620b](https://github.com/QNSC-VN/qnsc-ci/commit/fc8620b1ef7e78a3d48c9441fb04b3220e52c334))
* **run-db-migration:** update stale qnsc-gitops ref to qnsc-ci ([c909836](https://github.com/QNSC-VN/qnsc-ci/commit/c909836996867a75819b71dc7a1d9b4c96cb21c6))
* **scan-secrets:** call the Gitleaks CLI directly instead of gitleaks-action ([93c1d62](https://github.com/QNSC-VN/qnsc-ci/commit/93c1d62064a9b0aaa041c12fc05bd029dfe14bc8))
