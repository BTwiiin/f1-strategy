"""M2 ingestion, offline build and cutoff-gated access, against a fake OpenF1 API."""

import json
import subprocess
import urllib.parse
from datetime import UTC, datetime, timedelta

import pytest

from f1_strategy import config
from f1_strategy.data import build as build_mod
from f1_strategy.data.access import Access, AccessError, verify_frozen
from f1_strategy.data.ingest import ingest
from f1_strategy.data.openf1 import Client, FetchError, RateLimiter, read_manifest

DATA_CFG = config.load("data")
DEV = [2023, 2024]
T0 = datetime(2024, 3, 2, 15, 0, tzinfo=UTC)


def ts(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).isoformat()


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def fake_api(year: int = 2024) -> dict[tuple[str, tuple], list[dict]]:
    """One meeting: practice, qualifying, a sprint (excluded) and a race (session 10).

    Driver 1 in the race: laps 1-6 of 90 s from minute 3; lap 4 has no duration;
    stint 1 = laps 1-3 (MEDIUM), stint 2 = laps 4-6 (HARD).
    """

    def session(key, name, start, end):
        return {
            "session_key": key,
            "meeting_key": 1,
            "session_name": name,
            "year": year,
            "date_start": ts(start),
            "date_end": ts(end),
            "is_cancelled": False,
        }

    race = 10
    laps = [
        {
            "session_key": race,
            "meeting_key": 1,
            "driver_number": 1,
            "lap_number": n,
            "date_start": ts(3 + 1.5 * (n - 1)),
            "lap_duration": None if n == 4 else 90.0,
        }
        for n in range(1, 7)
    ]
    base = {"session_key": race, "meeting_key": 1}
    return {
        ("meetings", (("year", year),)): [
            {"meeting_key": 1, "year": year, "date_start": ts(-3000)}
        ],
        ("sessions", (("year", year),)): [
            session(8, "Practice 1", -2880, -2820),
            session(9, "Qualifying", -1440, -1380),
            session(11, "Sprint", -1200, -1170),
            session(race, "Race", 0, 120),
        ],
        ("laps", (("session_key", race),)): laps,
        ("stints", (("session_key", race),)): [
            {
                **base,
                "driver_number": 1,
                "stint_number": 1,
                "lap_start": 1,
                "lap_end": 3,
                "compound": "MEDIUM",
                "tyre_age_at_start": 3,
            },
            {
                **base,
                "driver_number": 1,
                "stint_number": 2,
                "lap_start": 4,
                "lap_end": 6,
                "compound": "HARD",
                "tyre_age_at_start": 0,
            },
        ],
        ("weather", (("session_key", race),)): [
            {**base, "date": ts(m), "track_temperature": 40.0 + m} for m in (0, 5, 10)
        ],
        ("race_control", (("session_key", race),)): [
            {**base, "date": ts(6), "category": "SafetyCar", "message": "SAFETY CAR DEPLOYED"}
        ],
        ("pit", (("session_key", race),)): [
            {**base, "date": ts(7.5), "driver_number": 1, "lap_number": 3, "lane_duration": 22.0}
        ],
        ("intervals", (("session_key", race),)): [
            {**base, "date": ts(m), "driver_number": 1, "interval": 1.0 + m} for m in (4, 9)
        ],
        ("session_result", (("session_key", race),)): [{**base, "driver_number": 1, "position": 1}],
        ("drivers", (("session_key", race),)): [{**base, "driver_number": 1, "team_name": "X"}],
    }


class FakeFetch:
    def __init__(self, api, fail_after=None, statuses=None):
        self.api, self.fail_after, self.statuses = api, fail_after, list(statuses or [])
        self.urls = []

    def __call__(self, url, timeout):
        if self.fail_after is not None and len(self.urls) >= self.fail_after:
            raise KeyboardInterrupt  # simulated crash mid-ingestion
        self.urls.append(url)
        if self.statuses:
            return self.statuses.pop(0), b"{}"
        parsed = urllib.parse.urlparse(url)
        endpoint = parsed.path.rsplit("/", 1)[-1]
        params = tuple(sorted((k, int(v)) for k, v in urllib.parse.parse_qsl(parsed.query)))
        rows = self.api.get((endpoint, params))
        if rows is None:
            return 404, b'{"detail": "No results found."}'
        return 200, json.dumps(rows).encode()


def make_client(root, fetch):
    limiter = RateLimiter(100, 1000, clock=lambda: 0.0, sleep=lambda s: None)
    return Client(root, "https://api.test/v1", limiter, fetch=fetch, sleep=lambda s: None)


@pytest.fixture
def dev_db(tmp_path):
    raw, db = tmp_path / "raw", tmp_path / "db"
    ingest(make_client(raw / "dev", FakeFetch(fake_api())), [2024], DATA_CFG)
    path = build_mod.build("dev", raw, db, allowed_seasons=DEV)
    acc = Access("dev", db, dev_seasons=DEV)
    yield acc, raw, db, path
    acc.close()


# --- client -------------------------------------------------------------------------------


def test_rate_limiter_enforces_per_second_and_per_minute():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s

    limiter = RateLimiter(3, 5, clock=lambda: now[0], sleep=sleep)
    sent = []
    for _ in range(6):
        limiter.wait()
        sent.append(now[0])
    assert sent[3] - sent[0] >= 1  # 4th request waits for the per-second window
    assert sent[5] - sent[0] >= 60  # 6th request waits for the per-minute window


def test_cache_hit_and_resume_make_no_request(tmp_path):
    fetch = FakeFetch(fake_api())
    client = make_client(tmp_path, fetch)
    rows = client.get("sessions", {"year": 2024})
    assert client.get("sessions", {"year": 2024}) == rows
    assert len(fetch.urls) == 1
    again = FakeFetch(fake_api())
    assert make_client(tmp_path, again).get("sessions", {"year": 2024}) == rows
    assert again.urls == []


def test_empty_result_is_cached_as_empty(tmp_path):
    client = make_client(tmp_path, FakeFetch(fake_api()))
    assert client.get("laps", {"session_key": 999}) == []
    entry = next(iter(read_manifest(tmp_path).values()))
    assert entry["status"] == 404 and entry["rows"] == 0


def test_retry_with_backoff_on_429(tmp_path):
    slept = []
    fetch = FakeFetch(fake_api(), statuses=[429, 503])
    limiter = RateLimiter(100, 1000, clock=lambda: 0.0, sleep=lambda s: None)
    client = Client(tmp_path, "https://api.test/v1", limiter, fetch=fetch, sleep=slept.append)
    assert client.get("sessions", {"year": 2024})
    assert slept == [2.0, 4.0]
    assert len(read_manifest(tmp_path)) == 1


def test_non_retryable_error_is_not_cached(tmp_path):
    client = make_client(tmp_path, FakeFetch(fake_api(), statuses=[400]))
    with pytest.raises(FetchError):
        client.get("sessions", {"year": 2024})
    assert read_manifest(tmp_path) == {}


def test_interrupted_ingestion_resumes(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        ingest(make_client(tmp_path, FakeFetch(fake_api(), fail_after=5)), [2024], DATA_CFG)
    done = len(read_manifest(tmp_path))
    resumed = FakeFetch(fake_api())
    ingest(make_client(tmp_path, resumed), [2024], DATA_CFG)
    complete = FakeFetch(fake_api())
    ingest(make_client(tmp_path / "fresh", complete), [2024], DATA_CFG)
    assert done == 5
    assert len(resumed.urls) == len(complete.urls) - done


def test_ingestion_plan_selects_sessions_and_endpoints(tmp_path):
    fetch = FakeFetch(fake_api())
    n = ingest(make_client(tmp_path, fetch), [2024], DATA_CFG)
    assert n == 3  # sprint excluded
    requested = {
        (e["endpoint"], e["params"].get("session_key")) for e in read_manifest(tmp_path).values()
    }
    ep = DATA_CFG["endpoints"]
    assert {e for e, k in requested if k == 10} == set(ep["every_session"] + ep["race"])
    assert {e for e, k in requested if k == 9} == set(ep["every_session"] + ep["qualifying"])
    assert {e for e, k in requested if k == 8} == set(ep["every_session"])
    assert not any(k == 11 for _, k in requested)


# --- build --------------------------------------------------------------------------------


def test_rebuild_is_offline_and_deterministic(dev_db, tmp_path):
    _, raw, db, path = dev_db
    first = build_mod.table_digests(path)
    second = build_mod.table_digests(build_mod.build("dev", raw, db, allowed_seasons=DEV))
    assert first == second
    assert {"raw_laps", "raw_stints", "raw_sessions"} <= set(first)


def test_loaded_at_comes_from_manifest(dev_db):
    acc, raw, _, _ = dev_db
    manifest = {e["url"]: e["retrieved_at"] for e in read_manifest(raw / "dev").values()}
    url, loaded = acc.con.sql("SELECT _source_url, _loaded_at FROM raw_laps LIMIT 1").fetchall()[0]
    assert loaded == datetime.fromisoformat(manifest[url])


def test_dev_build_refuses_holdout_season_request(tmp_path):
    raw = tmp_path / "raw"
    ingest(make_client(raw / "dev", FakeFetch(fake_api(2025))), [2025], DATA_CFG)
    with pytest.raises(AccessError, match="2025"):
        build_mod.build("dev", raw, tmp_path / "db", allowed_seasons=DEV)


def test_dev_build_refuses_holdout_season_content(tmp_path):
    # A 2025 session returned under a 2024 request is caught by the content check.
    api = fake_api(2025)
    api[("sessions", (("year", 2024),))] = api.pop(("sessions", (("year", 2025),)))
    api[("meetings", (("year", 2024),))] = api.pop(("meetings", (("year", 2025),)))
    raw = tmp_path / "raw"
    ingest(make_client(raw / "dev", FakeFetch(api)), [2024], DATA_CFG)
    with pytest.raises(AccessError, match="2025"):
        build_mod.build("dev", raw, tmp_path / "db", allowed_seasons=DEV)


def test_dev_build_never_reads_holdout_cache(tmp_path):
    raw = tmp_path / "raw"
    ingest(make_client(raw / "dev", FakeFetch(fake_api())), [2024], DATA_CFG)
    ingest(make_client(raw / "holdout", FakeFetch(fake_api(2025))), [2025], DATA_CFG)
    path = build_mod.build("dev", raw, tmp_path / "db", allowed_seasons=DEV)
    acc = Access("dev", tmp_path / "db", dev_seasons=DEV)
    assert acc.as_of("sessions", at(0)).aggregate("max(year)").fetchall()[0][0] == 2024
    acc.close()
    assert path.name == "dev.duckdb"


def test_coverage_report_lists_missing_and_empty_endpoints(dev_db):
    _, raw, _, path = dev_db
    report = build_mod.coverage_report(
        raw / "dev", path, DATA_CFG["sessions"]["include"], DATA_CFG["endpoints"]
    )
    race = next(line for line in report.splitlines() if "| Race |" in line)
    assert "position" in race  # empty in the fake API
    assert "| 1 |" in race  # one lap without duration


# --- access -------------------------------------------------------------------------------


def test_dev_access_rejects_database_with_holdout_season(tmp_path):
    raw = tmp_path / "raw"
    ingest(make_client(raw / "dev", FakeFetch(fake_api(2025))), [2025], DATA_CFG)
    build_mod.build("dev", raw, tmp_path / "db", allowed_seasons=[2025])  # misbuilt store
    with pytest.raises(AccessError, match="2025"):
        Access("dev", tmp_path / "db", dev_seasons=DEV)


def test_holdout_access_and_build_require_frozen_commit(tmp_path):
    with pytest.raises(AccessError):
        Access("holdout", tmp_path, dev_seasons=DEV)
    with pytest.raises(AccessError):
        build_mod.build("holdout", tmp_path / "raw", tmp_path / "db", allowed_seasons=DEV)
    with pytest.raises(AccessError, match="does not exist"):
        build_mod.build(
            "holdout",
            tmp_path / "raw",
            tmp_path / "db",
            allowed_seasons=DEV,
            repo=_repo(tmp_path / "repo"),
            freeze_tag="freeze-m7",
        )


def _repo(path):
    path.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (path / "f.txt").write_text("a")
    git("add", "f.txt")
    git("commit", "-qm", "a")
    return path


def test_verify_frozen_requires_exact_commit_and_clean_tree(tmp_path):
    repo = _repo(tmp_path / "repo")
    subprocess.run(["git", "-C", str(repo), "tag", "freeze-m7"], check=True)
    head = verify_frozen(repo, "freeze-m7")
    assert len(head) == 40
    (repo / "f.txt").write_text("changed")
    with pytest.raises(AccessError, match="uncommitted or untracked"):
        verify_frozen(repo, "freeze-m7")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "b"], check=True)
    with pytest.raises(AccessError, match="not the frozen commit"):
        verify_frozen(repo, "freeze-m7")


def test_as_of_hides_records_after_cutoff(dev_db):
    acc, *_ = dev_db
    t = at(8)
    laps = [r[0] for r in acc.as_of("laps", t).project("lap_number").order("lap_number").fetchall()]
    assert laps == [1, 2, 3]  # lap 3 completes at minute 7.5; lap 4 at minute 9 (next start)
    assert len(acc.as_of("weather", t).fetchall()) == 2
    assert len(acc.as_of("race_control", t).fetchall()) == 1
    assert len(acc.as_of("pit", t).fetchall()) == 1
    assert len(acc.as_of("intervals", t).fetchall()) == 1
    assert acc.as_of("session_result", t).fetchall() == []
    assert len(acc.as_of("session_result", at(121)).fetchall()) == 1
    assert len(acc.as_of("drivers", t).fetchall()) == 1


def test_lap_without_duration_becomes_available_at_next_lap_start(dev_db):
    acc, *_ = dev_db
    visible = acc.as_of("laps", at(9.01)).filter("lap_number = 4").fetchall()
    assert visible and acc.as_of("laps", at(8.99)).filter("lap_number = 4").fetchall() == []


def test_stint_end_is_masked_while_ongoing(dev_db):
    acc, *_ = dev_db

    def stints(t):
        rel = acc.as_of("stints", t).project("stint_number, lap_end, tyre_age_at_start")
        return rel.order("stint_number").fetchall()

    assert stints(at(5)) == [(1, None, 3)]  # stint 1 ongoing: end unknown
    assert stints(at(8)) == [(1, 3, 3), (2, None, 0)]  # lap 3 done at 7.5; stint 2 from 7.5
    assert stints(at(13)) == [(1, 3, 3), (2, 6, 0)]  # lap 6 done at 12


def test_future_rewrite_does_not_change_past_views(tmp_path):
    t = at(8)

    def views(api, name):
        raw, db = tmp_path / name / "raw", tmp_path / name / "db"
        ingest(make_client(raw / "dev", FakeFetch(api)), [2024], DATA_CFG)
        build_mod.build("dev", raw, db, allowed_seasons=DEV)
        acc = Access("dev", db, dev_seasons=DEV)
        out = {tbl: sorted(map(repr, acc.as_of(tbl, t).fetchall())) for tbl in acc.tables()}
        acc.close()
        return out

    original = fake_api()
    rewritten = fake_api()
    race = (("session_key", 10),)
    for lap in rewritten[("laps", race)]:
        if lap["lap_number"] >= 5:
            lap["lap_duration"] = 120.0
    for row in rewritten[("weather", race)]:
        if row["date"] > t.isoformat():
            row["track_temperature"] = 0.0
    rewritten[("stints", race)][1]["lap_end"] = 5
    rewritten[("session_result", race)][0]["position"] = 20
    assert views(original, "a") == views(rewritten, "b")


def test_cutoff_must_be_timezone_aware(dev_db):
    acc, *_ = dev_db
    with pytest.raises(ValueError):
        acc.as_of("laps", datetime(2024, 3, 2, 15, 8))
    assert acc.race_start(10) == at(0)


def _access(tmp_path, api, name="x"):
    raw, db = tmp_path / name / "raw", tmp_path / name / "db"
    ingest(make_client(raw / "dev", FakeFetch(api)), [2024], DATA_CFG)
    build_mod.build("dev", raw, db, allowed_seasons=DEV)
    return Access("dev", db, dev_seasons=DEV)


def test_unreconstructable_lap_completion_is_never_available(tmp_path):
    # The last lap has no duration and no next lap: excluded, not dated by the schedule.
    api = fake_api()
    race = (("session_key", 10),)
    api[("laps", race)][-1]["lap_duration"] = None
    acc = _access(tmp_path, api)
    assert acc.as_of("laps", at(10_000)).filter("lap_number = 6").fetchall() == []
    stint2 = acc.as_of("stints", at(10_000)).filter("stint_number = 2").project("lap_end")
    assert stint2.fetchall() == [(None,)]  # end of stint 2 stays masked
    acc.close()


def test_pit_durations_available_only_at_pit_exit(dev_db):
    acc, *_ = dev_db
    # Pit entry at minute 7.5 with 22 s in the lane: known from minute 7.5 + 22 s.
    assert acc.as_of("pit", at(7.5) + timedelta(seconds=21)).fetchall() == []
    assert len(acc.as_of("pit", at(7.5) + timedelta(seconds=23)).fetchall()) == 1


def test_results_wait_for_actual_session_end(tmp_path):
    # The race overruns its scheduled end (minute 10); the last lap completes at minute 12.
    api = fake_api()
    for s in api[("sessions", (("year", 2024),))]:
        if s["session_key"] == 10:
            s["date_end"] = ts(10)
    acc = _access(tmp_path, api)
    assert acc.as_of("session_result", at(11)).fetchall() == []
    assert len(acc.as_of("session_result", at(12.01)).fetchall()) == 1
    acc.close()
