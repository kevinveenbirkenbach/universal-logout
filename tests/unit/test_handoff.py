"""Hand-off between the conductors of the networks one deployment serves."""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from app import handoff_target, parse_siblings

REPO_ROOT = Path(__file__).resolve().parents[2]
CLEARNET = "https://logout.example.com"
ONION = "http://logout.abcdefghijklmnop.onion"
I2P = "http://logout.example.i2p"


def _marker(url):
    values = parse_qs(urlsplit(url).query, keep_blank_values=True)["handoff"]
    assert len(values) == 1
    return values[0]


def _walk(config, start):
    visited = [start]
    target = handoff_target(config[start], None)
    while target is not None:
        base = target.split("/?", 1)[0]
        visited.append(base)
        assert len(visited) <= len(config), f"the hand-off loops: {visited}"
        target = handoff_target(config[base], _marker(target))
    return visited


def test_no_sibling_configured_means_no_handoff():
    assert parse_siblings("") == []
    assert parse_siblings(" , ,") == []


def test_siblings_are_trimmed_deduplicated_and_kept_in_order():
    raw = f" {ONION}/ , {CLEARNET},{ONION}"
    assert parse_siblings(raw) == [ONION, CLEARNET]


def test_a_sibling_may_live_below_a_path():
    assert parse_siblings("https://example.com/sso/") == ["https://example.com/sso"]


@pytest.mark.parametrize(
    "entry",
    [
        "logout.example.com",
        "//logout.example.com",
        "ftp://logout.example.com",
        "javascript:alert(1)",
        "https://logout.example.com/?lang=de",
        "https://logout.example.com/#top",
    ],
)
def test_a_sibling_that_is_no_http_base_url_fails_loudly(entry):
    with pytest.raises(ValueError, match="LOGOUT_SIBLINGS"):
        parse_siblings(f"{ONION},{entry}")


def _import_app(siblings):
    env = {**os.environ, "LOGOUT_SIBLINGS": siblings}
    return subprocess.run(
        [sys.executable, "-c", "import app; print(app.SIBLINGS)"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_service_reads_its_siblings_from_the_environment():
    proc = _import_app(f"{ONION}/")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == repr([ONION])


def test_a_misconfigured_sibling_stops_the_service_from_starting():
    proc = _import_app("logout.abcdefghijklmnop.onion")
    assert proc.returncode != 0, "a sibling without scheme must not boot silently"
    assert "LOGOUT_SIBLINGS" in proc.stderr


def test_the_starting_conductor_continues_to_its_first_sibling():
    target = handoff_target([ONION, I2P], None)
    assert target.split("/?", 1)[0] == ONION
    assert _marker(target) == I2P, "the rest of the plan travels along"


def test_the_last_conductor_of_the_plan_ends_the_logout():
    assert handoff_target([CLEARNET], "") is None


def test_a_clearnet_logout_crosses_to_the_onion_once_and_ends_there():
    config = {CLEARNET: [ONION], ONION: [CLEARNET]}
    assert _walk(config, CLEARNET) == [CLEARNET, ONION]


def test_an_onion_logout_crosses_to_clearnet_once_and_ends_there():
    config = {CLEARNET: [ONION], ONION: [CLEARNET]}
    assert _walk(config, ONION) == [ONION, CLEARNET]


@pytest.mark.parametrize("start", [CLEARNET, ONION, I2P])
def test_three_networks_are_each_swept_exactly_once(start):
    everyone = [CLEARNET, ONION, I2P]
    config = {url: [other for other in everyone if other != url] for url in everyone}
    visited = _walk(config, start)
    assert sorted(visited) == sorted(everyone)


def test_a_forged_marker_cannot_lengthen_the_chain():
    forged = ",".join([ONION, CLEARNET] * 50)
    hops = 0
    target = handoff_target([ONION, CLEARNET], forged)
    while target is not None:
        hops += 1
        assert hops <= 2, "the plan must shrink with every hop"
        target = handoff_target([ONION, CLEARNET], _marker(target))


def test_an_unconfigured_target_is_refused():
    assert handoff_target([ONION], "https://evil.example") is None


def test_an_unconfigured_entry_is_dropped_and_never_forwarded():
    target = handoff_target([ONION], f"https://evil.example,{ONION}/")
    assert target.split("/?", 1)[0] == ONION
    assert _marker(target) == ""


def test_a_conductor_without_siblings_never_hands_off():
    assert handoff_target([], None) is None
    assert handoff_target([], ONION) is None


def test_without_siblings_the_page_ignores_the_marker(client, module, monkeypatch):
    monkeypatch.setattr(module, "DOMAINS", ["https://a.example"])
    monkeypatch.setattr(module, "SIBLINGS", [])
    plain = client.get("/?lang=en").get_data(as_text=True)

    for query in ("&handoff=", f"&handoff={ONION}"):
        assert client.get(f"/?lang=en{query}").get_data(as_text=True) == plain
    assert "handoff" not in plain
    assert "!important" not in plain


def test_with_siblings_the_top_level_page_is_no_misconfiguration(
    client, module, monkeypatch
):
    monkeypatch.setattr(module, "SIBLINGS", [ONION])
    for query in ("", "?handoff="):
        body = client.get(f"/{query}").get_data(as_text=True)
        assert "#iframe-warning { display: none !important; }" in body


def test_the_page_carries_the_handoff_target(client, module, monkeypatch):
    monkeypatch.setattr(module, "SIBLINGS", [ONION])
    body = client.get("/").get_data(as_text=True)
    assert f'const HANDOFF = "{ONION}/?handoff=";' in body


def test_the_end_of_the_chain_carries_no_handoff(client, module, monkeypatch):
    monkeypatch.setattr(module, "SIBLINGS", [CLEARNET])
    body = client.get("/?handoff=").get_data(as_text=True)
    assert "HANDOFF" not in body


def test_a_forged_marker_puts_no_foreign_url_into_the_page(client, module, monkeypatch):
    monkeypatch.setattr(module, "SIBLINGS", [ONION])
    body = client.get("/?handoff=https%3A%2F%2Fevil.example").get_data(as_text=True)
    assert "evil.example" not in body
    assert "HANDOFF" not in body
