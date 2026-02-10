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

```

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

`GET /logout`:

- returns **205 Reset Content** (suggests the browser should reset the view)
- sends strict anti-cache headers
- always sends `Clear-Site-Data: "cache","cookies","storage"`
- additionally sends best-effort `Set-Cookie` expirations (Path=/ only)

---

## Usage

1. Configure your logout domains in `.env`, e.g.:

```
LOGOUT_DOMAINS=https://app.example.com,https://nextcloud.example.com,https://mastodon.example.com
```

2. Deploy the logout proxy (Docker/Gunicorn).

3. Configure this service URL as **Front Channel Logout URL** in your IdP (e.g. Keycloak).

4. Ensure each application has a `/logout` endpoint that invalidates its own session.

---

## Docker Image

The image is published to GitHub Container Registry:

`ghcr.io/kevinveenbirkenbach/universal-logout`

Tags:
- `latest` is pushed on successful `main` builds.
- A Git tag is pushed only when the current commit is tagged.

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
