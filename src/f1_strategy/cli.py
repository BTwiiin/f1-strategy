"""Command-line entry point: ``ingest`` and ``build`` (M2)."""

import argparse

from f1_strategy import config
from f1_strategy.data import build as build_mod
from f1_strategy.data.ingest import ingest
from f1_strategy.data.openf1 import Client, RateLimiter

REPO = config.CONFIG_DIR.parent


def role_seasons(role: str) -> list[int]:
    splits = config.load("evaluation")["splits"]
    dev = splits["burn_in_seasons"] + splits["development_seasons"]
    return dev if role == "dev" else splits["holdout_seasons"]


def cmd_ingest(args: argparse.Namespace) -> None:
    cfg = config.load("data")
    http = cfg["http"]
    client = Client(
        REPO / cfg["raw_dir"] / args.role,
        cfg["base_url"],
        RateLimiter(http["max_per_second"], http["max_per_minute"]),
        max_attempts=http["max_attempts"],
        backoff_base_s=http["backoff_base_s"],
        timeout_s=http["timeout_s"],
    )
    seasons = role_seasons(args.role)
    if args.season is not None:
        if args.season not in seasons:
            raise SystemExit(f"season {args.season} is not a {args.role} season")
        seasons = [args.season]
    ingest(client, seasons, cfg, meeting_key=args.meeting_key)
    # Holdout ingestion is sealed: report only how many requests were made.
    print(f"{client.fetched} new requests cached")


def cmd_build(args: argparse.Namespace) -> None:
    cfg = config.load("data")
    raw_dir, db_dir = REPO / cfg["raw_dir"], REPO / cfg["db_dir"]
    allowed = role_seasons("dev") + (role_seasons("holdout") if args.role == "holdout" else [])
    path = build_mod.build(
        args.role,
        raw_dir,
        db_dir,
        allowed_seasons=allowed,
        repo=REPO,
        freeze_tag=cfg["holdout"]["freeze_tag"],
    )
    print(f"built {path.relative_to(REPO)}")
    for name, digest in build_mod.table_digests(path).items():
        print(f"  {name}: {digest[:16]}")
    if args.role == "dev":
        report = REPO / cfg["reports_dir"] / "coverage_dev.md"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            build_mod.coverage_report(
                raw_dir / "dev", path, cfg["sessions"]["include"], cfg["endpoints"]
            )
        )
        print(f"coverage report: {report.relative_to(REPO)}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="f1-strategy")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ingest", help="cache OpenF1 responses for a role")
    p.add_argument("--role", choices=["dev", "holdout"], required=True)
    p.add_argument("--season", type=int, help="restrict to one season of the role")
    p.add_argument("--meeting-key", type=int, help="restrict to one meeting (validation run)")
    p.set_defaults(func=cmd_ingest)
    p = sub.add_parser("build", help="rebuild the role's DuckDB from the raw cache (offline)")
    p.add_argument("--role", choices=["dev", "holdout"], required=True)
    p.set_defaults(func=cmd_build)
    args = parser.parse_args(argv)
    args.func(args)
