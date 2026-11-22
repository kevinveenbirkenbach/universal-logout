import http.client
import json
import logging
import math
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import (
    HTTPDefaultErrorHandler,
    HTTPErrorProcessor,
    HTTPHandler,
    HTTPSHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    UnknownHandler,
)

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
CLIENT_FIELDS = {"audience", "receiver", "key"}
CLOCK_SKEW_SECONDS = 30
MAX_AGE_SECONDS = 120
REPLAY_WINDOW_SECONDS = MAX_AGE_SECONDS + CLOCK_SKEW_SECONDS
SEEN_TOKENS_LIMIT = 4096
TIMEOUT_SECONDS = 10
JWKS_LIFESPAN_SECONDS = 300
MAX_BODY_BYTES = 16 * 1024
KEY_HEADER = "X-Logout-Gate-Key"
SETTINGS = ("LOGOUT_GATE_CLIENTS", "LOGOUT_GATE_ISSUER", "LOGOUT_GATE_JWKS_URL")
APPLICATION_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
PRINTABLE = re.compile(r"[\x21-\x7e]+")

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


class SeenTokens:
    def __init__(self):
        self._expiry = OrderedDict()
        self._lock = threading.Lock()

    def first_sight(self, jti, now):
        """Record the id of a verified token and tell whether it is new.

        :param jti: the token's ``jti``
        :param now: the current time in seconds
        :return: ``False`` when the same ``jti`` passed within the last
            ``REPLAY_WINDOW_SECONDS``
        """
        with self._lock:
            while self._expiry and next(iter(self._expiry.values())) <= now:
                self._expiry.popitem(last=False)
            if jti in self._expiry:
                return False
            self._expiry[jti] = now + REPLAY_WINDOW_SECONDS
            if len(self._expiry) > SEEN_TOKENS_LIMIT:
                self._expiry.popitem(last=False)
            return True


def _origin(url):
    """Read the origin of an absolute http(s) URL.

    :param url: the URL to read
    :return: ``(scheme, host, port)``
    :raises ValueError: the URL is no absolute http(s) URL or names an invalid port
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"{url!r} is no absolute http(s) URL")
    return (
        parts.scheme,
        parts.hostname,
        parts.port or {"http": 80, "https": 443}[parts.scheme],
    )


def parse_clients(raw):
    """Read the applications whose logout tokens the gate checks and forwards.

    :param raw: value of ``LOGOUT_GATE_CLIENTS``: a JSON object mapping each
        application id to an object with exactly the string fields ``audience``
        (its client id), ``receiver`` (the absolute http(s) URL of its
        back-channel logout endpoint) and ``key`` (the gate key its proxy
        expects); ``""`` for none
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
        if (
            not APPLICATION_ID.fullmatch(application_id)
            or not isinstance(entry, dict)
            or set(entry) != CLIENT_FIELDS
            or not all(isinstance(value, str) for value in entry.values())
        ):
            raise ValueError(
                f"LOGOUT_GATE_CLIENTS entry {application_id!r} is no object of the "
                "string fields audience, receiver and key"
            )
        if not PRINTABLE.fullmatch(entry["audience"]) or not PRINTABLE.fullmatch(
            entry["key"]
        ):
            raise ValueError(
                f"LOGOUT_GATE_CLIENTS entry {application_id!r} needs an audience and "
                "a key of printable ASCII without spaces"
            )
        _origin(entry["receiver"])
        clients[application_id] = GateClient(**entry)
    return clients


def _signing_key(keys):
    """Build the resolver of the issuer key that verifies a token.

    :param keys: the ``PyJWKClient`` of the issuer's JWKS URL
    :return: callable mapping an encoded token to the ``PyJWK`` its ``kid`` names
    """

    def resolve(token):
        kid = jwt.get_unverified_header(token).get("kid")
        if not isinstance(kid, str) or not kid:
            raise LogoutTokenError("the token header names no kid")
        try:
            keys.get_signing_keys()
        except (jwt.PyJWKClientError, jwt.PyJWKSetError, ValueError) as error:
            raise KeysUnavailable(str(error)) from error
        try:
            return keys.get_signing_key(kid)
        except (jwt.PyJWKClientConnectionError, jwt.PyJWKSetError, ValueError) as error:
            raise KeysUnavailable(str(error)) from error
        except jwt.PyJWKClientError as error:
            raise LogoutTokenError(str(error)) from error

    return resolve


def load(settings):
    """Build the gate from its settings.

    :param settings: mapping of exactly the names in ``SETTINGS`` to their values
    :return: the ``Gate``; ``None`` when ``LOGOUT_GATE_CLIENTS`` is empty
    :raises ValueError: the mapping holds other names, a value is malformed, or
        the clients are set without an issuer URL and a JWKS URL on the
        issuer's origin
    """
    if set(settings) != set(SETTINGS):
        raise ValueError(f"the gate reads exactly the settings {', '.join(SETTINGS)}")
    clients = parse_clients(settings["LOGOUT_GATE_CLIENTS"])
    if not clients:
        return None
    issuer = settings["LOGOUT_GATE_ISSUER"].strip()
    jwks_url = settings["LOGOUT_GATE_JWKS_URL"].strip()
    issuer_parts = urlsplit(issuer)
    if issuer_parts.query or issuer_parts.fragment:
        raise ValueError("LOGOUT_GATE_ISSUER carries a query or a fragment")
    if _origin(jwks_url) != _origin(issuer):
        raise ValueError(
            "LOGOUT_GATE_JWKS_URL is not on the origin of LOGOUT_GATE_ISSUER"
        )
    keys = jwt.PyJWKClient(
        jwks_url, lifespan=JWKS_LIFESPAN_SECONDS, timeout=TIMEOUT_SECONDS
    )
    return Gate(issuer=issuer, clients=clients, signing_key=_signing_key(keys))


def verify_logout_token(token, audience, issuer, signing_key):
    """Check a logout token against OpenID Connect Back-Channel Logout 1.0, section 2.6.

    :param token: the ``logout_token`` form value
    :param audience: the client id the token must carry as its only ``aud``
    :param issuer: the issuer the token must carry in ``iss``
    :param signing_key: callable returning the ``PyJWK`` that verifies an encoded token
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
            options={
                "require": REQUIRED_CLAIMS,
                "strict_aud": True,
                "verify_iat": False,
            },
        )
    except (KeysUnavailable, LogoutTokenError):
        raise
    except Exception as error:
        raise LogoutTokenError(f"{type(error).__name__}: {error}") from error
    issued_at = claims["iat"]
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int | float)
        or not math.isfinite(issued_at)
    ):
        raise LogoutTokenError("the iat claim is no NumericDate")
    now = time.time()
    if issued_at > now + CLOCK_SKEW_SECONDS:
        raise LogoutTokenError("the token was issued in the future")
    if now - issued_at > MAX_AGE_SECONDS:
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


def _opener():
    opener = OpenerDirector()
    for handler in (
        ProxyHandler({}),
        HTTPHandler(),
        HTTPSHandler(),
        HTTPDefaultErrorHandler(),
        HTTPErrorProcessor(),
        UnknownHandler(),
    ):
        opener.add_handler(handler)
    return opener


_OPENER = _opener()


def forward(client, token):
    """Hand a verified logout token to the application's own receiver.

    :param client: the ``GateClient`` of the application
    :param token: the verified ``logout_token``
    :return: the receiver's HTTP status; ``0`` when it could not be reached or
        answered no valid HTTP response
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
    except (URLError, OSError, http.client.HTTPException, ValueError):
        return 0


def _refused():
    return make_response(jsonify(error="invalid_request"), 400)


def blueprint(gate):
    """Build the blueprint that serves ``POST /backchannel/<application_id>``.

    :param gate: the ``Gate`` to serve; ``None`` answers 404 for every application
    :return: the Flask blueprint
    """
    routes = Blueprint("backchannel_gate", __name__)
    seen = SeenTokens()

    @routes.post("/backchannel/<application_id>")
    def backchannel_logout(application_id):
        client = gate.clients.get(application_id) if gate else None
        if client is None:
            return make_response("", 404)
        request.max_content_length = MAX_BODY_BYTES
        token = request.form.get("logout_token", "")
        if not token:
            logger.warning("refused a request for %s: no logout_token", application_id)
            return _refused()
        try:
            claims = verify_logout_token(
                token, client.audience, gate.issuer, gate.signing_key
            )
        except LogoutTokenError as error:
            logger.warning(
                "refused a logout token for %s: %r", application_id, str(error)
            )
            return _refused()
        except KeysUnavailable as error:
            logger.error("no signing keys for %s: %r", application_id, str(error))
            return make_response("", 503)
        if not seen.first_sight(claims["jti"], time.time()):
            logger.warning("refused a replayed logout token for %s", application_id)
            return _refused()
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
