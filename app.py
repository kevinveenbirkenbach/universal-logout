# app.py
import logging
import os
import sys
from pathlib import Path

import yaml
from flask import Flask, make_response, render_template, request

app = Flask(__name__, template_folder="templates")

TRANSLATIONS = yaml.safe_load(
    (Path(__file__).resolve().parent / "translations.yml").read_text(encoding="utf-8")
)
FALLBACK_LANG = "en"


def negotiate_language(accept_languages, requested=None):
    """Pick a catalogue key from ?lang= or the Accept-Language header.

    :param accept_languages: werkzeug ``LanguageAccept`` from the request
    :param requested: explicit override, e.g. the ``lang`` query parameter
    :return: a key of ``TRANSLATIONS``; ``FALLBACK_LANG`` when nothing matches
    """
    for candidate in (requested, ):
        if candidate and candidate.split("-")[0].lower() in TRANSLATIONS:
            return candidate.split("-")[0].lower()

    match = accept_languages.best_match(list(TRANSLATIONS))
    if match:
        return match

    for tag, _quality in accept_languages:
        base = tag.split("-")[0].lower()
        if base in TRANSLATIONS:
            return base

    return FALLBACK_LANG

# Load domains from an env var (comma-separated)
DOMAINS = [d.strip() for d in os.getenv("LOGOUT_DOMAINS", "").split(",") if d.strip()]
DEBUG = os.getenv("DEBUG_LOGOUT", "false").lower() in ("1", "true", "yes")

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# Strict anti-cache headers applied to every response
NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, private",
    "Pragma": "no-cache",
    "Expires": "0",
    # Clear-Site-Data is the ONLY path-agnostic cookie deletion mechanism
    "Clear-Site-Data": '"cache","cookies","storage"',
    "Referrer-Policy": "no-referrer",
}


@app.after_request
def add_no_store(resp):
    for k, v in NO_STORE_HEADERS.items():
        resp.headers.setdefault(k, v)
    return resp


@app.route("/")
def conductor():
    """Render the conductor UI that triggers per-domain logout calls."""
    lang = negotiate_language(request.accept_languages, request.args.get("lang"))
    catalogue = TRANSLATIONS[lang]
    return render_template(
        "conductor.html.j2",
        domains=DOMAINS,
        t=catalogue,
        lang=lang,
        text_direction=catalogue["dir"],
    )


@app.route("/logout")
def logout():
    """
    Logout endpoint with ZERO path special-casing.

    Guarantees:
    - HTTPS + Clear-Site-Data => full cookie deletion (path-agnostic, browser-managed)
    - HTTP (or any non-secure context, e.g. http://.onion outside Tor Browser)
      => Set-Cookie deletions still clear Path=/ cookies, because this endpoint
      returns a committed 200 document. A 205 (or any non-committed navigation
      response) makes the browser drop Set-Cookie on a top-level navigation, so
      the plain-http fallback would never fire when a user navigates straight to
      /logout. 200 keeps both the conductor's fetch() sweep and direct
      navigation working.

    Important constraints (by design, not by choice):
    - Cookies can only be deleted via Set-Cookie if name+domain+path match.
    - There is NO wildcard or path-agnostic Set-Cookie deletion.
    - Therefore we ONLY delete Path=/ cookies and rely on Clear-Site-Data
      for full correctness in secure contexts.
    """
    host = request.host.split(":")[0]
    parts = host.split(".")
    parent_domain = "." + ".".join(parts[-2:]) if len(parts) >= 2 else host

    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    is_https = scheme == "https"

    if DEBUG:
        logger.debug(f"Incoming host: {host}")
        logger.debug(f"Derived parent domain: {parent_domain}")
        logger.debug(f"Scheme: {scheme}")

    # Extract cookie names visible to this request
    cookie_header = request.headers.get("Cookie", "")
    cookie_names = []
    for part in cookie_header.split(";"):
        if "=" in part:
            name = part.split("=", 1)[0].strip()
            if name:
                cookie_names.append(name)

    if DEBUG:
        logger.debug(f"Cookies to expire: {cookie_names}")

    # 200 (committed document) so the browser applies the Set-Cookie deletions
    # below even on a direct top-level navigation to /logout — a 205 would be
    # dropped by the navigation and defeat the plain-http fallback.
    response = make_response("You have been logged out.", 200)

    # Enforce no-store headers explicitly
    for k, v in NO_STORE_HEADERS.items():
        response.headers[k] = v

    # Best-effort Set-Cookie deletion (Path=/ only, NO special cases)
    for name in cookie_names:
        # Parent domain
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=parent_domain,
            path="/",
            secure=is_https,
            httponly=True,
        )

        # Exact host
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=host,
            path="/",
            secure=is_https,
            httponly=True,
        )

        # Host-only (no Domain attribute)
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            path="/",
            secure=is_https,
            httponly=True,
        )

    return response


if __name__ == "__main__":
    # Development only; use Gunicorn in production
    port = int(os.getenv("LOGOUT_PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
