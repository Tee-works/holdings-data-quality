"""Paths and settings. Everything can be overridden with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLS_DIR = ROOT / "controls"
CONTRACTS_DIR = ROOT / "contracts"
SQL_DIR = ROOT / "sql"
TEMPLATES_DIR = ROOT / "templates"

# Legal & General Group Plc files its 13F reports under this SEC Central Index Key.
DEFAULT_CIK = "764068"
DEFAULT_FILER = "Legal & General Group Plc"
# A fixed start, so the window grows rather than slides: it always includes the reports
# filed in 2022, when 13F values were still in thousands of dollars. Set HDQ_SINCE=""
# to use a sliding window of HDQ_QUARTERS instead.
DEFAULT_SINCE = "2022-07-01"


@dataclass(frozen=True)
class Settings:
    cik: str
    filer_name: str
    quarters: int
    since: date | None
    raw_dir: Path
    warehouse: Path
    state_dir: Path
    site_dir: Path
    sample: bool = False

    @classmethod
    def from_env(cls, base: Path | None = None, sample: bool = False) -> Settings:
        base = Path(base or os.environ.get("HDQ_HOME", ROOT))
        sub = "sample" if sample else "sec"
        if sample:
            cik, filer = "0", "Example Group Plc (synthetic sample)"
        else:
            cik = os.environ.get("HDQ_CIK", DEFAULT_CIK).lstrip("0")
            filer = os.environ.get("HDQ_FILER", DEFAULT_FILER)
        return cls(
            cik=cik,
            filer_name=filer,
            quarters=int(os.environ.get("HDQ_QUARTERS", "16")),
            since=_since(sample),
            raw_dir=base / "data" / sub / "raw",
            warehouse=base / "data" / sub / "warehouse.duckdb",
            state_dir=base / ("state-sample" if sample else "state"),
            site_dir=base / ("site-sample" if sample else "site"),
            sample=sample,
        )


def _since(sample: bool) -> date | None:
    value = os.environ.get("HDQ_SINCE", DEFAULT_SINCE).strip()
    return date.fromisoformat(value) if value and not sample else None


def user_agent() -> str:
    """SEC asks automated clients to identify themselves with a name and contact email."""
    ua = os.environ.get("SEC_USER_AGENT", "").strip()
    if not ua or "@" not in ua:
        raise SystemExit(
            "Set SEC_USER_AGENT to 'Your Name your.email@example.com' "
            "(SEC fair access policy: https://www.sec.gov/os/accessing-edgar-data)"
        )
    return ua
