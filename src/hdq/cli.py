"""Command line entry point.

hdq fetch      download 13F filings from SEC EDGAR (needs SEC_USER_AGENT)
hdq build      parse downloaded filings into DuckDB
hdq check      run the controls, update the issue log, write reporting outputs
hdq site       build the static dashboard
hdq all        fetch, build, check, site
hdq demo       the same on the bundled synthetic sample, no network needed
hdq docs       regenerate docs/controls.md (catalogue and runbooks) from the control headers
"""

from __future__ import annotations

import argparse
import shutil
import sys

from hdq import check, docs, edgar, load, sample, site
from hdq.config import ROOT, Settings


def _sample_settings() -> Settings:
    s = Settings.from_env(sample=True)
    for path in (s.raw_dir, s.state_dir, s.site_dir):
        shutil.rmtree(path, ignore_errors=True)
    sample.write_sample(s.raw_dir)
    return s


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hdq", description=__doc__.split("\n")[0])
    parser.add_argument(
        "command",
        choices=["fetch", "build", "check", "site", "all", "demo", "docs", "snowflake"],
    )
    parser.add_argument("--sample", action="store_true", help="snowflake: use the demo data")
    args = parser.parse_args(argv)

    if args.command == "snowflake":
        from hdq import snowflake

        out = snowflake.run(Settings.from_env(sample=args.sample))
        print(f"parity {'passed' if out['parity'] else 'FAILED'}; report: {out['report']}")
        return 0 if out["parity"] else 1

    if args.command == "docs":
        path = docs.write(ROOT / "docs" / "controls.md")
        print(f"wrote {path}")
        return 0

    settings = _sample_settings() if args.command == "demo" else Settings.from_env()
    if args.command in ("fetch", "all"):
        print("fetch:", edgar.fetch(settings))
    if args.command in ("build", "all", "demo"):
        print("build:", load.build(settings))
    if args.command in ("check", "all", "demo"):
        print(check.summary(check.run(settings)))
    if args.command in ("site", "all", "demo"):
        print("site:", site.build(settings))
    return 0


if __name__ == "__main__":
    sys.exit(main())
