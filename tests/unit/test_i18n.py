"""The catalogue is data, so nothing but a test keeps its 30 entries in step."""

import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = yaml.safe_load((REPO_ROOT / "translations.yml").read_text(encoding="utf-8"))
TEMPLATE = (REPO_ROOT / "templates" / "conductor.html.j2").read_text(encoding="utf-8")
REFERENCE = "en"
RTL = {"ar", "fa", "ur"}


def test_thirty_languages_are_offered():
    assert len(CATALOGUE) == 30


def test_every_language_carries_every_key():
    expected = set(CATALOGUE[REFERENCE])
    for lang, entry in CATALOGUE.items():
        assert set(entry) == expected, (
            f"{lang} diverges: {sorted(set(entry) ^ expected)}"
        )


def test_no_string_is_left_empty_or_untranslated_by_accident():
    reference = CATALOGUE[REFERENCE]
    for lang, entry in CATALOGUE.items():
        for key, value in entry.items():
            assert value.strip(), f"{lang}.{key} is empty"
        if lang == REFERENCE:
            continue
        translated = [k for k, v in entry.items() if k != "dir" and v != reference[k]]
        assert len(translated) >= len(reference) - 2, (
            f"{lang} looks mostly untranslated"
        )


def test_right_to_left_languages_are_marked_and_others_are_not():
    for lang, entry in CATALOGUE.items():
        expected = "rtl" if lang in RTL else "ltr"
        assert entry["dir"] == expected, f"{lang} should be {expected}"


def test_every_key_the_template_uses_exists(client):
    used = set(re.findall(r"\bt\.([a-z_]+)", TEMPLATE))
    assert used, "the template no longer reads the catalogue"
    missing = used - set(CATALOGUE[REFERENCE])
    assert not missing, (
        f"the template reads keys the catalogue lacks: {sorted(missing)}"
    )


def test_every_catalogue_key_is_actually_used(client):
    used = set(re.findall(r"\bt\.([a-z_]+)", TEMPLATE)) | {"dir"}
    unused = set(CATALOGUE[REFERENCE]) - used
    assert not unused, f"dead catalogue keys: {sorted(unused)}"


@pytest.mark.parametrize("lang", sorted(CATALOGUE))
def test_every_language_renders(client, lang):
    response = client.get(f"/?lang={lang}")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert f'lang="{lang}"' in body
    assert f'dir="{CATALOGUE[lang]["dir"]}"' in body
    assert CATALOGUE[lang]["heading"] in body
    assert "Undefined" not in body


def test_the_header_decides_when_no_override_is_given(client):
    body = client.get("/", headers={"Accept-Language": "de-DE,de;q=0.9"}).get_data(
        as_text=True
    )
    assert CATALOGUE["de"]["heading"] in body
    assert 'lang="de"' in body


def test_a_regional_tag_falls_back_to_its_base_language(client):
    body = client.get("/", headers={"Accept-Language": "pt-BR"}).get_data(as_text=True)
    assert 'lang="pt"' in body


def test_an_unknown_language_falls_back_to_english(client):
    body = client.get("/", headers={"Accept-Language": "xx-YY"}).get_data(as_text=True)
    assert 'lang="en"' in body
    assert CATALOGUE["en"]["heading"] in body


def test_an_absent_header_falls_back_to_english(client):
    assert 'lang="en"' in client.get("/").get_data(as_text=True)


def test_the_query_override_beats_the_header(client):
    body = client.get("/?lang=ja", headers={"Accept-Language": "de"}).get_data(
        as_text=True
    )
    assert 'lang="ja"' in body


def test_an_unknown_override_does_not_break_the_page(client):
    body = client.get("/?lang=klingon", headers={"Accept-Language": "de"}).get_data(
        as_text=True
    )
    assert 'lang="de"' in body


def test_the_sweep_labels_are_localised(client):
    body = client.get("/?lang=de").get_data(as_text=True)
    assert json.dumps(CATALOGUE["de"]["st_done"], ensure_ascii=False) in body
    assert json.dumps(CATALOGUE["de"]["st_failed"], ensure_ascii=False) in body
