"""Cutoff-gated, role-separated read access to the DuckDB store.

- ``dev`` opens only ``dev.duckdb``, which holds burn-in and development seasons only.
- ``holdout`` opens ``holdout.duckdb`` (all seasons) and only from the exact frozen commit.

``as_of(table, t)`` returns rows whose reconstructed availability (``available_at``, see
docs/scope.md) is strictly before ``t``. Schedule metadata (meetings, sessions) is not gated.
"""

import subprocess
from datetime import datetime
from pathlib import Path

import duckdb

ROLES = ("dev", "holdout")
UNGATED = ("meetings", "sessions")
GATED = (
    "drivers",
    "laps",
    "stints",
    "pit",
    "race_control",
    "weather",
    "intervals",
    "position",
    "session_result",
    "starting_grid",
)


class AccessError(PermissionError):
    pass


def db_path(db_dir: Path, role: str) -> Path:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    return db_dir / f"{role}.duckdb"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise AccessError(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout.strip()


def verify_frozen(repo: Path, tag: str) -> str:
    """Return the frozen commit if HEAD is exactly ``tag``'s commit with a clean tree."""
    try:
        tagged = _git(repo, "rev-list", "-n", "1", tag)
    except AccessError as e:
        raise AccessError(f"freeze tag {tag!r} does not exist") from e
    head = _git(repo, "rev-parse", "HEAD")
    if head != tagged:
        raise AccessError(f"HEAD {head[:12]} is not the frozen commit {tagged[:12]} ({tag})")
    # Untracked (non-ignored) files count too: frozen means exactly the tagged tree.
    if _git(repo, "status", "--porcelain"):
        raise AccessError("working tree has uncommitted or untracked changes")
    return head


class Access:
    def __init__(
        self,
        role: str,
        db_dir: Path,
        *,
        dev_seasons: list[int],
        repo: Path | None = None,
        freeze_tag: str | None = None,
    ):
        """Open the role's database read-only; the holdout role verifies the frozen commit."""
        self.role = role
        self.frozen_commit = None
        if role == "holdout":
            if repo is None or freeze_tag is None:
                raise AccessError("holdout access requires the repository and freeze tag")
            self.frozen_commit = verify_frozen(repo, freeze_tag)
        self.con = duckdb.connect(str(db_path(db_dir, role)), read_only=True)
        self.con.sql("SET TimeZone = 'UTC'")
        if role == "dev":
            rows = self.con.sql("SELECT DISTINCT year FROM stg_sessions").fetchall()
            extra = sorted({r[0] for r in rows} - set(dev_seasons))
            if extra:
                self.con.close()
                raise AccessError(f"dev database contains seasons {extra}")

    def tables(self) -> list[str]:
        names = {r[0] for r in self.con.sql("SELECT view_name FROM duckdb_views()").fetchall()}
        return [t for t in UNGATED + GATED if f"stg_{t}" in names]

    def as_of(self, table: str, t: datetime) -> duckdb.DuckDBPyRelation:
        if t.tzinfo is None:
            raise ValueError("cutoff must be timezone-aware")
        if table in UNGATED:
            return self.con.sql(f"SELECT * FROM stg_{table}")
        if table not in GATED:
            raise ValueError(f"unknown table {table!r}")
        if table == "stints":
            # A stint ongoing at t has an unknown end: its lap_end is masked.
            return self.con.sql(
                "SELECT * EXCLUDE (end_available_at) REPLACE ("
                "CASE WHEN end_available_at < $t THEN lap_end END AS lap_end) "
                "FROM stg_stints WHERE available_at < $t",
                params={"t": t},
            )
        return self.con.sql(f"SELECT * FROM stg_{table} WHERE available_at < $t", params={"t": t})

    def race_start(self, session_key: int) -> datetime:
        """Pre-race checkpoint of a race session."""
        row = self.con.sql(
            "SELECT date_start FROM stg_sessions WHERE session_key = $k", params={"k": session_key}
        ).fetchall()
        if not row:
            raise KeyError(session_key)
        return row[0][0]

    def close(self) -> None:
        self.con.close()
