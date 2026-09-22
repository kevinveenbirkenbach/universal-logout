import os

from flask import Flask, jsonify, make_response, request

app = Flask(__name__)

CONDUCTOR_ORIGINS = {"https://logout.test.local", "http://logout.test.local"}

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
    cookies = sorted(request.cookies.keys())
    return jsonify({"host": request.host.split(":")[0], "cookies": cookies})


@app.get("/logout")
def logout():
    """Sweep target for the conductor.

    The conductor fetches this cross-origin with credentials, so the response
    must name the conductor's origin explicitly - a wildcard is refused for
    credentialed requests.
    """
    host = request.host.split(":")[0]
    parent = _base_domain(host)

    resp = make_response("logged out\n", 200)
    origin = request.headers.get("Origin", "")
    if origin in CONDUCTOR_ORIGINS:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Credentials"] = "true"
    resp.headers["Clear-Site-Data"] = '"cache","cookies","storage"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"

    for name in sorted(request.cookies.keys()):
        for domain in (None, host, parent):
            resp.set_cookie(name, "", max_age=0, expires=0, path="/", domain=domain)

    return resp


@app.get("/frame")
def frame():
    """Stand in for Keycloak's logout page: frame the conductor, record reports.

    ``iss`` is what Keycloak appends to the front-channel logout URL, and it is
    where the conductor addresses its messages. The page keeps every report on
    ``window.__reports`` so a test can read the whole conversation.
    """
    conductor = request.args.get("conductor", "https://logout.test.local/")
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    origin = f"{scheme}://{request.host}"
    return (
        f"""<!doctype html>
<html><head><meta charset="utf-8"><title>frame</title></head>
<body>
<h1 id="parent">parent</h1>
<iframe id="conductor" src="{conductor}?iss={origin}/realms/x" style="width:600px;height:400px"></iframe>
<script>
window.__reports = [];
window.__origins = [];
window.addEventListener("message", function (event) {{
  window.__origins.push(event.origin);
  if (event.data && event.data.source === "universal-logout") {{
    window.__reports.push(event.data);
  }}
}});
</script>
</body></html>
""",
        200,
        {"Cache-Control": "no-store"},
    )


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
