#!/usr/bin/env python
"""Check that this machine's copy of the astro knowledge base works. Changes nothing.

One line per check: OK, WARN (works, something is behind) or FAIL (fix it first).
  setup     Python packages; the search model at its pinned revision; scripts/config.local
            (KB_PYTHON, readable by you only); git config github.user; the pre-commit check;
            .mcp.json, the search server script and the Claude Code hooks;
  content   the checks of /sync, without updating anything: skeleton against GitHub, both
            Keeper libraries, conflict copies, drafts, code pins, the search index;
  works     the note checker; a search through the index (loads the model); the search
            server started as Claude Code starts it, asked for one Gaia column.

    python scripts/doctor.py           # everything (about half a minute)
    python scripts/doctor.py --fast    # no model, no server, no network
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")              # the doctor never downloads
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync  # noqa: E402
from kb_common import KEEPER, ROOT  # noqa: E402

say = sync.say
PACKAGES = ["yaml", "requests", "bs4", "pymupdf", "lancedb", "sentence_transformers", "torch", "mcp",
            "numpy", "astropy", "astroquery", "matplotlib", "nbconvert", "tqdm"]
PROBE = ("nss_two_body_orbit", "period")      # a column every Gaia release since DR3 has


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def config_local_python() -> str | None:
    """The KB_PYTHON line of scripts/config.local (the file may hold tokens: nothing else is read)."""
    f = ROOT / "scripts" / "config.local"
    for line in f.read_text(encoding="utf-8").splitlines() if f.exists() else []:
        if line.strip().startswith("KB_PYTHON"):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            return os.path.expanduser(v)
    return None


def hf_cache() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def setup_checks() -> None:
    missing = [m for m in PACKAGES if importlib.util.find_spec(m) is None]   # found, not imported
    say("OK" if not missing else "FAIL", f"Python {sys.version.split()[0]}",
        f"missing: {', '.join(missing)}: bash scripts/setup.sh" if missing else sys.executable)

    from kb_pkg import config
    model, rev = config.embedding_model(), config.model_revision()
    snap = hf_cache() / f"models--{model.replace('/', '--')}" / "snapshots" / str(rev)
    if snap.is_dir() and any(snap.glob("*.safetensors")) or (snap / "config.json").exists():
        say("OK", "search model", f"{model} at the pinned revision {str(rev)[:10]}")
    else:
        have = sorted(p.name[:10] for p in snap.parent.iterdir()) if snap.parent.exists() else []
        say("FAIL", "search model", f"{model} revision {str(rev)[:10]} not downloaded"
            + (f" (have {', '.join(have)})" if have else "") + ": bash scripts/setup.sh")

    cl = ROOT / "scripts" / "config.local"
    py = config_local_python()
    if not cl.exists() or not py:
        say("FAIL", "scripts/config.local", "no KB_PYTHON line: the search server cannot start; bash scripts/setup.sh")
    elif not Path(py).exists():
        say("FAIL", "scripts/config.local", f"KB_PYTHON points to {py}, which does not exist: bash scripts/setup.sh")
    else:
        loose = stat.S_IMODE(cl.stat().st_mode) & 0o077
        say("WARN" if loose else "OK", "scripts/config.local",
            f"KB_PYTHON = {py}" + ("; readable by others: chmod 600 scripts/config.local" if loose else ""))

    user = git("config", "github.user")
    say("OK" if user else "FAIL", "git config github.user",
        user or "not set: git config github.user <your GitHub name> (notes and branches carry it)")
    hook = ROOT / ".git" / "hooks" / "pre-commit"
    ok = hook.exists() and "check_public.py" in hook.read_text(errors="replace")
    say("OK" if ok else "WARN", "pre-commit check", "installed" if ok else "not installed: bash scripts/setup.sh")

    mcp = ROOT / ".mcp.json"
    try:
        servers = json.loads(mcp.read_text())["mcpServers"]
        ok = "astro-kb" in servers and (ROOT / "scripts" / "kb_server.sh").exists()
    except (OSError, ValueError, KeyError):
        ok = False
    say("OK" if ok else "FAIL", ".mcp.json", "search server 'astro-kb' declared" if ok
        else "the search server is not declared: /sync the skeleton")
    try:
        hooks = json.loads((ROOT / ".claude" / "settings.json").read_text()).get("hooks", {})
        ok = {"SessionStart", "PreToolUse"} <= set(hooks)
    except (OSError, ValueError):
        ok = False
    say("OK" if ok else "FAIL", "Claude Code hooks", "session start and one-writer hooks set" if ok
        else ".claude/settings.json lacks the hooks: /sync the skeleton")


def checker() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_vault.py")], cwd=ROOT,
                       capture_output=True, text=True)
    last = (r.stdout.strip().splitlines() or [""])[-1]
    say("OK" if r.returncode == 0 else "FAIL", "note checker", last + ("" if r.returncode == 0 else ": run /resolve or fix the notes named"))


def search() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    try:
        from kb_pkg import config
        from kb_pkg.embed import Embedder
        from kb_pkg.store import Store
        store = Store(config.INDEX_DIR)
        hits = store.search(Embedder(device="cpu").embed_query("orbital period of astrometric binaries"), 3)
        say("OK" if hits else "FAIL", "search", f"{len(hits)} passages, first from '{hits[0]['source_id'][:60]}'"
            if hits else "no passages found: run /sync")
    except Exception as e:                                       # noqa: BLE001
        say("FAIL", "search", f"{type(e).__name__}: {str(e)[:200]}")


def server(timeout: float = 120) -> None:
    """Start scripts/kb_server.sh as Claude Code does (.mcp.json) and call lookup_column."""
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def probe():
        params = StdioServerParameters(command="bash", args=[str(ROOT / "scripts" / "kb_server.sh")], cwd=str(ROOT),
                                       env=dict(os.environ))     # Claude Code passes its environment on
        with open(os.devnull, "w") as quiet:
            async with stdio_client(params, errlog=quiet) as (r, w):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    tools = {t.name for t in (await s.list_tools()).tools}
                    res = await s.call_tool("lookup_column", {"table": PROBE[0], "column": PROBE[1]})
                    return tools, json.loads(res.content[0].text) if res.content else {}

    try:
        tools, rec = asyncio.run(asyncio.wait_for(probe(), timeout))
    except BaseException as e:                                   # noqa: BLE001
        while isinstance(e, BaseExceptionGroup) and e.exceptions:   # the first real error
            e = e.exceptions[0]
        if isinstance(e, KeyboardInterrupt):
            raise
        say("FAIL", "search server", f"did not answer ({type(e).__name__}: {str(e)[:160] or 'closed'}); "
                                     "check KB_PYTHON in scripts/config.local")
        return
    want = {"search_kb", "lookup_column", "find_columns", "get_neighbors"}
    if not want <= tools:
        say("FAIL", "search server", f"tools missing: {', '.join(sorted(want - tools))}")
    elif not rec.get("found"):
        say("FAIL", "search server", f"lookup_column({PROBE[0]}, {PROBE[1]}) found nothing: is keeper/parsed/gaia synced?")
    else:
        say("OK", "search server", f"answers; {PROBE[0]}.{PROBE[1]} is in {', '.join(sorted(rec['records']))}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fast", action="store_true", help="no model, no server, no network")
    ap.add_argument("--full", action="store_true", help="also compare the SHA-256 of every Keeper file")
    a = ap.parse_args()
    print("-- setup")
    setup_checks()
    print("-- content")
    sync.skeleton(offline=a.fast, apply=False)
    sync.keeper(a.full)
    sync.code(offline=a.fast, apply=False)
    if KEEPER.is_dir() or (ROOT / "index").exists():
        sync.index(build=False, apply=False)
    print("-- works")
    checker()
    if not a.fast:
        search()
        server()
    fails = sum(1 for l, _, _ in sync.LINES if l in ("FAIL", "STOP"))
    warns = sum(1 for l, _, _ in sync.LINES if l == "WARN")
    print(f"\n{len(sync.LINES)} checks: {fails} FAIL, {warns} WARN"
          + ("" if fails or warns else ": this machine is ready"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
