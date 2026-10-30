"""Contract of the reports the conductor posts to the page that frames it.

The consumer lives in another repository - infinito-nexus-core injects a
listener into Keycloak's logout page - so the message shape is a cross-repo
interface with nothing else holding it in place. Renaming a field here is a
silent break there.

The script is exercised as served: lifted out of the rendered template.
"""

import re
import shutil
import subprocess
import textwrap

import pytest

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


HANDOFF_DRIVER = textwrap.dedent(
    """
    const assert = require("assert");
    const script = require("fs").readFileSync(process.argv[2], "utf8");
    const PARENT = process.argv[3];
    const TARGET = process.argv[4];
    const PROBE = `${new URL(TARGET).origin}/`;

    function harness(framed, siblingUp = true) {
      const posted = [];
      const replaced = [];
      const pending = [];
      const probes = [];
      const top = {};
      global.document = {
        referrer: "",
        getElementById() { return { textContent: "", className: "", style: {} }; },
      };
      global.window = {
        self: framed ? {} : top,
        top,
        location: {
          search: `?iss=${PARENT}/realms/x`,
          replace(url) { replaced.push(url); },
        },
        parent: {
          postMessage(payload, origin) { posted.push({ payload, origin }); },
        },
      };
      global.fetch = (url, init) => {
        if (url === PROBE) {
          probes.push(init);
          return siblingUp
            ? Promise.resolve({ type: "opaque" })
            : Promise.reject(new TypeError("Failed to fetch"));
        }
        return new Promise((resolve) => {
          pending.push(() => resolve({ ok: true }));
        });
      };

      eval(script);
      return {
        posted,
        replaced,
        probes,
        answer: () => pending.splice(0).forEach((f) => f()),
      };
    }

    const settle = async () => {
      for (let i = 0; i < 30; i += 1) { await new Promise((r) => setImmediate(r)); }
    };

    (async () => {
      {
        const h = harness(false);
        await settle();
        assert.deepStrictEqual(h.replaced, [], "the hand-off waits for the sweep");
        assert.strictEqual(h.probes.length, 0, "and so does the probe");
        h.answer();
        await settle();
        assert.deepStrictEqual(h.replaced, [TARGET], "a top-level conductor travels on");
        assert.strictEqual(h.posted.length, 0, "and reports to nobody");
        assert.strictEqual(h.probes[0].mode, "no-cors");
        assert.strictEqual(h.probes[0].credentials, "omit", "the probe carries no cookies");
      }

      {
        const h = harness(false, false);
        h.answer();
        await settle();
        assert.deepStrictEqual(
          h.replaced, [], "a sibling the browser cannot reach keeps the conductor on its own page",
        );
      }

      {
        const h = harness(true, false);
        h.answer();
        await settle();
        const kinds = h.posted.map((m) => m.payload.type);
        assert.deepStrictEqual(
          kinds, ["start", "host", "host", "done"], `an unreachable sibling is not reported: ${kinds}`,
        );
      }

      {
        const h = harness(true);
        h.answer();
        await settle();
        assert.deepStrictEqual(
          h.replaced, [], "a framed conductor leaves the top-level navigation to its parent",
        );
        const kinds = h.posted.map((m) => m.payload.type);
        assert.deepStrictEqual(kinds, ["start", "host", "host", "done", "handoff"], `got ${kinds}`);
        const handoff = h.posted[4];
        assert.strictEqual(handoff.payload.url, TARGET);
        assert.strictEqual(handoff.payload.source, "universal-logout");
        assert.strictEqual(handoff.origin, PARENT, "the hand-off is addressed like every report");
      }

      console.log("OK");
    })();
    """
)


def _script(client, module, monkeypatch, siblings=()) -> str:
    monkeypatch.setattr(module, "DOMAINS", DOMAINS)
    monkeypatch.setattr(module, "SIBLINGS", list(siblings))
    html = client.get("/?lang=en").get_data(as_text=True)
    blocks = re.findall(
        r"<script>(.*?)</script>", html, flags=re.DOTALL | re.IGNORECASE
    )
    assert blocks, "no inline <script> block in the conductor template"
    return "\n".join(blocks)


def _run(tmp_path, script, driver, *args):
    script_file = tmp_path / "conductor.js"
    script_file.write_text(script)
    driver_file = tmp_path / "driver.js"
    driver_file.write_text(driver)
    return subprocess.run(
        ["node", str(driver_file), str(script_file), PARENT_ORIGIN, *args],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not available in PATH"
)
def test_the_conductor_reports_its_sweep_to_the_framing_page(
    tmp_path, client, module, monkeypatch
):
    assert module.TRANSLATIONS["en"]["st_done"] == LABEL_DONE
    assert module.TRANSLATIONS["en"]["st_failed"] == LABEL_FAILED
    script = _script(client, module, monkeypatch)

    proc = _run(tmp_path, script, DRIVER, LABEL_DONE)

    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout


@pytest.mark.skipif(
    shutil.which("node") is None, reason="node is not available in PATH"
)
def test_the_conductor_hands_off_to_its_sibling_once_the_sweep_is_done(
    tmp_path, client, module, monkeypatch
):
    sibling = "http://logout.abcdefghijklmnop.onion"
    script = _script(client, module, monkeypatch, siblings=[sibling])

    proc = _run(tmp_path, script, HANDOFF_DRIVER, f"{sibling}/?handoff=")

    assert proc.returncode == 0, proc.stderr
    assert "OK" in proc.stdout
