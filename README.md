# F1 Tyre Pace and Strategy

Forecasting tyre-dependent race pace in dry Formula 1 races from historical [OpenF1](https://openf1.org) data (2023–2025, DuckDB), and using the validated models to compare one-stop and two-stop strategies for a single car.

## Questions

1. How accurately can post-stop stint lap times be forecast 5–15 laps ahead for future races, and which models and information beat persistence and structural baselines?
2. How do the strategy rankings implied by those models differ, and how robust are they to model class, parameter uncertainty and common-trend assumptions?
3. What can observed races actually verify about strategy decisions?

Predictive accuracy, model-implied strategy comparisons and empirically verifiable outcomes are reported separately. Pit timing and compound choice are team decisions, so good forecasts do not make strategy comparisons causal, and no recommended plan is claimed to be optimal.

## Approach

- Structural pace model with a driver-race level shared across stints, extended by a GAM and gradient boosting only where they beat simpler models out of sample.
- Walk-forward evaluation (2023 burn-in, 2024 development), feature-group ablation, calibrated forecast intervals, and a single frozen 2025 holdout behind a cutoff-gated access layer.
- Deterministic strategy simulator with data-support labels, regret-based decision outputs and common-trend sensitivity.

## Status

Evaluation contract (M0, revised) and synthetic core (M1). Next: OpenF1 ingestion (M2).

- [`docs/scope.md`](docs/scope.md), [`docs/forecasting.md`](docs/forecasting.md), [`docs/evaluation.md`](docs/evaluation.md): contract.
- [`MVP_roadmap.md`](MVP_roadmap.md): milestones and acceptance criteria.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run f1-strategy     # CLI entry point
```
