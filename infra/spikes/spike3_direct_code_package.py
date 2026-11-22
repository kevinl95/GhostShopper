#!/usr/bin/env python3
"""Spike 3: does the arm64 direct-code zip fit AgentCore limits, and does Nova Act start over CDP?

Resolves the "Direct code package" item in design.md.

Part 1 builds the zip for the `buyer` extra with
    uv pip install --python-platform aarch64-manylinux2014 --target <dir> ".[buyer]"
and reports compressed and uncompressed sizes against the 250 MB and 750 MB limits.

Part 2 attaches Nova Act to an AgentCore Browser session over CDP and loads a page, with no
act() call. It reports whether a local Chrome is installed. For a clean answer to "no local
Chrome", run this script in a container or VM without Chrome; the script records what it found.

Requirements: uv on PATH, plus bedrock-agentcore, nova-act, boto3 in the running environment.
NOVA_ACT_API_KEY must be set for part 2 (use your own key; it is never written to the result).

Usage:
    python infra/spikes/spike3_direct_code_package.py --region us-east-1
    python infra/spikes/spike3_direct_code_package.py --skip-nova-act     # size check only

Fallback if the zip is over a limit or Nova Act will not start: container artifact
(ContainerConfiguration). The decision is written to infra/spikes/results/spike3.md.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from _common import write_result

ROOT = Path(__file__).resolve().parents[2]
ZIP_LIMIT = 250 * 1024 * 1024
UNZIPPED_LIMIT = 750 * 1024 * 1024
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome")


def mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def build_zip(out_dir: Path) -> tuple[Path, int, int]:
    if not shutil.which("uv"):
        raise RuntimeError("uv is not on PATH (https://docs.astral.sh/uv/)")
    pkg = out_dir / "pkg"
    subprocess.run(
        [
            "uv", "pip", "install",
            "--python-platform", "aarch64-manylinux2014",
            "--python-version", "3.13",
            "--target", str(pkg),
            f"{ROOT}[buyer]",
        ],
        check=True,
    )  # fmt: skip
    # Drop bytecode caches; they only add size.
    for cache in pkg.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)
    zip_path = out_dir / "buyer.zip"
    uncompressed = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg.rglob("*")):
            if f.is_file():
                uncompressed += f.stat().st_size
                zf.write(f, f.relative_to(pkg))
    return zip_path, zip_path.stat().st_size, uncompressed


def nova_act_over_cdp(region: str) -> str:
    from bedrock_agentcore.tools.browser_client import browser_session
    from nova_act import NovaAct

    if not os.environ.get("NOVA_ACT_API_KEY"):
        raise RuntimeError("NOVA_ACT_API_KEY is not set")
    with browser_session(region) as client:
        ws_url, headers = client.generate_ws_headers()
        with NovaAct(
            cdp_endpoint_url=ws_url,
            cdp_headers=headers,
            starting_page="about:blank",
        ) as nova:
            nova.page.goto("https://example.com")
            return nova.page.title()


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--skip-nova-act", action="store_true")
    ap.add_argument("--keep-zip", default=None, help="copy the built zip to this path")
    args = ap.parse_args()

    lines: list[str] = []
    size_ok: bool | None = None
    try:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path, zsize, usize = build_zip(Path(tmp))
            if args.keep_zip:
                shutil.copy(zip_path, args.keep_zip)
        size_ok = zsize <= ZIP_LIMIT and usize <= UNZIPPED_LIMIT
        lines += [
            "## Package size (arm64, `buyer` extra)",
            "",
            f"- Compressed: {mb(zsize)} (limit {mb(ZIP_LIMIT)})",
            f"- Uncompressed: {mb(usize)} (limit {mb(UNZIPPED_LIMIT)})",
            f"- Within limits: **{'yes' if size_ok else 'NO'}**",
            "",
        ]
    except Exception as exc:
        lines += ["## Package size", "", f"Build failed: `{type(exc).__name__}: {exc}`", ""]
        size_ok = False

    chrome = [n for n in CHROME_NAMES if shutil.which(n)]
    nova_ok: bool | None = None
    if args.skip_nova_act:
        lines += ["## Nova Act over CDP", "", "Skipped (`--skip-nova-act`).", ""]
    else:
        try:
            title = nova_act_over_cdp(args.region)
            nova_ok = True
            lines += [
                "## Nova Act over CDP",
                "",
                f"- Attached to an AgentCore Browser session and loaded a page (title: `{title}`).",
                f"- Local Chrome binaries found on this machine: {', '.join(chrome) or 'none'}.",
                "- If Chrome was found, this run does not prove that Nova Act works without it. "
                "Re-run in a container without Chrome.",
                "",
            ]
        except Exception as exc:
            nova_ok = False
            lines += ["## Nova Act over CDP", "", f"Failed: `{type(exc).__name__}: {exc}`", ""]

    if size_ok and nova_ok is not False:
        decision = "Direct code zip is viable. Use `CodeConfiguration`."
    else:
        decision = (
            "Use the container artifact (`ContainerConfiguration`) as the fallback. "
            "Update infra/build_buyer.sh (task 12.1) and the design's packaging row."
        )
    lines += ["## Decision", "", decision]

    overall = None if (nova_ok is None and size_ok) else bool(size_ok and nova_ok is not False)
    path = write_result("spike3", overall, "Spike 3: direct code package", "\n".join(lines))
    print(
        f"spike 3: {'INCONCLUSIVE' if overall is None else 'PASS' if overall else 'FAIL'} ({path})"
    )
    return 0 if overall is not False else 1


if __name__ == "__main__":
    sys.exit(main())
