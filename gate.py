import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

import jwt
from flask import Blueprint, jsonify, make_response, request

BACKCHANNEL_LOGOUT_EVENT = "http://schemas.openid.net/event/backchannel-logout"
ALGORITHMS = (
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
)
REQUIRED_CLAIMS = ["iss", "aud", "iat", "exp", "jti", "events"]
LEEWAY_SECONDS = 30
MAX_AGE_SECONDS = 120
TIMEOUT_SECONDS = 10
JWKS_LIFESPAN_SECONDS = 300
KEY_HEADER = "X-Logout-Gate-Key"
APPLICATION_ID = re.compile(r"[a-z0-9][a-z0-9-]*")

logger = logging.getLogger(__name__)


class LogoutTokenError(ValueError):
    pass


class KeysUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class GateClient:
    audience: str
    receiver: str
    key: str = field(repr=False)


@dataclass(frozen=True)
class Gate:
    issuer: str
    clients: dict
    signing_key: Callable[[str], object]


def _is_http_url(url):
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def parse_clients(raw):
    """Read the applications whose logout tokens the gate checks and forwards.

    :param raw: value of ``LOGOUT_GATE_CLIENTS``: a JSON object mapping each
        application id to an object with ``audience`` (its client id),
        ``receiver`` (the absolute http(s) URL of its back-channel logout
        endpoint) and ``key`` (the gate key its proxy expects); ``""`` for none
    :return: a ``GateClient`` per application id
    :raises ValueError: the value is no such object
    """
    if not raw.strip():
        return {}
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"LOGOUT_GATE_CLIENTS is no JSON object: {error}") from error
    if not isinstance(entries, dict):
        raise ValueError("LOGOUT_GATE_CLIENTS is no JSON object")  # noqa: TRY004
    clients = {}
    for application_id, entry in entries.items():
        if not APPLICATION_ID.fullmatch(application_id) or not isinstance(entry, dict):
            raise ValueError(
                f"LOGOUT_GATE_CLIENTS entry {application_id!r} is no application object"
            )
        client = GateClient(
            audience=str(entry.get("audience") or ""),
            receiver=str(entry.get("receiver") or ""),
            key=str(entry.get("key") or ""),
        )
        if not client.audience or not client.key or not _is_http_url(client.receiver):
            raise ValueError(
                f"LOGOUT_GATE_CLIENTS entry {application_id!r} needs an audience, "
                "a key and an http(s) receiver"
            )
        clients[application_id] = client
    return clients


def load(environ):
    """Build the gate from the process environment.

    :param environ: mapping that holds ``LOGOUT_GATE_CLIENTS``,
        ``LOGOUT_GATE_ISSUER`` and ``LOGOUT_GATE_JWKS_URL``
    :return: the ``Gate``; ``None`` when ``LOGOUT_GATE_CLIENTS`` is empty
    :raises ValueError: the clients are set without an issuer or an http(s)
        JWKS URL
    """
    clients = parse_clients(environ.get("LOGOUT_GATE_CLIENTS", ""))
    if not clients:
        return None
    issuer = environ.get("LOGOUT_GATE_ISSUER", "").strip()
    jwks_url = environ.get("LOGOUT_GATE_JWKS_URL", "").strip()
    if not issuer or not _is_http_url(jwks_url):
        raise ValueError(
            "LOGOUT_GATE_CLIENTS needs LOGOUT_GATE_ISSUER and an http(s) "
            "LOGOUT_GATE_JWKS_URL"
        )
    keys = jwt.PyJWKClient(
        jwks_url, lifespan=JWKS_LIFESPAN_SECONDS, timeout=TIMEOUT_SECONDS
    )
    return Gate(
        issuer=issuer,
        clients=clients,
        signing_key=lambda token: keys.get_signing_key_from_jwt(token).key,
    )


def verify_logout_token(token, audience, issuer, signing_key):
    """Check a logout token against OpenID Connect Back-Channel Logout 1.0, section 2.6.

    :param token: the ``logout_token`` form value
    :param audience: the client id the token must carry in ``aud``
    :param issuer: the issuer the token must carry in ``iss``
    :param signing_key: callable returning the verification key of an encoded token
    :return: the verified claims
    :raises LogoutTokenError: the token fails a check
    :raises KeysUnavailable: the issuer's keys could not be fetched
    """
    try:
        claims = jwt.decode(
            token,
            signing_key(token),
            algorithms=list(ALGORITHMS),
            audience=audience,
            issuer=issuer,
            leeway=LEEWAY_SECONDS,
            options={"require": REQUIRED_CLAIMS},
        )
    except jwt.PyJWKClientConnectionError as error:
        raise KeysUnavailable(str(error)) from error
    except jwt.PyJWTError as error:
        raise LogoutTokenError(str(error)) from error
    if time.time() - claims["iat"] > MAX_AGE_SECONDS + LEEWAY_SECONDS:
        raise LogoutTokenError("the token was issued too long ago")
    events = claims["events"]
    if not isinstance(events, dict) or not isinstance(
        events.get(BACKCHANNEL_LOGOUT_EVENT), dict
    ):
        raise LogoutTokenError("the events claim names no back-channel logout")
    if "nonce" in claims:
        raise LogoutTokenError("the token carries a nonce")
    if not claims.get("sub") and not claims.get("sid"):
        raise LogoutTokenError("the token names neither sub nor sid")
    return claims


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = build_opener(_NoRedirect)


def forward(client, token):
    """Hand a verified logout token to the application's own receiver.

    :param client: the ``GateClient`` of the application
    :param token: the verified ``logout_token``
    :return: the receiver's HTTP status; ``0`` when it could not be reached
    """
    outbound = Request(
        client.receiver,
        data=urlencode({"logout_token": token}).encode("ascii"),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            KEY_HEADER: client.key,
        },
        method="POST",
    )
    try:
        with _OPENER.open(outbound, timeout=TIMEOUT_SECONDS) as response:
            return response.status
    except HTTPError as error:
        error.close()
        return error.code
    except (URLError, OSError):
        return 0


def _refused():
    return make_response(jsonify(error="invalid_request"), 400)


def blueprint(gate):
    """Build the blueprint that serves ``POST /backchannel/<application_id>``.

    :param gate: the ``Gate`` to serve; ``None`` answers 404 for every application
    :return: the Flask blueprint
    """
    routes = Blueprint("backchannel_gate", __name__)

    @routes.post("/backchannel/<application_id>")
    def backchannel_logout(application_id):
        client = gate.clients.get(application_id) if gate else None
        if client is None:
            return make_response("", 404)
        token = request.form.get("logout_token", "")
        if not token:
            logger.warning("refused a request for %s: no logout_token", application_id)
            return _refused()
        try:
            verify_logout_token(token, client.audience, gate.issuer, gate.signing_key)
        except LogoutTokenError as error:
            logger.warning("refused a logout token for %s: %s", application_id, error)
            return _refused()
        except KeysUnavailable as error:
            logger.error("no signing keys for %s: %s", application_id, error)
            return make_response("", 503)
        status = forward(client, token)
        if 200 <= status < 300:
            logger.info("forwarded a logout token to %s", application_id)
            return make_response("", 200)
        logger.error(
            "the receiver of %s answered %s to a verified logout token",
            application_id,
            status,
        )
        return make_response("", 502)

    return routes
