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
    # Only affects this origin, but harmless and useful for privacy
    "Clear-Site-Data": '"cache","cookies","storage"',
    "Referrer-Policy": "no-referrer",
}


@app.after_request
def add_no_store(resp):
    for k, v in NO_STORE_HEADERS.items():
        # Do not override if already set explicitly on the response
        resp.headers.setdefault(k, v)
    return resp


@app.route("/")
def conductor():
    """Renders the conductor UI that triggers per-domain logout calls."""
    return render_template("conductor.html.j2", domains=DOMAINS)


@app.route("/logout")
def logout():
    """
    Expires all cookies visible to this host by sending three variants:
      1) Domain cookie for the parent eTLD+1 (e.g., .example.com)
      2) Domain cookie for the exact host (e.g., app.example.com)
      3) Host-only cookie (no Domain attribute)
    Returns 205 Reset Content and strict no-store headers.
    """
    host = request.host.split(":")[0]
    parts = host.split(".")
    parent_domain = "." + ".".join(parts[-2:]) if len(parts) >= 2 else host

    if DEBUG:
        logger.debug(f"Incoming host: {host}")
        logger.debug(f"Derived parent domain for cookie deletion: {parent_domain}")

    cookie_header = request.headers.get("Cookie", "")
    cookie_names = []
    for part in cookie_header.split(";"):
        if "=" in part:
            name = part.split("=", 1)[0].strip()
            if name:
                cookie_names.append(name)

    if DEBUG:
        logger.debug(f"Cookies to expire: {cookie_names}")

    # 205 = Reset Content (signals the client that the view should be reset)
    response = make_response("You have been logged out.", 205)
    # Enforce anti-cache headers explicitly on this endpoint
    for k, v in NO_STORE_HEADERS.items():
        response.headers[k] = v

    for name in cookie_names:
        if DEBUG:
            logger.debug(f"Expiring cookie: {name} on parent domain {parent_domain}")
            logger.debug(f"Expiring cookie: {name} on subdomain {host}")
            logger.debug(f"Expiring cookie: {name} without domain (host-only)")

        # Delete cookie on parent domain
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=parent_domain,
            path="/",
            secure=True,
            httponly=True,
        )
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=parent_domain,
            path="/",
            secure=True,
            httponly=True,
            samesite="None",
        )

        # Delete cookie on the exact host
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=host,
            path="/",
            secure=True,
            httponly=True,
        )
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            domain=host,
            path="/",
            secure=True,
            httponly=True,
            samesite="None",
        )

        # Delete host-only cookie (no Domain attribute)
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            path="/",
            secure=True,
            httponly=True,
        )
        response.set_cookie(
            key=name,
            value="",
            expires=0,
            max_age=0,
            path="/",
            secure=True,
            httponly=True,
            samesite="None",
        )

    return response


if __name__ == "__main__":
    # Development only; use Gunicorn in production
    app.run(host="0.0.0.0", port=8000)
