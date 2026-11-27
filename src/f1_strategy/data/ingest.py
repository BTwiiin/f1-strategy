"""Ingestion plan: which OpenF1 requests are made for a role's seasons."""

from typing import Any

from f1_strategy.data.openf1 import Client


def endpoints_for(session_name: str, endpoints: dict[str, list[str]]) -> list[str]:
    extra = {"Race": endpoints["race"], "Qualifying": endpoints["qualifying"]}
    return endpoints["every_session"] + extra.get(session_name, [])


def selected_sessions(
    sessions: list[dict[str, Any]], include: list[str], meeting_key: int | None = None
) -> list[dict[str, Any]]:
    """Included, non-cancelled sessions, optionally of one meeting, in a stable order."""
    chosen = [
        s
        for s in sessions
        if s["session_name"] in include
        and not s.get("is_cancelled")
        and (meeting_key is None or s["meeting_key"] == meeting_key)
    ]
    return sorted(chosen, key=lambda s: (s["date_start"], s["session_key"]))


def ingest(
    client: Client,
    seasons: list[int],
    data_cfg: dict[str, Any],
    meeting_key: int | None = None,
) -> int:
    """Cache every planned request for ``seasons``; return the number of sessions covered.

    Only schedule metadata (meetings, sessions) is parsed; session data is cached unread.
    """
    endpoints = data_cfg["endpoints"]
    n_sessions = 0
    for season in seasons:
        for endpoint in endpoints["season"]:
            client.ensure(endpoint, {"year": season})
        sessions = client.get("sessions", {"year": season})
        for s in selected_sessions(sessions, data_cfg["sessions"]["include"], meeting_key):
            for endpoint in endpoints_for(s["session_name"], endpoints):
                client.ensure(endpoint, {"session_key": s["session_key"]})
            n_sessions += 1
    return n_sessions
