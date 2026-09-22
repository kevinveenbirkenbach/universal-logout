# Changelog

## [1.4.0] - 2026-09-22

* Image ships for *linux/amd64* and *linux/arm64* under one tag.
* Each arch is built once natively and published as the build e2e tested.
* *latest* follows the highest release tag, not untagged commits on *main*.
* A release commit pushed with its tag no longer builds the image twice.
* *make lint* checks every language and format the repository ships.
* CodeQL, Trivy, dependency review and OSSF scorecard run on every change.
* Dependabot keeps actions, images and packages current.
* Playwright bumps no longer break e2e when image and package drift.
* *make test-e2e* builds the image first; *make test-e2e-run* reuses it.

## [1.3.1] - 2026-08-21

* Releases now actually reach the registry. Pushing a version tag started no workflow at all, and the build read its version from a tag lookup that a branch push could not see — which is why every image ever published carried only *latest*.
* *latest* no longer moves when an older commit is tagged. It follows the branch; a release keeps its own tag.

## [1.3.0] - 2026-08-21

* The logout page now speaks 30 languages, picked from the browser's *Accept-Language* header and overridable with *?lang=*. Arabic, Persian and Urdu render right-to-left.
* The conductor reports its sweep to the page that frames it via *postMessage*, so an identity provider embedding this page can tell when every service has been signed out — and which ones did not answer.
* Those messages are addressed to the framing origin, never broadcast.
* Verified across Chromium, Firefox and WebKit: 144 end-to-end tests, now including per-language rendering and the actual right-to-left layout, alongside 52 unit tests.
* Dependencies and test entrypoints declared in *pyproject.toml* (*make test*, *make test-unit*, *make test-e2e*).
* The translations are machine-generated and have not been reviewed by native speakers.

## [1.2.0] - 2026-02-10

* This release introduces separated CI workflows and automatically publishes the Docker image with `latest` and an optional Git tag after successful E2E tests.

## [1.1.0] - 2026-01-28

* * Reliable HTTPS logout verified across Chromium, Firefox, and WebKit
* Clear-Site-Data (HTTPS only) defined as the only path-agnostic cookie deletion mechanism
* Dockerized Playwright E2E tests ensure deterministic cross-browser validation


## [1.0.0] - 2026-01-17

* Official Release🥳

