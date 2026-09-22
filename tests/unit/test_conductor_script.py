"""Contract of the reports the conductor posts to the page that frames it.

The consumer lives in another repository - infinito-nexus-core injects a
listener into Keycloak's logout page - so the message shape is a cross-repo
interface with nothing else holding it in place. Renaming a field here is a
silent break there.

The script is exercised as served: lifted out of the rendered template.
"""

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "templates" / "conductor.html.j2"
PARENT_ORIGIN = "https://auth.example.test"
DOMAINS = ["https://shop.example.test", "https://cloud.example.test"]
LABEL_DONE = "Signed out"
LABEL_FAILED = "Failed"

DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const PARENT = process.argv[3];

    function harness(opts) {
      opts = opts || {};
      const posted = [];
      const cells = {};
      const inits = {};
      const top = {};
      global.document = {
        referrer: opts.referrer === undefined ? "" : opts.referrer,
        getElementById(id) {
          if (opts.noCells) { return null; }
          cells[id] = cells[id] || { textContent: "", className: "", style: {} };
          return cells[id];
        },
      };
      const self = opts.framed === false ? top : {};
      global.window = {
        self,
        top,
        location: { search: opts.search === undefined ? `?iss=${PARENT}/realms/x` : opts.search },
        parent: {
          postMessage(payload, origin) {
            if (opts.postThrows) { throw new Error("postMessage refused"); }
            posted.push({ payload, origin });
          },
        },
      };
      global.fetch = (url, init) => {
        inits[url] = init;
        const failing = (opts.failing || []).some((h) => url.startsWith(h));
        if (opts.reject) { return Promise.reject(new Error("network")); }
        return Promise.resolve({ ok: !failing });
      };

      eval(script);
      return { posted, cells, inits };
    }

    const settle = async () => {
      for (let i = 0; i < 30; i += 1) { await new Promise((r) => setImmediate(r)); }
    };

    (async () => {
      {
        const h = harness({ failing: ["https://cloud.example.test"] });
        await settle();

        const kinds = h.posted.map((m) => m.payload.type);
        assert.deepStrictEqual(kinds, ["start", "host", "host", "done"], `got ${kinds}`);
        assert.ok(
          h.posted.every((m) => m.payload.source === "universal-logout"),
          "every message is tagged so a foreign frame cannot be mistaken for us",
        );
        assert.ok(
          h.posted.every((m) => m.origin === PARENT),
          "messages are addressed to the issuer origin, never to a wildcard",
        );
        assert.deepStrictEqual(h.posted[0].payload.domains.length, 2);

        const hosts = h.posted.filter((m) => m.payload.type === "host");
        assert.strictEqual(hosts.find((m) => m.payload.host.includes("shop")).payload.ok, true);
        assert.strictEqual(hosts.find((m) => m.payload.host.includes("cloud")).payload.ok, false);

        const done = h.posted[3].payload;
        assert.strictEqual(done.total, 2);
        assert.strictEqual(done.failed, 1, "done counts what stayed logged in");

        const url = Object.keys(h.inits).find((u) => u.includes("shop"));
        assert.strictEqual(h.inits[url].keepalive, true, "requests must survive the navigation");
        assert.strictEqual(h.inits[url].credentials, "include");
        assert.ok(url.includes("/logout?t="), "each request carries its own cache-buster");
      }

      {
        const h = harness({ search: "", referrer: `${PARENT}/realms/x/logout` });
        await settle();
        assert.ok(h.posted.length, "referrer is the fallback when iss is absent");
        assert.ok(h.posted.every((m) => m.origin === PARENT));
      }

      {
        const h = harness({ search: "", referrer: "" });
        await settle();
        assert.strictEqual(h.posted.length, 0, "no origin to trust means no message");
        assert.ok(Object.keys(h.inits).length, "but the sweep still runs");
      }

      {
        const h = harness({ framed: false });
        await settle();
        assert.strictEqual(h.posted.length, 0, "a standalone page reports to nobody");
        assert.ok(Object.keys(h.inits).length, "and still sweeps");
      }

      {
        const h = harness({ postThrows: true });
        await settle();
        assert.ok(
          Object.values(h.cells).every((c) => c.textContent.includes(process.argv[4])),
          "a refused postMessage must not derail the sweep or its table",
        );
      }

      {
        const h = harness({ noCells: true });
        await settle();
        const done = h.posted.find((m) => m.payload.type === "done");
        assert.ok(done, "done is sent even when the table is missing");
        assert.strictEqual(done.payload.failed, 0, "a missing cell is not a failed logout");
      }

      {
        const h = harness({ reject: true });
        await settle();
        const done = h.posted.find((m) => m.payload.type === "done");
        assert.strictEqual(done.payload.failed, 2, "a rejected fetch counts as failed");
      }

      console.log("OK");
    })();
    """
)


SUBSTITUTIONS = {
    "domains": DOMAINS,
    "st_done": LABEL_DONE,
    "st_failed": LABEL_FAILED,
}


def _render(match: re.Match) -> str:
    expression = match.group(0)
    for needle, value in SUBSTITUTIONS.items():
        if needle in expression:
            return json.dumps(value)
    raise AssertionError(
        f"the conductor script grew an expression this test cannot render: {expression}"
    )


def _script() -> str:
    html = TEMPLATE.read_text()
    blocks = re.findall(
        r"<script>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE
    )
    assert blocks, "no inline <script> block in the conductor template"
    body = "\n".join(blocks)
    body = re.sub(r"\{%.*?%\}", "", body, flags=re.DOTALL)
    return re.sub(r"\{\{.*?\}\}", _render, body, flags=re.DOTALL)


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not available in PATH"
)
def test_the_conductor_reports_its_sweep_to_the_framing_page(tmp_path):
    script = tmp_path / "conductor.js"
    script.write_text(_script())
    driver = tmp_path / "driver.js"
    driver.write_text(DRIVER)

    proc = subprocess.run(
        ["node", str(driver), str(script), PARENT_ORIGIN, LABEL_DONE],
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
