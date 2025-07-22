# Universal Logout 🍪

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

---

## Overview

Managing logout across multiple applications integrated via OIDC can be tricky — especially when using nginx as a reverse proxy.  
This project, **Universal Logout**, provides a centralized logout proxy service that solves the common problem:

> ❌ *How do you reliably log out a user from **all** connected apps with a single logout action?*

Many setups struggle with this because nginx and typical OIDC clients don’t easily support coordinated logout flows spanning multiple services.

---

## What does it do?

Universal Logout acts as a **dedicated logout proxy** that:

- Receives logout requests from your Identity Provider (e.g. Keycloak) via **Front Channel Logout**.
- Iterates over a configurable list of subdomains/apps.
- Performs logout requests on each app’s `/logout` endpoint in the background.
- Provides a friendly UI status page to monitor logout progress.
- Handles cookie clearing on each domain to ensure sessions are fully invalidated.

This enables a **unified, service-wide logout experience** for users in complex OIDC environments.

---

## Why?

Because logging out a user from multiple apps behind nginx is not straightforward:  
- Cookies are domain-specific.  
- Sessions are often managed locally per app.  
- OIDC logout coordination requires all clients to participate properly.

Universal Logout solves these challenges elegantly by providing a **single logout endpoint** that proxies and orchestrates logout calls.

---

## Features ✨

- Simple Flask-based logout proxy with minimal dependencies.  
- Configurable logout domains via environment variables.  
- Detailed logout status UI with live progress updates.  
- Works seamlessly as the Front Channel Logout URL for Keycloak or other IdPs.  
- Docker-ready with an example Dockerfile and nginx proxy snippet.

---

## Usage

1. Configure your logout domains in `.env` via `LOGOUT_DOMAINS=app1.example.com,app2.example.com,...`  
2. Deploy the logout proxy service (e.g. with Docker).  
3. Set the logout proxy URL as the **Front Channel Logout URL** in your Keycloak realm settings.  
4. Make sure all apps expose a `/logout` endpoint that clears sessions/cookies properly.  
5. Enjoy unified logout across all your OIDC-integrated apps!

---

## License

This project is licensed under the **MIT License** — see [LICENSE](./LICENSE) for details.

---

## Author & Project Info

Developed by **Kevin Veen-Birkenbach** ([veen.world](https://veen.world))  
As part of the [CyMaIS](https://cymais.cloud) project — aiming to provide a unified, service-spanning logout for OIDC-connected applications.

---

## Links

- [GitHub Repository](https://github.com/kevinveenbirkenbach/universal-logout)  
- [CyMaIS Project](https://cymais.cloud)  
- [Author Website](https://veen.world)
- [Demo](https://logout.cymais.cloud/)
- [Ansible Role](https://github.com/kevinveenbirkenbach/cymais/tree/master/roles/web-svc-logout)

---

Thanks for using Universal Logout! 🍪🚀
