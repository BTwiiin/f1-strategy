# Common-trend scenario grid

The common trend (`common_trend_gain`, s/lap, positive = faster each lap) is an external assumption, not an estimate (see [`scope.md`](scope.md#common-trend)). This document records the sources of its fuel component, the derivation of the scenario grid and the limitations of both. Values are in `config/model.toml` (`[common_trend]`).

## Fuel component

Per lap, the fuel-burn gain is

```
fuel_gain = lap_time_mass_sensitivity [s/kg] × fuel_burn_per_lap [kg/lap]
```

### Source

Per-circuit parameter sets of the open-source TUM race simulation:

- A. Heilmeier, M. Graf, J. Betz, M. Lienkamp, "Application of Monte Carlo Methods to Consider Probabilistic Effects in a Race Simulation for Circuit Motorsport", *Applied Sciences* 10(12), 4229, 2020. [doi:10.3390/app10124229](https://doi.org/10.3390/app10124229). Open-access copy: <https://mediatum.ub.tum.de/doc/1595500/1595500.pdf>.
- A. Heilmeier, M. Graf, M. Lienkamp, "A Race Simulation for Strategy Decisions in Circuit Motorsports", *21st International Conference on Intelligent Transportation Systems (ITSC)*, 2018. [doi:10.1109/itsc.2018.8570012](https://doi.org/10.1109/itsc.2018.8570012). Defines the lap-time model including the fuel-mass term.
- Parameter files: [TUMFTM/race-simulation](https://github.com/TUMFTM/race-simulation), commit `96ef2c2021982217be008fe458df47c1a72da071`, `racesim/input/parameters/pars_<circuit>_2019.ini`, keys `t_lap_sens_mass` (s/kg), `m_fuel` (kg), `b_fuel_perlap` (kg/lap), `tot_no_laps`. Licence LGPL-3.0.
- Related lap-time simulation: [TUMFTM/laptime-simulation](https://github.com/TUMFTM/laptime-simulation), commit `afa0aa710adb9fdd23fa3d6fbdd6a13664253616`.

### Provenance of the parameters (verified)

- The 2020 paper uses a lap-time model with a fuel-mass term `t_fuel` taken from the 2018 paper. It does not report the per-circuit mass-sensitivity values or how they were obtained.
- The race-simulation repository states that its 2014–2019 parameter files were created automatically from the authors' Formula 1 timing database (seasons 2014–2019, based on the Ergast API). The derivation of `t_lap_sens_mass` is not documented in the paper or the repository.
- The lap-time simulation repository describes lap-time mass sensitivity as a quantity that *can* be determined by sensitivity analysis with its quasi-steady-state simulation. It ships a single Formula 1 vehicle parameter file. It is not documented that the race-simulation values were produced this way.
- In every 2019 parameter file, `m_fuel = 110` kg and `b_fuel_perlap = m_fuel / tot_no_laps` (checked for all 21 files, to rounding). The burn rate is therefore a uniform-burn assumption from an assumed start fuel mass, not a measured consumption.

### 2019 values

| Circuit (file) | Laps | Sensitivity (s/kg) | Burn (kg/lap) | Fuel gain (s/lap) |
|---|---:|---:|---:|---:|
| Austin | 56 | 0.037 | 1.964 | 0.073 |
| Baku | 51 | 0.038 | 2.157 | 0.082 |
| Budapest | 70 | 0.028 | 1.571 | 0.044 |
| Catalunya | 66 | 0.033 | 1.667 | 0.055 |
| Hockenheim | 64 | 0.034 | 1.719 | 0.058 |
| LeCastellet | 53 | 0.035 | 2.076 | 0.073 |
| Melbourne | 58 | 0.029 | 1.897 | 0.055 |
| MexicoCity | 71 | 0.026 | 1.549 | 0.040 |
| MonteCarlo | 78 | 0.034 | 1.410 | 0.048 |
| Montreal | 70 | 0.022 | 1.571 | 0.035 |
| Monza | 53 | 0.027 | 2.076 | 0.056 |
| Sakhir | 57 | 0.023 | 1.930 | 0.044 |
| SaoPaulo | 71 | 0.030 | 1.549 | 0.046 |
| Shanghai | 56 | 0.031 | 1.964 | 0.061 |
| Silverstone | 52 | 0.034 | 2.115 | 0.072 |
| Singapore | 61 | 0.030 | 1.803 | 0.054 |
| Sochi | 53 | 0.031 | 2.076 | 0.064 |
| Spa | 44 | 0.030 | 2.500 | 0.075 |
| Spielberg | 71 | 0.019 | 1.549 | 0.029 |
| Suzuka | 52 | 0.028 | 2.115 | 0.059 |
| YasMarina | 55 | 0.034 | 2.000 | 0.068 |

Range 0.029–0.082 s/lap (Spielberg–Baku), median 0.056 s/lap. Fuel gain is computed from the file values and rounded to three decimals in the table.

The 2014–2018 parameter files give per-season ranges of a similar magnitude (minimum 0.022, maximum 0.105 s/lap across all seasons). They are not used: the 2019 files describe the most recent cars in the source.

### Limitations

- The values are historical simulation parameters for 2019 cars, not measurements for 2023–2025 cars. The 2022 regulations changed car mass and aerodynamic concept; whether the sensitivities transfer is untested.
- The derivation of the mass sensitivities is undocumented (see above).
- The burn rate assumes the full 110 kg start fuel is consumed uniformly. Cars that start with less fuel or save fuel unevenly burn less per lap, so the upper bound is conservative for the fuel component.
- The range is a spread across circuits, not an uncertainty interval for any circuit. One global grid is used for all circuits (no per-circuit grid), which is wide for circuits with a small fuel effect.

## Track-evolution allowance

Track evolution (rubbering-in, track temperature) has no cited source in the MVP. It enters as an explicitly labelled judgement allowance, symmetric around the fuel range: `track_evolution_allowance = 0.02` s/lap (provisional).

## Grid

- Range: `[fuel_gain_min − allowance, fuel_gain_max + allowance] = [0.009, 0.102]`, rounded outwards to multiples of the step: **0.00–0.11 s/lap**.
- Step: 0.01 s/lap (provisional), 12 points. Development-only resolution check: 0.005 s/lap over the same range, 23 points.
- Central scenario: the grid point nearest the median fuel gain with zero track-evolution allowance, **0.06 s/lap** (fixed). It does not move if the allowance or step is adjusted before the M6 freeze.

The grid is a set of stated assumptions, not a statistical confidence interval. No probability weights are placed on it by default; an aggregated probability is reported only under an explicit, documented prior and labelled as prior-dependent. Development fit (E2) is never used to select or weight scenarios.

The grid is computed by `f1_strategy.config.common_trend_grid`.
