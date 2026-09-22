"""Guarantees app.py documents at length and nothing else checks."""

from http.cookies import SimpleCookie


def _set_cookie_headers(response):
    return response.headers.get_all("Set-Cookie")


def _deletions(response, name):
    out = []
    for header in _set_cookie_headers(response):
        jar = SimpleCookie()
        jar.load(header)
        if name in jar:
            out.append(jar[name])
    return out


def test_logout_answers_200_not_205(client):
    response = client.get("/logout")
    assert response.status_code == 200


def test_logout_sends_clear_site_data(client):
    response = client.get("/logout")
    assert response.headers["Clear-Site-Data"] == '"cache","cookies","storage"'


def test_logout_forbids_storing_the_response(client):
    response = client.get("/logout")
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def test_every_visible_cookie_is_expired_on_three_scopes(client):
    client.set_cookie("sid", "abc", domain="app.test.local")
    client.set_cookie("other", "xyz", domain="app.test.local")
    response = client.get("/logout", base_url="https://app.test.local")

    for name in ("sid", "other"):
        deletions = _deletions(response, name)
        assert len(deletions) == 3, (
            f"{name} needs parent-domain, exact-host and host-only"
        )
        assert all(morsel.value == "" for morsel in deletions)
        assert all(morsel["max-age"] in ("0", 0) for morsel in deletions)
        domains = {morsel["domain"] for morsel in deletions}
        assert domains == {"test.local", "app.test.local", ""}


def test_a_request_without_cookies_expires_nothing(client):
    response = client.get("/logout", base_url="https://app.test.local")
    assert _set_cookie_headers(response) == []


def test_the_secure_flag_follows_the_forwarded_scheme(client):
    client.set_cookie("sid", "abc", domain="app.test.local")

    plain = client.get("/logout", base_url="http://app.test.local")
    assert _set_cookie_headers(plain)
    assert all("Secure" not in header for header in _set_cookie_headers(plain))

    forwarded = client.get(
        "/logout",
        base_url="http://app.test.local",
        headers={"X-Forwarded-Proto": "https"},
    )
    assert all("Secure" in header for header in _set_cookie_headers(forwarded))


def test_the_conductor_lists_every_configured_domain(client, module, monkeypatch):
    monkeypatch.setattr(module, "DOMAINS", ["https://a.example", "https://b.example"])
    body = client.get("/").get_data(as_text=True)

    for host in ("https://a.example", "https://b.example"):
        assert host in body
        assert f"{host}/logout?manual=1" in body, "each row offers a manual way out"


def test_the_conductor_survives_an_empty_domain_list(client, module, monkeypatch):
    monkeypatch.setattr(module, "DOMAINS", [])
    response = client.get("/")
    assert response.status_code == 200
