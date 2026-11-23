# ntnsim v1.5.1: Operator 3GPP IoT-NTN vs IoT-only LoRaWAN NTN over LEO

Code and frozen results for the paper

> A. Elnashar, "Operator-Led 3GPP IoT-NTN Versus IoT-Only LoRaWAN Direct-to-Satellite Networks: A Same-Scenario LEO Simulation Study," submitted to *IEEE Open Journal of the Communications Society*, 2026.

Every number, table and figure in the paper comes from `frozen/results.json`, produced by `scripts/run_batch.py` with the code in this repository (version 1.5.1). All presets are illustrative system classes, not any operator's deployment, and no measured network data is used.

## Repository layout

| Path | Content |
|---|---|
| `ntnsim/` | Simulator package (standard library only) |
| `NTN_IoT_Operator_vs_LoRaWAN_Simulator.ipynb` | Self-contained Colab notebook, executed on the frozen results |
| `frozen/` | `results.json`, CSV tables (link budgets, scenario summary) and all figures (PNG and PDF) used in the paper |
| `scripts/run_batch.py` | Recomputes every result (about 2 h, about 3 GB RAM, checkpointed) |
| `scripts/build_notebook.py` | Rebuilds the notebook from the package |
| `CHANGELOG.md` | Model history and the stated limitations of v1.5.1 |
| `PORTING.md` | Notes for porting the model to other bands or regions |

## Headline results (frozen v1.5.1, utility-wells scenario)

| Quantity | Value |
|---|---|
| Operator NB-IoT on-time delivery | 0.986 |
| Operator NB-IoT service capacity | 13.58 [13.43, 13.72] devices/km² |
| Operator LTE-M service capacity | 58.3 [53.1, 63.4] devices/km² |
| Control NB-IoT / LR-FHSS capacity ratio, transmit at first visibility | 1.187 [1.165, 1.209] |
| Control NB-IoT / LR-FHSS capacity ratio, both wait for 30° | 1.238 [1.214, 1.262] |
| IoT-only LR-FHSS (ISM 868 MHz) on-time delivery | 0.297 (45.9 % expired) |
| Urban disaster fallback, operator NB-IoT on time (CE0 / CE1 / CE2) | 0.616 overall (0.99 / 0.874 / 0.012) |

Intervals are Student-t 95 % intervals over 10 independent replications; ratios are seed-paired log-ratio intervals.

## Quick start

```
pip install -r requirements.txt
python3 -c "from ntnsim import validate; validate.run()"     # 55 checks
python3 scripts/run_batch.py                                 # full recomputation
```

Or open the notebook in Colab; it writes the package itself and loads `frozen/results.json` (set `use_frozen = False` in `scripts/build_notebook.py` to recompute instead).

## Model overview
A simulator comparing hypothetical architectures that represent two ways of delivering the same IoT service from low Earth orbit. The presets are illustrative system classes, not any operator's deployment. Delivery means uplink reception at the satellite (transparent payload: at the gateway).

| Model | Stacks | Spectrum | Satellite class (illustrative) |
|---|---|---|---|
| Operator-led 3GPP | `OP-LB-NBIOT`, `OP-LB-LTEM` | Operator 800 MHz (B20) reused from space | 223 m² direct-to-device array, 120 sats, 520 km |
| Operator via MSS partner | `OP-MSS-NBIOT` | L-band MSS | 5 dBi smallsat, 32 sats, 500 km |
| IoT-only LoRaWAN | `IO-ISM-LRFHSS`, `IO-ISM-LORA-SF10`, `IO-ISM-LORA-SF12` | ISM 868 MHz (licence-exempt device, non-protected satellite) | 5 dBi smallsat, 16 sats, 550 km |
| IoT-only LoRaWAN, licensed | `IO-SBAND-LRFHSS` (LR1120, +11.5 dBm), `IO-SBAND-LRFHSS-HP` (+27 dBm module) | S-band MSS | 5 dBi smallsat, 64 sats, 550 km |
| Control (air interface only) | `CTRL-NBIOT`, `CTRL-LRFHSS`, `CTRL-LORA-SF12` | 847 MHz, same satellite and 22 dBm for all | 223 m² array, 120 sats |

Scenarios (UAE defaults, all values illustrative): remote utility wells, agriculture and water metering, logistics on highways, urban disaster fallback with the terrestrial network down.

## Comparison dimensions

| Dimension | Function | Method |
|---|---|---|
| Path loss | `analysis.path_loss_curve` | FSPL + TR 38.811 LOS/NLOS clutter and shadowing |
| Link budget | `analysis.link_budget` | Itemised: EIRP, FSPL, clutter, G, G/T, kT, interference, C/N0, required C/N0, margin, MAPL, MCL |
| Coverage | `analysis.coverage_curve`, `time_coverage` | P(link closes) per elevation (closed form); fraction of day at the site |
| Cell radius | `analysis.cell_radius` | Beam-spot radius (arrays) or footprint where link closes with 90 % probability (smallsats) |
| Interference | `analysis.noise_rise_vs_density`, engine | Aggregate ISM SRD and co-channel terrestrial UE density integrated over the footprint |
| Throughput | `report` (throughput vs elevation), `analysis.goodput_curve` | Link-adapted rate (3GPP) or fixed PHY rate (LoRa/LR-FHSS); delivered goodput vs load |
| Capacity | `analysis.capacity` | Service capacity (>= 90 % on time, all failures counted) and contention capacity (conditional); mean over independent replications of the whole estimation, Student-t 95 % interval (10 replications in the reference scenario) |
| Scheduler comparison | `refsched.reference_scheduler` | Exploratory chronological policy comparison (not a validation of the engine queue) |
| Delivery, latency | `engine.run_case` | Monte Carlo over real pass geometry; waiting for coverage, access, deadline |
| Energy | `energy` | Per-message state timeline; battery life |
| Sensitivity | `report.run_extras` | One assumption changed at a time |

## Validation (55 checks, all pass)

LoRa time on air matches the TTN airtime calculator to within 0.05 ms for SF7 to SF12; LoRa SF12 sensitivity matches the SX1276 datasheet (−137 dBm); Monte Carlo LoRa matches pure ALOHA; Monte Carlo LR-FHSS matches the Ullah et al. (IEEE WCL 2022) closed form; NPRACH collision model matches a direct preamble-selection simulation; propagated geometry matches the TR 38.811 slant-range formula; array gains match published estimates for 64 m² and 223 m² apertures at 850 MHz; NB-IoT and LTE-M MCL reproduce 164 dB (23 dBm, NF 3 dB) and 155.7 dB (20 dBm, NF 5 dB) at their stated assumptions (by construction, consistency only); LR-FHSS airtime follows the RP002-1.0.5 hop structure; satellite patterns conserve energy (v1 did not); RACH configurations are valid; Walker and censored-gap handling; v1.4 adds regression tests for the message chronology (no transmission after deadline or contact end, profile conservation, beam hopping), LR-FHSS branch continuity in six regimes, tiered admission accounting, per-TB HARQ, coherence-correlated HARQ, the S.1528 back lobe, capacity-interval coverage on a known crossing, and engine vs reference scheduler. Several checks are internal-consistency tests; independent link-level and measurement benchmarks are Phase 3.

## What is assumed, and what is not modelled

Assumed (exposed as parameters): satellite and constellation presets; ISM transmitter activity seen from orbit (low 1e-4, medium 1e-3, high 1e-2 per km²); LR-FHSS SNR thresholds (4 / 7 dB); LoRa and LR-FHSS Doppler tolerances; NPRACH repetition mapping; NB-IoT repetition efficiency beta 0.5 (hardware-inspired sensitivity; beta 1 reproduces the link-level anchor); LTE-M continuous Eb/N0 model with a 300 kbit/s cap (legacy model; no cap applies to the NB-IoT table model); protocol overhead; device current profiles; polarisation loss 3 dB; scintillation allowance 1 dB; transmit policy (wait for 30° elevation). TR 38.811 clutter tables are S-band values used at sub-GHz.

Phase 2 (v1.2) added event-driven traffic, NB-IoT TBS/RU/repetition tables with two documented calibrations, packet-level LR-FHSS hopping grids, scan broadening and optional finite beams, equal-infrastructure smallsat controls and spectral efficiency, symmetric frequency-offset limits and a TR 38.811 nearest-angle mode. Phase 3 items are listed in CHANGELOG.

Not modelled: downlink and acknowledgements; feeder links and gateway availability; satellite downlink interference into terrestrial users; J2 and drag; inter-satellite handover within a message; NB-IoT HARQ at physical-layer detail; LR-FHSS onboard demodulator limits (an optional cap can be added); economics are a template with no prices (fill in quotes).

The operator low-band stacks assume large direct-to-device arrays and a 120-satellite constellation, while the IoT-only stacks assume 16 to 64 small satellites. Results therefore compare **hypothetical architectures**, in which infrastructure scale, spectrum and technology are confounded. The control stacks isolate the air interface at one configured operating point (spectrum slices still differ: 180, 137 and 125 kHz); the sensitivity analysis shows how far each assumption moves the result. Equal-spectrum and equal-infrastructure controls are Phase 2. B20 reuse from space is a hypothetical configuration: B20 is not an NTN band in TS 36.102.

## Citation

See `CITATION.cff`. Please cite the paper when using the simulator.

## License

MIT, see `LICENSE`.
