# Universal Logout 🍪

[![GitHub Sponsors](https://img.shields.io/badge/Sponsor-GitHub%20Sponsors-blue?logo=github)](https://github.com/sponsors/kevinveenbirkenbach) [![Patreon](https://img.shields.io/badge/Support-Patreon-orange?logo=patreon)](https://www.patreon.com/c/kevinveenbirkenbach) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20Coffee-Funding-yellow?logo=buymeacoffee)](https://buymeacoffee.com/kevinveenbirkenbach) [![PayPal](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal)](https://s.veen.world/paypaldonate) [![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

---

## Overview

Logging out across multiple OIDC-connected applications is hard because **sessions and cookies are origin-bound**.
Universal Logout provides a central **Front Channel Logout** endpoint (e.g. for Keycloak) that triggers per-domain logout calls and applies browser-safe cache/cookie clearing headers.

This repository also includes **E2E tests** (Playwright) to validate behavior across **Chromium, Firefox, and WebKit**.

---

## What exactly gets deleted?

Universal Logout uses **two mechanisms**:

1. **Clear-Site-Data (browser-managed, path-agnostic)**
2. **Set-Cookie expirations (server-managed, best-effort, path-sensitive)**

### 1) Clear-Site-Data (primary mechanism)

Every response includes:

```text
Clear-Site-Data: "cache","cookies","storage"
```

**On HTTPS**, modern browsers are expected to honor this header and clear:

- cookies for the current origin
- storage (localStorage/sessionStorage/IndexedDB)
- cache

✅ **This is the only path-agnostic and wildcard-like deletion mechanism available in browsers.**

### 2) Set-Cookie expirations (fallback / best-effort)

In addition, `/logout` expires cookies via `Set-Cookie` for:

- the derived parent domain (eTLD+1)
- the exact host
- host-only cookies (no Domain attribute)

However:

- **Set-Cookie can only delete cookies if `name + domain + path` match.**
- There is **no wildcard path deletion** with Set-Cookie.

So Universal Logout **only expires cookies for `Path=/`** as a best-effort fallback.

---

## HTTPS vs HTTP behavior (important)

### ✅ HTTPS (recommended / correct mode)

When Universal Logout is served via **HTTPS**:

- **Clear-Site-Data** is processed by browsers reliably (in practice: Chromium/Firefox/WebKit)
- cookies + storage are cleared **fully** for the current origin
- Set-Cookie expirations are applied as additional best-effort cleanup

**Result on HTTPS:**

- ✅ Cookies are reliably cleared (browser-managed)
- ✅ Storage is cleared
- ✅ Works cross-browser (validated via E2E tests)

### ⚠️ HTTP (best-effort only, not guaranteed)

When served via **HTTP**:

- Browsers may **ignore Clear-Site-Data** (varies by engine and policy)
- You fall back to Set-Cookie expirations only
- Since Set-Cookie deletion is **path-sensitive**, cookies set on paths like `/api` may remain

**Result on HTTP:**

- ❌ Clear-Site-Data may be ignored
- ⚠️ Only cookies visible to the request and matching `Path=/` are deleted best-effort
- ⚠️ Cookies on other paths (e.g. `/api`) and some host-only/domain variants may remain depending on how they were set

**Bottom line:** HTTP logout is **not a security contract**. If you need reliable cleanup, use HTTPS.

---

## What `/logout` does

`GET /logout` and `POST /logout`:

- return **200 OK**
- send strict anti-cache headers
- always send `Clear-Site-Data: "cache","cookies","storage"`
- additionally send best-effort `Set-Cookie` expirations (Path=/ only)

---

## Usage

1. Configure your logout domains in `.env`, e.g.:

   ```dotenv
   LOGOUT_DOMAINS=https://app.example.com,https://nextcloud.example.com,https://mastodon.example.com
   ```

2. Deploy the logout proxy (Docker/Gunicorn).

3. Configure this service URL as **Front Channel Logout URL** in your IdP (e.g. Keycloak).

4. Ensure each application has a `/logout` endpoint that invalidates its own session.

### Several networks, one conductor each

A deployment that serves the same applications on more than one network, for
example on clearnet over HTTPS and as Tor onion services over HTTP, runs one
conductor per network. A page served over HTTPS cannot fetch HTTP hosts, so the
browser travels instead: once a conductor's sweep is done it hands off to the
conductor of the next network.

Configure every conductor with the base URLs of the other networks' conductors:

```dotenv
# clearnet conductor
LOGOUT_SIBLINGS=http://logout.example.onion
# onion conductor
LOGOUT_SIBLINGS=https://logout.example.com
```

- `LOGOUT_SIBLINGS` is a comma-separated list of absolute `http(s)` base URLs
  without query or fragment. An invalid entry stops the service from starting.
  Empty or unset disables the hand-off and leaves the page unchanged.
- The conductor that starts a logout visits its siblings in the configured
  order. The hand-off URL carries the conductors still to visit in its `handoff`
  query parameter, so every conductor sweeps once and the last one ends on its
  own page.
- A conductor only ever hands off to a URL from its own `LOGOUT_SIBLINGS`;
  entries of the `handoff` parameter that are not configured there are dropped.
- Before it hands off, the conductor checks with a credential-less `no-cors`
  request (4 s) that the browser can reach the next sibling. A browser that
  cannot, such as one without Tor for an onion sibling or one that blocks the
  plain-HTTP sibling as mixed content, ends on the current conductor's page.
- Loaded top-level, the conductor navigates to the next sibling itself and no
  longer warns about the missing iframe. Loaded in an iframe, it cannot navigate
  the top-level page, so after `done` it posts
  `{ source: "universal-logout", type: "handoff", url }` to the framing page,
  which performs the navigation.

### Back-channel logout gate

Some applications ship an OIDC back-channel logout receiver that checks the
logout token only partly. The gate checks the token for them and forwards only a
token that passes every check. Point the IdP's back-channel logout URL of such
an application at `POST /backchannel/<application id>` and configure:

```dotenv
LOGOUT_GATE_ISSUER=https://auth.example.com/realms/example
LOGOUT_GATE_JWKS_URL=https://auth.example.com/realms/example/protocol/openid-connect/certs
LOGOUT_GATE_CLIENTS={"web-app-xwiki": {"audience": "xwiki", "receiver": "https://xwiki.example.com/oidc/authenticator/backchannel_logout", "key": "<gate key>"}}
```

- `LOGOUT_GATE_CLIENTS` maps each application id to its client id
  (`audience`), the absolute `http(s)` URL of its own receiver (`receiver`) and
  the gate key its proxy expects (`key`). Empty or unset disables the gate, and
  every `/backchannel/...` request answers `404`. A malformed value, or clients
  without `LOGOUT_GATE_ISSUER` and an `http(s)` `LOGOUT_GATE_JWKS_URL`, stops the
  service from starting.
- The token passes when it is signed by a key of `LOGOUT_GATE_JWKS_URL` with an
  asymmetric algorithm (RS, PS or ES), names `LOGOUT_GATE_ISSUER` as `iss` and the
  application's client as `aud`, carries `iat`, `exp`, `jti` and the
  `http://schemas.openid.net/event/backchannel-logout` event, was issued at most
  120 seconds ago (30 seconds of clock skew allowed), carries no `nonce` and names
  `sub`, `sid` or both. This is section 2.6 of OpenID Connect Back-Channel
  Logout 1.0. The keys are cached for 300 seconds and fetched again for an
  unknown `kid`.
- The gate answers `400` to a token that fails a check, `404` to an application
  it does not serve, `503` while the issuer's keys cannot be fetched, and `502`
  when the receiver answers anything but `2xx` or cannot be reached. A token that
  passes goes to the receiver unchanged as the `logout_token` form field with the
  application's key in the `X-Logout-Gate-Key` header, and the gate answers
  `200` once the receiver answered `2xx`. The gate follows no redirect, so the
  key reaches only the configured receiver.
- The proxy in front of each application must refuse every request to the
  receiver that does not carry the application's key, and must strip the header
  before it passes the request on. Otherwise the gate adds nothing, because the
  receiver can still be reached directly.

---

## Docker Image

The image is published to GitHub Container Registry:

`ghcr.io/kevinveenbirkenbach/universal-logout`

Tags:

- Every release tag `vX.Y.Z` is published for `linux/amd64` and `linux/arm64`.
- `latest` follows the highest release tag.

### Docker Run

```bash
docker run --rm -p 8000:8000 \
  -e LOGOUT_DOMAINS="https://app.example.com,https://nextcloud.example.com,https://mastodon.example.com" \
  ghcr.io/kevinveenbirkenbach/universal-logout:latest
```

### Docker Compose

```yaml
services:
  universal-logout:
    image: ghcr.io/kevinveenbirkenbach/universal-logout:latest
    ports:
      - "8000:8000"
    environment:
      - LOGOUT_DOMAINS=https://app.example.com,https://nextcloud.example.com,https://mastodon.example.com
```

---

## E2E Tests

This repository includes a Playwright-based E2E suite validating:

- Clear-Site-Data behavior on HTTP vs HTTPS
- Set-Cookie deletion behavior
- Combined strategy behavior across Chromium/Firefox/WebKit

Run:

```bash
make test-e2e
```

`make test-e2e` builds the service image as `universal-logout:e2e` first.
`make test-e2e-run` skips that build and tests whatever image carries the tag.

CI builds the image once per architecture on native amd64 and arm64 runners and
runs the E2E suite against exactly that image on the same architecture. A
release tag publishes those tested images under one multi-architecture tag
without building them again.

---

## Lint

```bash
make lint
```

Each linter runs from its own container image, so Docker is the only local
requirement:

| Target | Checks |
| --- | --- |
| `lint-python` | ruff check and ruff format |
| `lint-javascript` | ESLint |
| `lint-json` | JSON syntax |
| `lint-yaml` | yamllint |
| `lint-toml` | TOML syntax of `pyproject.toml` |
| `lint-docker` | hadolint on every Dockerfile |
| `lint-markdown` | markdownlint-cli2 |
| `lint-actions` | actionlint, including shellcheck on the workflow scripts |
| `lint-html` | djlint on the Jinja templates |
| `lint-nginx` | `nginx -t` on the E2E proxy config |
| `lint-compose` | `docker compose config` on the E2E stack |

---

## License

This project is licensed under the **MIT License** — see [LICENSE](./LICENSE) for details.

---

## Author & Project Info

Developed by **Kevin Veen-Birkenbach** ([veen.world](https://veen.world))  
As part of the [Infinito.Nexus](https://infinito.nexus) project — aiming to provide a unified, service-spanning logout for OIDC-connected applications.

---

## Links

- [GitHub Repository](https://github.com/kevinveenbirkenbach/universal-logout)  
- [CyMaIS Project](https://cymais.cloud)  
- [Author Website](https://veen.world)
- [Demo](https://logout.cymais.cloud/)
- [Ansible Role](https://github.com/kevinveenbirkenbach/cymais/tree/master/roles/web-svc-logout)

---

Thanks for using Universal Logout! 🍪🚀
