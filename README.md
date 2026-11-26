# F1 Dry-Race Strategy Simulator

A reproducible pre-race simulator that compares one-stop and two-stop tyre strategies for a single car in dry Formula 1 races, using historical [OpenF1](https://openf1.org) data (2023–2025) stored in DuckDB.

The tool compares strategies; it does not predict races. It reports relative time deltas between plans and how robust their ranking is, not absolute race time or finishing position, and it does not claim that a recommended plan is optimal.

## Approach

- **Relative time model:** each plan's time is the sum of compound pace effects, tyre-age effects and pit losses. The lap-time trend shared by all plans (fuel burn and track evolution) cancels out of strategy comparisons.
- **Common-trend scenarios:** the shared trend cannot be separated from tyre degradation in lap-time data. It is therefore an explicit assumption, varied across a documented grid, and results are reported for each scenario, together with break-even values.
- **Uncertainty:** parameters are bootstrapped by race, and outputs include intervals, the conditional probability that each plan is fastest, regret, and a robust/fragile label.
- **Data support:** plans are labelled supported, extrapolated or unsupported according to how much historical data covers them, and recommendations are drawn from supported plans by default.
- **Evaluation:** a layered evidence hierarchy (synthetic recovery, executed-plan prediction, within-race plan comparison, agreement with reference strategies), walk-forward validation on 2023–2024, and a single frozen holdout evaluation on 2025.

## Status

Early development: evaluation contract and project skeleton (milestone M0).

- [`docs/scope.md`](docs/scope.md): scope and modelling assumptions.
- [`docs/evaluation.md`](docs/evaluation.md): evaluation contract.
- [`docs/common_trend.md`](docs/common_trend.md): common-trend scenario grid and its sources.
- [`MVP_roadmap.md`](MVP_roadmap.md): milestones, deliverables and acceptance criteria.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run f1-strategy     # CLI entry point
```
