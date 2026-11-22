import importlib.util
import itertools
import json
import logging
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask
from jwt.algorithms import RSAAlgorithm
from jwt.utils import base64url_encode

import gate

ISSUER = "https://auth.example.test/realms/example"
AUDIENCE = "xwiki"
APP = "web-app-xwiki"
RECEIVER = "https://xwiki.example.test/oidc/authenticator/backchannel_logout"
GATE_KEY = "k" * 48
REALM_KID = "realm"
DROP = object()
REALM_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FOREIGN_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROXY_VARIABLES = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)
JTI = itertools.count()


def _jwks(kid, private_key):
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


def _signing_key(jwk_set):
    keys = jwt.PyJWKSet.from_dict(jwk_set)

    def resolve(token):
        kid = jwt.get_unverified_header(token).get("kid")
        for key in keys.keys:
            if key.key_id == kid:
                return key
        raise gate.LogoutTokenError(f"no signing key {kid}")

    return resolve


REALM_SIGNING_KEY = _signing_key(_jwks(REALM_KID, REALM_KEY))


def logout_token(private_key=REALM_KEY, kid=REALM_KID, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 120,
        "jti": f"jti-{next(JTI)}",
        "sub": "user-1",
        "sid": "session-1",
        "typ": "Logout",
        "events": {gate.BACKCHANNEL_LOGOUT_EVENT: {}},
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not DROP}
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def unsigned_token(header, claims):
    parts = [json.dumps(header).encode(), json.dumps(claims).encode(), b"\x00" * 64]
    return b".".join(base64url_encode(part) for part in parts).decode()


def id_token():
    return logout_token(events=DROP, nonce="n-1", typ="ID")


def settings(**values):
    return {name: values.get(name, "") for name in gate.SETTINGS}


def clients_value(**entry):
    return json.dumps(
        {APP: {"audience": AUDIENCE, "receiver": RECEIVER, "key": GATE_KEY, **entry}}
    )


FORGED = {
    "signed with a foreign key": lambda: logout_token(private_key=FOREIGN_KEY),
    "signed with an unknown key": lambda: logout_token(
        private_key=FOREIGN_KEY, kid="foreign"
    ),
    "from a foreign issuer": lambda: logout_token(
        iss="https://auth.example.test/realms/foreign"
    ),
    "for another client": lambda: logout_token(aud="infinito-foreign-client"),
    "for this and another client": lambda: logout_token(
        aud=[AUDIENCE, "infinito-foreign-client"]
    ),
    "an ID token of the realm": id_token,
}

REFUSED = {
    **FORGED,
    "without the events claim": lambda: logout_token(events=DROP),
    "with an event other than back-channel logout": lambda: logout_token(
        events={"http://schemas.openid.net/event/other": {}}
    ),
    "with a nonce": lambda: logout_token(nonce="n-1"),
    "naming neither sub nor sid": lambda: logout_token(sub=DROP, sid=DROP),
    "issued 121 seconds ago": lambda: logout_token(
        iat=int(time.time()) - 121, exp=int(time.time()) + 60
    ),
    "issued 145 seconds ago": lambda: logout_token(
        iat=int(time.time()) - 145, exp=int(time.time()) + 60
    ),
    "issued 31 seconds ahead": lambda: logout_token(iat=int(time.time()) + 31),
    "expired a second ago": lambda: logout_token(
        iat=int(time.time()) - 60, exp=int(time.time()) - 1
    ),
    "with an iat that is no number": lambda: logout_token(iat="now"),
    "without a jti": lambda: logout_token(jti=DROP),
    "without an exp": lambda: logout_token(exp=DROP),
    "with an algorithm other than its key's": lambda: unsigned_token(
        {"alg": "ES256", "kid": REALM_KID, "typ": "JWT"}, {"iss": ISSUER}
    ),
    "with a header nested 5000 deep": lambda: (
        f"{base64url_encode(('[' * 5000 + ']' * 5000).encode()).decode()}"
        f".{base64url_encode(b'{}').decode()}.AAAA"
    ),
}

ACCEPTED = {
    "naming sid only": lambda: logout_token(sub=DROP),
    "naming sub only": lambda: logout_token(sid=DROP),
    "issued 119 seconds ago": lambda: logout_token(
        iat=int(time.time()) - 119, exp=int(time.time()) + 60
    ),
    "issued 29 seconds ahead": lambda: logout_token(iat=int(time.time()) + 29),
}


def _gate(signing_key=REALM_SIGNING_KEY, receiver=RECEIVER):
    return gate.Gate(
        issuer=ISSUER,
        clients={APP: gate.GateClient(AUDIENCE, receiver, GATE_KEY)},
        signing_key=signing_key,
    )


def _route(the_gate):
    flask_app = Flask(__name__)
    flask_app.register_blueprint(gate.blueprint(the_gate))
    return flask_app.test_client()


def _post(client, token):
    return client.post(f"/backchannel/{APP}", data={"logout_token": token})


@pytest.fixture
def forwarded(monkeypatch):
    calls = []
    status = {"code": 200}

    def fake_forward(client, token):
        calls.append((client, token))
        return status["code"]

    monkeypatch.setattr(gate, "forward", fake_forward)
    return calls, status


@pytest.fixture
def gate_client():
    return _route(_gate())


@pytest.fixture
def no_proxy(monkeypatch):
    for name in PROXY_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_a_keycloak_logout_token_is_accepted():
    claims = gate.verify_logout_token(
        logout_token(), AUDIENCE, ISSUER, REALM_SIGNING_KEY
    )
    assert claims["sid"] == "session-1"


@pytest.mark.parametrize("kind", sorted(ACCEPTED))
def test_a_token_inside_every_bound_is_accepted(kind):
    gate.verify_logout_token(ACCEPTED[kind](), AUDIENCE, ISSUER, REALM_SIGNING_KEY)


@pytest.mark.parametrize("kind", sorted(REFUSED))
def test_a_token_that_fails_a_check_is_refused(kind):
    with pytest.raises(gate.LogoutTokenError):
        gate.verify_logout_token(REFUSED[kind](), AUDIENCE, ISSUER, REALM_SIGNING_KEY)


def test_a_symmetric_or_unsigned_token_is_refused():
    claims = jwt.decode(
        logout_token(), options={"verify_signature": False}, algorithms=["RS256"]
    )
    hmac = jwt.encode(
        claims,
        "a-shared-secret-of-thirty-two-bytes",
        algorithm="HS256",
        headers={"kid": REALM_KID},
    )
    unsigned = jwt.encode(claims, None, algorithm="none", headers={"kid": REALM_KID})
    for token in (hmac, unsigned):
        with pytest.raises(gate.LogoutTokenError):
            gate.verify_logout_token(token, AUDIENCE, ISSUER, REALM_SIGNING_KEY)


def test_an_unexpected_error_while_verifying_is_a_refusal(forwarded):
    def broken(_token):
        raise RuntimeError("unexpected")

    with pytest.raises(gate.LogoutTokenError):
        gate.verify_logout_token(logout_token(), AUDIENCE, ISSUER, broken)
    assert _post(_route(_gate(signing_key=broken)), logout_token()).status_code == 400


def test_unreachable_signing_keys_are_no_refusal():
    def unreachable(_token):
        raise gate.KeysUnavailable("connection refused")

    with pytest.raises(gate.KeysUnavailable):
        gate.verify_logout_token(logout_token(), AUDIENCE, ISSUER, unreachable)


@pytest.mark.parametrize("kind", sorted(FORGED))
def test_the_route_answers_a_forged_token_with_400_and_forwards_nothing(
    kind, gate_client, forwarded
):
    calls, _status = forwarded
    response = _post(gate_client, FORGED[kind]())
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_request"}
    assert calls == []


def test_a_verified_token_reaches_the_receiver_and_answers_200(gate_client, forwarded):
    calls, _status = forwarded
    token = logout_token()
    assert _post(gate_client, token).status_code == 200
    assert calls == [(gate.GateClient(AUDIENCE, RECEIVER, GATE_KEY), token)]


def test_a_replayed_token_is_refused_and_forwarded_once(gate_client, forwarded):
    calls, _status = forwarded
    token = logout_token()
    assert _post(gate_client, token).status_code == 200
    assert _post(gate_client, token).status_code == 400
    assert _post(gate_client, logout_token()).status_code == 200
    assert len(calls) == 2


def test_the_replay_memory_forgets_a_token_after_its_window():
    seen = gate.SeenTokens()
    assert seen.first_sight("jti-a", 1000.0)
    assert not seen.first_sight("jti-a", 1000.0 + gate.REPLAY_WINDOW_SECONDS - 1)
    assert seen.first_sight("jti-a", 1000.0 + gate.REPLAY_WINDOW_SECONDS + 1)


def test_the_replay_memory_stays_bounded():
    seen = gate.SeenTokens()
    for number in range(gate.SEEN_TOKENS_LIMIT + 1):
        assert seen.first_sight(f"jti-{number}", 1000.0)
    assert len(seen._expiry) == gate.SEEN_TOKENS_LIMIT
    assert seen.first_sight("jti-0", 1000.0)
    assert not seen.first_sight(f"jti-{gate.SEEN_TOKENS_LIMIT}", 1000.0)


@pytest.mark.parametrize("receiver_status", [0, 302, 400, 500])
def test_a_receiver_that_refuses_or_is_unreachable_answers_502(
    receiver_status, gate_client, forwarded
):
    _calls, status = forwarded
    status["code"] = receiver_status
    assert _post(gate_client, logout_token()).status_code == 502


def test_an_application_the_gate_does_not_serve_answers_404(gate_client, forwarded):
    calls, _status = forwarded
    response = gate_client.post(
        "/backchannel/web-app-unknown", data={"logout_token": logout_token()}
    )
    assert response.status_code == 404
    assert calls == []


def test_a_request_without_logout_token_answers_400(gate_client, forwarded):
    calls, _status = forwarded
    assert gate_client.post(f"/backchannel/{APP}", data={}).status_code == 400
    assert calls == []


def test_a_body_over_16_kib_answers_413_and_a_smaller_one_is_read(
    gate_client, forwarded
):
    calls, _status = forwarded
    assert _post(gate_client, "a" * gate.MAX_BODY_BYTES).status_code == 413
    assert _post(gate_client, "a" * (gate.MAX_BODY_BYTES - 100)).status_code == 400
    assert calls == []


def test_only_post_is_served(gate_client):
    assert gate_client.get(f"/backchannel/{APP}").status_code == 405


def test_unreachable_signing_keys_answer_503(forwarded):
    def unreachable(_token):
        raise gate.KeysUnavailable("connection refused")

    assert (
        _post(_route(_gate(signing_key=unreachable)), logout_token()).status_code == 503
    )


def test_without_clients_every_application_answers_404(client):
    response = client.post(f"/backchannel/{APP}", data={"logout_token": "x"})
    assert response.status_code == 404


def test_clients_parse_from_the_environment_value():
    assert gate.parse_clients(clients_value()) == {
        APP: gate.GateClient(AUDIENCE, RECEIVER, GATE_KEY)
    }
    assert gate.parse_clients("") == {}


def test_a_client_never_prints_its_key():
    assert GATE_KEY not in repr(gate.GateClient(AUDIENCE, RECEIVER, GATE_KEY))


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        json.dumps({"Web App": {"audience": "a", "receiver": RECEIVER, "key": "k"}}),
        json.dumps({APP: "xwiki"}),
        clients_value(audience=""),
        clients_value(key=""),
        clients_value(audience=["xwiki"]),
        clients_value(key=1),
        clients_value(receiver=None),
        clients_value(key=GATE_KEY + "\n"),
        clients_value(key="k k"),
        clients_value(key="schlüssel"),
        clients_value(audience="x wiki"),
        clients_value(receiver="ftp://xwiki.example.test/receiver"),
        clients_value(receiver="file:///etc/passwd"),
        clients_value(receiver="javascript:alert(1)"),
        clients_value(receiver="/relative"),
        clients_value(receiver="https://xwiki.example.test:80a/receiver"),
        clients_value(extra="field"),
        json.dumps({APP: {"audience": AUDIENCE, "receiver": RECEIVER}}),
    ],
)
def test_a_malformed_clients_value_fails_at_start(raw):
    with pytest.raises(ValueError):
        gate.parse_clients(raw)


@pytest.mark.parametrize(
    "receiver",
    [RECEIVER, "http://xwiki.abcdefghijklmnop.onion/receiver", "https://xwiki:8443/r"],
)
def test_an_absolute_http_or_https_receiver_is_accepted(receiver):
    assert (
        gate.parse_clients(clients_value(receiver=receiver))[APP].receiver == receiver
    )


@pytest.mark.parametrize(
    ("issuer", "jwks_url"),
    [
        ("", ISSUER + "/protocol/openid-connect/certs"),
        (ISSUER, ""),
        (ISSUER, "certs"),
        (ISSUER, "file:///etc/passwd"),
        (ISSUER, "ftp://auth.example.test/certs"),
        (ISSUER, "https://keys.example.test/realms/example/certs"),
        (ISSUER, "http://auth.example.test/realms/example/certs"),
        (ISSUER, "https://auth.example.test:8443/realms/example/certs"),
        ("realms/example", ISSUER + "/certs"),
        (ISSUER + "?x=1", ISSUER + "/certs"),
    ],
)
def test_clients_without_a_valid_issuer_and_keys_url_fail_at_start(issuer, jwks_url):
    with pytest.raises(ValueError):
        gate.load(
            settings(
                LOGOUT_GATE_CLIENTS=clients_value(),
                LOGOUT_GATE_ISSUER=issuer,
                LOGOUT_GATE_JWKS_URL=jwks_url,
            )
        )


@pytest.mark.parametrize(
    ("issuer", "jwks_url"),
    [
        (ISSUER, ISSUER + "/protocol/openid-connect/certs"),
        (
            "http://auth.abcdefghijklmnop.onion/realms/example",
            "http://auth.abcdefghijklmnop.onion/realms/example/protocol/openid-connect/certs",
        ),
    ],
)
def test_a_keys_url_on_the_issuer_origin_starts_the_gate(issuer, jwks_url):
    started = gate.load(
        settings(
            LOGOUT_GATE_CLIENTS=clients_value(),
            LOGOUT_GATE_ISSUER=issuer,
            LOGOUT_GATE_JWKS_URL=jwks_url,
        )
    )
    assert started.issuer == issuer


def test_the_gate_reads_exactly_its_own_settings():
    assert gate.load(settings()) is None
    with pytest.raises(ValueError):
        gate.load({**settings(), "HOME": "/root"})
    with pytest.raises(ValueError):
        gate.load({"LOGOUT_GATE_CLIENTS": ""})


def test_the_app_hands_the_gate_only_its_own_settings(monkeypatch):
    received = []
    monkeypatch.setenv("LOGOUT_GATE_UNRELATED", "x")
    monkeypatch.setattr(gate, "load", lambda values: received.append(values))
    spec = importlib.util.spec_from_file_location(
        "app_under_test", Path(__file__).resolve().parents[2] / "app.py"
    )
    spec.loader.exec_module(importlib.util.module_from_spec(spec))
    assert [set(values) for values in received] == [set(gate.SETTINGS)]


class _Jwks(BaseHTTPRequestHandler):
    body = b""
    hits = 0

    def do_GET(self):
        type(self).hits += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *_args):
        return


@pytest.fixture
def jwks_gate(no_proxy):
    _Jwks.body = json.dumps(_jwks(REALM_KID, REALM_KEY)).encode()
    _Jwks.hits = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Jwks)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    issuer = f"http://127.0.0.1:{server.server_port}/realms/example"
    the_gate = gate.load(
        settings(
            LOGOUT_GATE_CLIENTS=clients_value(),
            LOGOUT_GATE_ISSUER=issuer,
            LOGOUT_GATE_JWKS_URL=issuer + "/protocol/openid-connect/certs",
        )
    )
    yield the_gate, issuer
    server.shutdown()
    server.server_close()


def test_the_resolver_hands_out_the_key_bound_to_its_algorithm(jwks_gate):
    the_gate, issuer = jwks_gate
    key = the_gate.signing_key(logout_token(iss=issuer))
    assert isinstance(key, jwt.PyJWK)
    assert key.algorithm_name == "RS256"


def test_the_issuer_keys_verify_a_token_end_to_end(jwks_gate, forwarded):
    the_gate, issuer = jwks_gate
    assert _post(_route(the_gate), logout_token(iss=issuer)).status_code == 200


def test_an_algorithm_other_than_the_key_s_answers_400(jwks_gate, forwarded):
    the_gate, issuer = jwks_gate
    token = unsigned_token(
        {"alg": "ES256", "kid": REALM_KID, "typ": "JWT"}, {"iss": issuer}
    )
    assert _post(_route(the_gate), token).status_code == 400


@pytest.mark.parametrize("body", [b"<html>maintenance</html>", b'{"keys": []}', b"[]"])
def test_keys_the_issuer_cannot_serve_answer_503(body, jwks_gate, forwarded):
    the_gate, issuer = jwks_gate
    _Jwks.body = body
    assert _post(_route(the_gate), logout_token(iss=issuer)).status_code == 503


def test_unknown_kids_answer_400_without_refetching_the_keys(jwks_gate, forwarded):
    the_gate, issuer = jwks_gate
    client = _route(the_gate)
    statuses = [
        _post(client, logout_token(iss=issuer, kid=f"unknown-{number}")).status_code
        for number in range(5)
    ]
    assert statuses == [400] * 5
    assert _Jwks.hits == 1


def test_a_kid_with_a_line_break_forges_no_log_line(jwks_gate, forwarded, caplog):
    the_gate, issuer = jwks_gate
    caplog.set_level(logging.DEBUG, logger="gate")
    response = _post(_route(the_gate), logout_token(iss=issuer, kid="x\nFORGED-LINE"))
    assert response.status_code == 400
    assert "\nFORGED-LINE" not in caplog.text
    assert "FORGED-LINE" in caplog.text


class _Receiver(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = parse_qs(self.rfile.read(length).decode("ascii"))
        type(self).seen.append((self.path, self.headers.get(gate.KEY_HEADER), body))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/elsewhere")
            self.end_headers()
            return
        if self.path == "/broken":
            self.send_response(500)
            self.end_headers()
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        return


class _Garbage(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.recv(65536)
        self.request.sendall(b"GARBAGE\r\n\r\n")


@pytest.fixture
def receiver(no_proxy):
    _Receiver.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def garbage_receiver(no_proxy):
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Garbage)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/receiver"
    server.shutdown()
    server.server_close()


def test_forward_posts_the_token_with_the_gate_key(receiver):
    client = gate.GateClient(AUDIENCE, receiver + "/receiver", GATE_KEY)
    assert gate.forward(client, "the-token") == 204
    assert _Receiver.seen == [("/receiver", GATE_KEY, {"logout_token": ["the-token"]})]


def test_forward_follows_no_redirect_and_leaks_no_key(receiver):
    client = gate.GateClient(AUDIENCE, receiver + "/redirect", GATE_KEY)
    assert gate.forward(client, "the-token") == 302
    assert [path for path, _key, _body in _Receiver.seen] == ["/redirect"]


def test_forward_uses_no_proxy_from_the_environment(receiver, monkeypatch):
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setattr(gate, "_OPENER", gate._opener())
    client = gate.GateClient(AUDIENCE, receiver + "/receiver", GATE_KEY)
    assert gate.forward(client, "the-token") == 204


def test_forward_opens_no_url_but_http_and_https():
    for receiver in ("file:///etc/hostname", "ftp://127.0.0.1/receiver"):
        assert gate.forward(gate.GateClient(AUDIENCE, receiver, GATE_KEY), "t") == 0


def test_forward_reports_an_unreachable_receiver_as_0():
    client = gate.GateClient(AUDIENCE, "http://127.0.0.1:9/receiver", GATE_KEY)
    assert gate.forward(client, "the-token") == 0


def test_a_receiver_answering_no_http_answers_502(garbage_receiver):
    the_gate = _gate(receiver=garbage_receiver)
    assert _post(_route(the_gate), logout_token()).status_code == 502


def test_the_gate_key_reaches_no_log_line(receiver, garbage_receiver, caplog):
    caplog.set_level(logging.DEBUG)
    for target in (receiver + "/receiver", receiver + "/broken", garbage_receiver):
        client = _route(_gate(receiver=target))
        token = logout_token()
        _post(client, token)
        _post(client, token)
        _post(client, logout_token(private_key=FOREIGN_KEY))
    assert caplog.records
    assert GATE_KEY not in caplog.text
