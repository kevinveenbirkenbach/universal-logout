from flask import Flask, request, make_response, jsonify
import os

app = Flask(__name__)

DEBUG = os.getenv("DEBUG_COOKIE_LAB", "false").lower() in ("1", "true", "yes")


def _base_domain(host: str) -> str:
    # host like app.test.local -> .test.local
    parts = host.split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return host


@app.get("/set")
def set_cookies():
    """
    Sets a matrix of cookies so we can test deletion strategies:

    - host-only cookie (no Domain)
    - domain cookie (Domain=.test.local)
    - path cookie (Path=/api)
    - secure cookies (only when scheme=https)
    """
    host = request.host.split(":")[0]
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    parent = _base_domain(host)

    resp = make_response("cookies set\n", 200)

    # Host-only cookies
    resp.set_cookie("host_only", "1", path="/")
    resp.set_cookie("host_only_api", "1", path="/api")

    # Domain cookies
    resp.set_cookie("domain_cookie", "1", domain=parent, path="/")
    resp.set_cookie("domain_cookie_api", "1", domain=parent, path="/api")

    # Secure cookies (only meaningful on https)
    if scheme == "https":
        resp.set_cookie("secure_host_only", "1", path="/", secure=True)
        resp.set_cookie(
            "secure_domain_cookie", "1", domain=parent, path="/", secure=True
        )

    if DEBUG:
        resp.headers["X-Debug-Host"] = host
        resp.headers["X-Debug-Parent"] = parent
        resp.headers["X-Debug-Scheme"] = scheme

    return resp


@app.get("/api/ping")
def api_ping():
    return "pong\n", 200


@app.get("/whoami")
def whoami():
    """
    Returns cookie names seen by this origin. Used by tests.
    """
    cookies = sorted(list(request.cookies.keys()))
    return jsonify({"host": request.host.split(":")[0], "cookies": cookies})


@app.get("/logout-setcookie")
def logout_setcookie():
    """
    Framework-agnostic cookie deletion via Set-Cookie headers.
    We delete:
      - host-only cookie variants
      - domain cookie variants
    and we cover both Path=/ and Path=/api.

    NOTE: We cannot delete cookies we don't know the names of.
    Here we delete the cookies this lab sets.
    """
    host = request.host.split(":")[0]
    parent = _base_domain(host)

    resp = make_response("logout-setcookie\n", 200)

    names = [
        "host_only",
        "host_only_api",
        "domain_cookie",
        "domain_cookie_api",
        "secure_host_only",
        "secure_domain_cookie",
    ]

    # Paths we want to cover
    paths = ["/", "/api"]

    for name in names:
        for p in paths:
            # Host-only delete
            resp.set_cookie(name, "", max_age=0, expires=0, path=p)

            # Host domain delete (explicit)
            resp.set_cookie(name, "", max_age=0, expires=0, path=p, domain=host)

            # Parent domain delete
            resp.set_cookie(name, "", max_age=0, expires=0, path=p, domain=parent)

    # Anti-cache
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"

    return resp
