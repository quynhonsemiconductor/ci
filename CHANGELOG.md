# Changelog

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
