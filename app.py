# app.py
from flask import Flask, request, make_response, render_template
import logging
import sys
import os

app = Flask(__name__, template_folder="templates")

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
    return render_template("conductor.html.j2", domains=DOMAINS)


@app.route("/logout")
def logout():
    """
    Logout endpoint with ZERO path special-casing.

    Guarantees:
    - HTTPS + Clear-Site-Data => full cookie deletion (path-agnostic, browser-managed)
    - Set-Cookie deletions are best-effort fallback only

    Important constraints (by design, not by choice):
    - Cookies can only be deleted via Set-Cookie if name+domain+path match.
    - There is NO wildcard or path-agnostic Set-Cookie deletion.
    - Therefore we ONLY delete Path=/ cookies and rely on Clear-Site-Data
      for full correctness.
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

    # 205 Reset Content signals the browser to reset the view
    response = make_response("You have been logged out.", 205)

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
