# Changelog

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

