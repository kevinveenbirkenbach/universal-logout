import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from urllib.parse import parse_qs

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask
from jwt.algorithms import RSAAlgorithm

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


def _jwks(kid, private_key):
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return {"keys": [{**jwk, "kid": kid, "use": "sig", "alg": "RS256"}]}


def _signing_key(jwk_set):
    keys = jwt.PyJWKSet.from_dict(jwk_set)

    def resolve(token):
        kid = jwt.get_unverified_header(token).get("kid")
        for key in keys.keys:
            if key.key_id == kid:
                return key.key
        raise jwt.PyJWKClientError(f"no signing key {kid}")

    return resolve


REALM_SIGNING_KEY = _signing_key(_jwks(REALM_KID, REALM_KEY))


def logout_token(private_key=REALM_KEY, kid=REALM_KID, **overrides):
    now = int(time.time())
    claims = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 120,
        "jti": "jti-1",
        "sub": "user-1",
        "sid": "session-1",
        "typ": "Logout",
        "events": {gate.BACKCHANNEL_LOGOUT_EVENT: {}},
    }
    claims.update(overrides)
    claims = {name: value for name, value in claims.items() if value is not DROP}
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


def id_token():
    return logout_token(events=DROP, nonce="n-1", typ="ID")


FORGED = {
    "signed with a foreign key": lambda: logout_token(private_key=FOREIGN_KEY),
    "signed with an unknown key": lambda: logout_token(
        private_key=FOREIGN_KEY, kid="foreign"
    ),
    "from a foreign issuer": lambda: logout_token(
        iss="https://auth.example.test/realms/foreign"
    ),
    "for another client": lambda: logout_token(aud="infinito-foreign-client"),
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
    "issued too long ago": lambda: logout_token(
        iat=int(time.time()) - 600, exp=int(time.time()) + 60
    ),
    "issued in the future": lambda: logout_token(iat=int(time.time()) + 600),
    "expired": lambda: logout_token(
        iat=int(time.time()) - 100, exp=int(time.time()) - 60
    ),
    "without a jti": lambda: logout_token(jti=DROP),
    "without an exp": lambda: logout_token(exp=DROP),
}


def _gate(signing_key=REALM_SIGNING_KEY):
    return gate.Gate(
        issuer=ISSUER,
        clients={APP: gate.GateClient(AUDIENCE, RECEIVER, GATE_KEY)},
        signing_key=signing_key,
    )


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
    flask_app = Flask(__name__)
    flask_app.register_blueprint(gate.blueprint(_gate()))
    return flask_app.test_client()


def test_a_keycloak_logout_token_is_accepted():
    claims = gate.verify_logout_token(
        logout_token(), AUDIENCE, ISSUER, REALM_SIGNING_KEY
    )
    assert claims["sid"] == "session-1"


def test_a_token_with_sid_only_or_sub_only_is_accepted():
    for token in (logout_token(sub=DROP), logout_token(sid=DROP)):
        gate.verify_logout_token(token, AUDIENCE, ISSUER, REALM_SIGNING_KEY)


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


def test_unreachable_signing_keys_are_no_refusal():
    def unreachable(_token):
        raise jwt.PyJWKClientConnectionError("connection refused")

    with pytest.raises(gate.KeysUnavailable):
        gate.verify_logout_token(logout_token(), AUDIENCE, ISSUER, unreachable)


@pytest.mark.parametrize("kind", sorted(FORGED))
def test_the_route_answers_a_forged_token_with_400_and_forwards_nothing(
    kind, gate_client, forwarded
):
    calls, _status = forwarded
    response = gate_client.post(
        f"/backchannel/{APP}", data={"logout_token": FORGED[kind]()}
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "invalid_request"}
    assert calls == []


def test_a_verified_token_reaches_the_receiver_and_answers_200(gate_client, forwarded):
    calls, _status = forwarded
    token = logout_token()
    response = gate_client.post(f"/backchannel/{APP}", data={"logout_token": token})
    assert response.status_code == 200
    assert calls == [(gate.GateClient(AUDIENCE, RECEIVER, GATE_KEY), token)]


@pytest.mark.parametrize("receiver_status", [0, 302, 400, 500])
def test_a_receiver_that_refuses_or_is_unreachable_answers_502(
    receiver_status, gate_client, forwarded
):
    _calls, status = forwarded
    status["code"] = receiver_status
    response = gate_client.post(
        f"/backchannel/{APP}", data={"logout_token": logout_token()}
    )
    assert response.status_code == 502


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


def test_only_post_is_served(gate_client):
    assert gate_client.get(f"/backchannel/{APP}").status_code == 405


def test_unreachable_signing_keys_answer_503(forwarded):
    def unreachable(_token):
        raise jwt.PyJWKClientConnectionError("connection refused")

    flask_app = Flask(__name__)
    flask_app.register_blueprint(gate.blueprint(_gate(signing_key=unreachable)))
    response = flask_app.test_client().post(
        f"/backchannel/{APP}", data={"logout_token": logout_token()}
    )
    assert response.status_code == 503


def test_without_clients_every_application_answers_404(client):
    response = client.post(f"/backchannel/{APP}", data={"logout_token": "x"})
    assert response.status_code == 404


def test_clients_parse_from_the_environment_value():
    raw = json.dumps(
        {APP: {"audience": AUDIENCE, "receiver": RECEIVER, "key": GATE_KEY}}
    )
    assert gate.parse_clients(raw) == {
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
        json.dumps({APP: {"audience": "", "receiver": RECEIVER, "key": "k"}}),
        json.dumps({APP: {"audience": "a", "receiver": RECEIVER, "key": ""}}),
        json.dumps({APP: {"audience": "a", "receiver": "ftp://x/y", "key": "k"}}),
        json.dumps({APP: {"audience": "a", "receiver": "/relative", "key": "k"}}),
    ],
)
def test_a_malformed_clients_value_fails_at_start(raw):
    with pytest.raises(ValueError):
        gate.parse_clients(raw)


def test_clients_without_issuer_or_keys_url_fail_at_start():
    raw = json.dumps(
        {APP: {"audience": AUDIENCE, "receiver": RECEIVER, "key": GATE_KEY}}
    )
    for environ in (
        {"LOGOUT_GATE_CLIENTS": raw, "LOGOUT_GATE_JWKS_URL": ISSUER + "/certs"},
        {"LOGOUT_GATE_CLIENTS": raw, "LOGOUT_GATE_ISSUER": ISSUER},
        {
            "LOGOUT_GATE_CLIENTS": raw,
            "LOGOUT_GATE_ISSUER": ISSUER,
            "LOGOUT_GATE_JWKS_URL": "certs",
        },
    ):
        with pytest.raises(ValueError):
            gate.load(environ)
    assert gate.load({}) is None


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
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        return


@pytest.fixture
def receiver():
    _Receiver.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
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


def test_forward_reports_an_unreachable_receiver_as_0():
    client = gate.GateClient(AUDIENCE, "http://127.0.0.1:9/receiver", GATE_KEY)
    assert gate.forward(client, "the-token") == 0
