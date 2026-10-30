import sys

import atheris

with atheris.instrument_imports(include=["app"]):
    from app import handoff_target

SIBLINGS = ["https://logout.example.com", "http://logout.abcdefghijklmnop.onion"]


def test_one_input(data):
    marker = atheris.FuzzedDataProvider(data).ConsumeUnicodeNoSurrogates(512)
    target = handoff_target(SIBLINGS, marker)
    if target is not None and not any(
        target.startswith(f"{sibling}/?") for sibling in SIBLINGS
    ):
        raise AssertionError(f"hand-off left the configured siblings: {target!r}")


if __name__ == "__main__":
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()
