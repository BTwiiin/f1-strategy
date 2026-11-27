"""Offline, deterministic DuckDB build from the raw cache.

``raw_<endpoint>`` tables hold rows as returned, plus ``_source_url``, ``_response_hash`` and
``_loaded_at`` (the manifest retrieval time, so rebuilds are deterministic). ``stg_<endpoint>``
views add typed timestamps, season, session name and ``available_at``: the reconstructed time
at which a record became known on track (docs/scope.md), not its API publication time.
"""

import hashlib
import os
from pathlib import Path

import duckdb

from f1_strategy.data.access import AccessError, db_path, verify_frozen
from f1_strategy.data.openf1 import read_manifest

META = "_source_url, _response_hash, _loaded_at, filename"

# available_at of event tables stamped at the moment they occur.
_TIMESTAMPED = ("race_control", "weather", "intervals", "position")
# Pit durations are known only when the car leaves the pit lane.
_PIT_DURATIONS = ("lane_duration", "pit_duration", "stop_duration")


def _seconds(col: str) -> str:
    return f"to_microseconds(CAST({col} * 1e6 AS BIGINT))"


def _stg_views(con: duckdb.DuckDBPyConnection, present: set[str]) -> dict[str, str]:
    """Typed staging views, in dependency order, for the endpoints present in the cache.

    ``available_at`` is NULL when it cannot be reconstructed; such rows are never returned by
    ``as_of`` (conservative exclusion, counted in the coverage report).
    """

    def columns(table: str) -> set[str]:
        return {r[0] for r in con.sql(f"DESCRIBE raw_{table}").fetchall()}

    views = {
        "meetings": f"""
            SELECT * EXCLUDE ({META}) REPLACE (CAST(date_start AS TIMESTAMPTZ) AS date_start)
            FROM raw_meetings""",
        "sessions": f"""
            SELECT * EXCLUDE ({META}) REPLACE (
                CAST(date_start AS TIMESTAMPTZ) AS date_start,
                CAST(date_end AS TIMESTAMPTZ) AS date_end)
            FROM raw_sessions""",
        "drivers": f"""
            SELECT r.* EXCLUDE ({META}), s.year AS season, s.session_name,
                   s.date_start AS available_at
            FROM raw_drivers r JOIN stg_sessions s ON r.session_key = s.session_key""",
        # Lap completion = start + duration, else the next lap's start, else unknown.
        "laps": f"""
            SELECT r.* EXCLUDE ({META}) REPLACE (CAST(r.date_start AS TIMESTAMPTZ) AS date_start),
                   s.year AS season, s.session_name,
                   coalesce(
                       CAST(r.date_start AS TIMESTAMPTZ) + {_seconds("r.lap_duration")},
                       lead(CAST(r.date_start AS TIMESTAMPTZ)) OVER (
                           PARTITION BY r.session_key, r.driver_number ORDER BY r.lap_number)
                   ) AS available_at
            FROM raw_laps r JOIN stg_sessions s ON r.session_key = s.session_key""",
        # A stint is known from the start of its first lap and its end from the completion of
        # its last lap (end_available_at; the access layer masks lap_end until then).
        "stints": f"""
            SELECT r.* EXCLUDE ({META}), s.year AS season, s.session_name,
                   lf.date_start AS available_at, ll.available_at AS end_available_at
            FROM raw_stints r
            JOIN stg_sessions s ON r.session_key = s.session_key
            LEFT JOIN stg_laps lf ON lf.session_key = r.session_key
                AND lf.driver_number = r.driver_number AND lf.lap_number = r.lap_start
            LEFT JOIN stg_laps ll ON ll.session_key = r.session_key
                AND ll.driver_number = r.driver_number AND ll.lap_number = r.lap_end""",
    }
    for name in _TIMESTAMPED:
        views[name] = f"""
            SELECT r.* EXCLUDE ({META}) REPLACE (CAST(r.date AS TIMESTAMPTZ) AS date),
                   s.year AS season, s.session_name, CAST(r.date AS TIMESTAMPTZ) AS available_at
            FROM raw_{name} r JOIN stg_sessions s ON r.session_key = s.session_key"""
    if "pit" in present:
        durations = [c for c in _PIT_DURATIONS if c in columns("pit")]
        longest = f"greatest({', '.join(f'coalesce(r.{c}, 0)' for c in durations)}, 0)"
        views["pit"] = f"""
            SELECT r.* EXCLUDE ({META}) REPLACE (CAST(r.date AS TIMESTAMPTZ) AS date),
                   s.year AS season, s.session_name,
                   CAST(r.date AS TIMESTAMPTZ) + {_seconds(longest)} AS available_at
            FROM raw_pit r JOIN stg_sessions s ON r.session_key = s.session_key"""
    # Results are known only after the session has actually ended: the later of the scheduled
    # end, the last reconstructed lap completion and the last race-control message.
    ends = ["max(s.date_end)"]
    if "laps" in present:
        ends.append(
            "(SELECT max(available_at) FROM stg_laps l WHERE l.session_key = s.session_key)"
        )
    if "race_control" in present:
        ends.append(
            "(SELECT max(CAST(date AS TIMESTAMPTZ)) FROM raw_race_control c "
            "WHERE c.session_key = s.session_key)"
        )
    views["session_end"] = f"""
        SELECT s.session_key, greatest({", ".join(f"coalesce({e}, max(s.date_end))" for e in ends)})
               AS ended_at
        FROM stg_sessions s GROUP BY s.session_key"""
    for name in ("session_result", "starting_grid"):
        views[name] = f"""
            SELECT r.* EXCLUDE ({META}), s.year AS season, s.session_name,
                   e.ended_at AS available_at
            FROM raw_{name} r JOIN stg_sessions s ON r.session_key = s.session_key
            JOIN stg_session_end e ON e.session_key = r.session_key"""
    required = {"session_end": {"sessions"}}
    return {n: v for n, v in views.items() if (required.get(n, {n}) <= present)}


def raw_roots(raw_dir: Path, role: str) -> list[Path]:
    """Raw caches readable by a role: dev reads only its own; holdout reads both."""
    return [raw_dir / "dev"] if role == "dev" else [raw_dir / "dev", raw_dir / "holdout"]


def build(
    role: str,
    raw_dir: Path,
    db_dir: Path,
    *,
    allowed_seasons: list[int],
    repo: Path | None = None,
    freeze_tag: str | None = None,
) -> Path:
    """Rebuild ``<db_dir>/<role>.duckdb`` from the raw cache without network access."""
    if role == "holdout":
        if repo is None or freeze_tag is None:
            raise AccessError("holdout build requires the repository and freeze tag")
        verify_frozen(repo, freeze_tag)

    entries = []
    for root in raw_roots(raw_dir, role):
        entries += [(root, e) for e in read_manifest(root).values()]
    for _, e in entries:
        year = e["params"].get("year")
        if year is not None and year not in allowed_seasons:
            raise AccessError(f"{role} build refuses season {year} ({e['key']})")

    target = db_path(db_dir, role)
    tmp = target.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        con.sql("SET TimeZone = 'UTC'")
        cols = "path VARCHAR, url VARCHAR, sha VARCHAR, retrieved VARCHAR"
        con.sql(f"CREATE TEMP TABLE manifest ({cols})")
        by_endpoint: dict[str, list[str]] = {}
        for root, e in sorted(entries, key=lambda x: (str(x[0]), x[1]["key"])):
            if e["status"] != 200 or e["rows"] == 0:
                continue
            path = str((root / e["key"]).resolve())
            con.execute(
                "INSERT INTO manifest VALUES (?, ?, ?, ?)",
                [path, e["url"], e["sha256"], e["retrieved_at"]],
            )
            by_endpoint.setdefault(e["endpoint"], []).append(path)

        for endpoint, paths in sorted(by_endpoint.items()):
            files = ", ".join(f"'{p}'" for p in paths)
            con.sql(f"""
                CREATE TABLE raw_{endpoint} AS
                SELECT r.*, m.url AS _source_url, m.sha AS _response_hash,
                       CAST(m.retrieved AS TIMESTAMPTZ) AS _loaded_at
                FROM read_json([{files}], format = 'array', union_by_name = true,
                               filename = true) r
                JOIN manifest m ON r.filename = m.path""")
        for name, sql in _stg_views(con, set(by_endpoint)).items():
            con.sql(f"CREATE VIEW stg_{name} AS {sql}")
        _check_seasons(con, allowed_seasons)
    finally:
        con.close()
    os.replace(tmp, target)
    return target


def _check_seasons(con: duckdb.DuckDBPyConnection, allowed: list[int]) -> None:
    """Every row belongs to an allowed season (content check behind the request check)."""
    rows = con.sql("SELECT table_name FROM duckdb_tables() WHERE NOT temporary").fetchall()
    tables = {r[0] for r in rows}
    if "raw_sessions" not in tables:
        return
    bad = con.sql(
        f"SELECT DISTINCT year FROM raw_sessions WHERE year NOT IN ({', '.join(map(str, allowed))})"
    ).fetchall()
    if bad:
        raise AccessError(f"cache contains disallowed seasons {sorted(r[0] for r in bad)}")
    for t in sorted(tables - {"raw_sessions", "raw_meetings"}):
        orphans = con.sql(
            f"SELECT count(*) FROM {t} "
            "WHERE session_key NOT IN (SELECT session_key FROM raw_sessions)"
        ).fetchall()[0][0]
        if orphans:
            raise AccessError(f"{t} has {orphans} rows from sessions outside the allowed seasons")


def table_digests(path: Path) -> dict[str, str]:
    """SHA-256 of each table's ordered content, for rebuild determinism checks."""
    con = duckdb.connect(str(path), read_only=True)
    try:
        con.sql("SET TimeZone = 'UTC'")
        names = sorted(r[0] for r in con.sql("SELECT table_name FROM duckdb_tables()").fetchall())
        return {
            n: hashlib.sha256(
                repr(con.sql(f"SELECT * FROM {n} ORDER BY ALL").fetchall()).encode()
            ).hexdigest()
            for n in names
        }
    finally:
        con.close()


# Per-session data-quality counts in the coverage report: (label, table, condition).
_QUALITY = (
    ("laps without duration", "raw_laps", "lap_duration IS NULL"),
    ("laps never available", "stg_laps", "available_at IS NULL"),
    ("stints without compound", "raw_stints", "compound IS NULL OR compound = 'UNKNOWN'"),
    ("stints never available", "stg_stints", "available_at IS NULL"),
    ("stint ends never available", "stg_stints", "end_available_at IS NULL"),
)


def coverage_report(raw_root: Path, db: Path, include: list[str], endpoints: dict) -> str:
    """Markdown coverage per session and endpoint, from the manifest and the built database."""
    from f1_strategy.data.ingest import endpoints_for
    from f1_strategy.data.openf1 import query_key

    manifest = read_manifest(raw_root)
    con = duckdb.connect(str(db), read_only=True)
    try:
        sessions = con.sql(
            "SELECT year, meeting_key, session_key, session_name FROM stg_sessions "
            f"WHERE session_name IN ({', '.join(repr(s) for s in include)}) ORDER BY date_start"
        ).fetchall()
        names = {r[0] for r in con.sql("SELECT table_name FROM duckdb_tables()").fetchall()}
        names |= {r[0] for r in con.sql("SELECT view_name FROM duckdb_views()").fetchall()}
        counts = {
            label: dict(
                con.sql(
                    f"SELECT session_key, count(*) FILTER ({cond}) FROM {t} GROUP BY 1"
                ).fetchall()
            )
            if t in names
            else {}
            for label, t, cond in _QUALITY
        }
    finally:
        con.close()

    requested = {e["params"].get("session_key") for e in manifest.values()}
    skipped = sum(1 for row in sessions if row[2] not in requested)
    sessions = [row for row in sessions if row[2] in requested]
    lines = [
        f"Included sessions without any requested data: {skipped}",
        "",
        "| season | meeting | session | name | missing endpoints | empty endpoints "
        + "".join(f"| {label} " for label, _, _ in _QUALITY)
        + "|",
        "|---" * (6 + len(_QUALITY)) + "|",
    ]
    for year, meeting, key, name in sessions:
        missing, empty = [], []
        for ep in endpoints_for(name, endpoints):
            e = manifest.get(f"{ep}/{query_key(ep, {'session_key': key})}.json")
            if e is None:
                missing.append(ep)
            elif e["rows"] == 0:
                empty.append(ep)
        lines.append(
            f"| {year} | {meeting} | {key} | {name} | {', '.join(missing) or '—'} "
            f"| {', '.join(empty) or '—'} "
            + "".join(f"| {counts[label].get(key, '—')} " for label, _, _ in _QUALITY)
            + "|"
        )
    return "\n".join(lines) + "\n"
