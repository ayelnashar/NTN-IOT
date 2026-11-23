# ntnsim v1.7.0: Operator 3GPP IoT-NTN vs IoT-only LoRaWAN NTN over LEO

Code and frozen results for the paper

> A. Elnashar, "Operator-Led 3GPP IoT-NTN Versus IoT-Only LoRaWAN Direct-to-Satellite Networks: A Same-Scenario LEO Simulation Study," submitted to *IEEE Open Journal of the Communications Society*, 2026.

Every number, table and figure in the paper comes from `frozen/results.json`, produced by `scripts/run_batch.py` with the code in this repository (version 1.7.0). All presets are illustrative system classes, not any operator's deployment, and no measured network data is used.

## Repository layout

| Path | Content |
|---|---|
| `ntnsim/` | Simulator package (standard library only) |
| `NTN_IoT_Operator_vs_LoRaWAN_Simulator.ipynb` | Self-contained Colab notebook, executed on the frozen results |
| `frozen/` | `results.json`, CSV tables (link budgets, scenario summary) and all figures (PNG and PDF) used in the paper |
| `scripts/run_batch.py` | Recomputes every result (about 3.5 h of processor time, about 3 GB RAM, checkpointed) |
| `scripts/build_notebook.py` | Rebuilds the notebook from the package |
| `CHANGELOG.md` | Model history and the stated limitations of v1.7.0 |
| `PORTING.md` | Notes for porting the model to other bands or regions |

## Headline results (frozen v1.7.0, utility-wells scenario)

| Quantity | Value |
|---|---|
| Operator NB-IoT on-time delivery, uplink / confirmed | 0.983 / 0.980 |
| Operator NB-IoT service capacity (uplink) | 19.36 [19.02, 19.70] devices/km² |
| Operator NB-IoT capacity without access barring (uniform / RAR priority / uplink-only model) | 10.2 / 10.6 / 13.6 devices/km² (3 replications) |
| Operator LTE-M service capacity | 58.5 [57.5, 59.5] devices/km² |
| Control NB-IoT / LR-FHSS uplink capacity ratio, first visibility / 30° | 1.698 [1.677, 1.720] / 1.873 [1.824, 1.923] |
| Control NB-IoT / LR-FHSS confirmed capacity ratio, first visibility / 30° | 7.48 [7.27, 7.70] / 7.20 [7.00, 7.41] |
| IoT-only LR-FHSS (ISM 868 MHz) on-time delivery, uplink / confirmed | 0.297 / 0.009 |
| Urban disaster, operator NB-IoT on time | 0.502 (0.616 with the downlink off; 0.230 uniform admission; 0.100 RAR priority) |

At the NB-IoT service capacity the random-access responses occupy 0.71 of the downlink; access barring by coverage level holds the downlink at 0.9 and bars 7.1 % of devices. NB-IoT capacity, and the uplink ratio to LR-FHSS, therefore depend on the access control.

Intervals are Student-t 95 % intervals over 10 independent replications; ratios are seed-paired log-ratio intervals.

## Downlink (v1.7)

The downlink is modelled for every stack (`ntnsim/downlink.py`, `ntnsim/txn.py`).

- Link budget: satellite EIRP density from 3GPP TR 36.763 Set 4 (small satellites, fixed EIRP) or the array aperture gain at the downlink frequency plus an assumed 8.5 dBW/MHz RF density (arrays); each device's uplink realisation re-evaluated at the downlink frequency in the same physical direction with the downlink beamwidth; co-channel beams at reuse 3. The model reports the RF power needed to light every beam of the footprint (about 21 kW for NB-IoT, 126 kW for LTE-M at the assumed density).
- 3GPP: declared NB-IoT and LTE-M configurations; control and shared channels with a gap anchored at the NPDSCH reference point (TBS 680, 8 subframes, 128 repetitions, -14.7 dB) for the active beta; assumed acquisition limit -14.7 dB (non-acquired devices send no preamble); initial coverage level from the downlink measurement, three attempts per level, five in total, NPRACH and RAR moving together; one RAR MAC PDU per non-empty occasion and level with one RAR per distinct detected preamble (binomial occupancy), split at the maximum TBS; the RAR carries the first grant; grants for later attempts and a final message, re-sent up to 4 times with repetitions doubled up to R_max; downlink load with every re-send; one fixed point for access, uplink admission and downlink load; downlink admission by access barring per coverage level (default), uniform or RAR-priority (stress); one absolute event timeline per device for uplink fading, downlink decoding and the energy ledger.
- LoRaWAN confirmed mode: one acknowledgement transmitter per cell as a stationary on-off calendar (loss system, window-specific duty budgets); RX1 with the EU868 mapping on the uplink channel at 25 mW and 1 % in the ISM band (it does not close), RX2 at the configured rate; RX1 at the configured rate in licensed bands; joint LR-FHSS decode-and-blanking mask on the same calendar for half-duplex ISM gateways; acknowledgement demand from the uplinks that survive; acknowledgement must end inside the contact.

`g_over=dict(downlink=False)` reproduces v1.5.1 exactly.

## Quick start

```
pip install -r requirements.txt
python3 -c "from ntnsim import validate; validate.run()"     # 65 checks
python3 scripts/run_batch.py                                 # full recomputation
```

Or open the notebook in Colab; it writes the package itself and loads `frozen/results.json` (set `use_frozen = False` in `scripts/build_notebook.py` to recompute instead).

## Model overview
A simulator comparing hypothetical architectures that represent two ways of delivering the same IoT service from low Earth orbit. The presets are illustrative system classes, not any operator's deployment. Two delivery metrics: uplink reception at the satellite (transparent payload: at the gateway), and confirmed delivery with the downlink acknowledgement.

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

## Validation (65 checks, all pass)

LoRa time on air matches the TTN airtime calculator to within 0.05 ms for SF7 to SF12; LoRa SF12 sensitivity matches the SX1276 datasheet (−137 dBm); Monte Carlo LoRa matches pure ALOHA; Monte Carlo LR-FHSS matches the Ullah et al. (IEEE WCL 2022) closed form; NPRACH collision model matches a direct preamble-selection simulation; propagated geometry matches the TR 38.811 slant-range formula; array gains match published estimates for 64 m² and 223 m² apertures at 850 MHz; NB-IoT and LTE-M MCL reproduce 164 dB (23 dBm, NF 3 dB) and 155.7 dB (20 dBm, NF 5 dB) at their stated assumptions (by construction, consistency only); LR-FHSS airtime follows the RP002-1.0.5 hop structure; satellite patterns conserve energy (v1 did not); RACH configurations are valid; Walker and censored-gap handling; v1.4 adds regression tests for the message chronology (no transmission after deadline or contact end, profile conservation, beam hopping), LR-FHSS branch continuity in six regimes, tiered admission accounting, per-TB HARQ, coherence-correlated HARQ, the S.1528 back lobe, capacity-interval coverage on a known crossing, and engine vs reference scheduler; v1.6/v1.7 add the downlink anchor in both calibrations, the acknowledgement-transmitter limits and calendar occupancy, co-channel geometry symmetry, the joint LR-FHSS decode-and-blanking mask (review probe R5), re-send repetition limits (probe R3), the RAR distinct-preamble count and PDU split, the coverage-level chain, delivery ordering invariants and exact reproduction of v1.5.1 with the downlink off. Several checks are internal-consistency tests; independent link-level and measurement benchmarks are Phase 3.

## What is assumed, and what is not modelled

Assumed (exposed as parameters): satellite and constellation presets; ISM transmitter activity seen from orbit (low 1e-4, medium 1e-3, high 1e-2 per km²); LR-FHSS SNR thresholds (4 / 7 dB); LoRa and LR-FHSS Doppler tolerances; NPRACH repetition mapping; NB-IoT repetition efficiency beta 0.5 (hardware-inspired sensitivity; beta 1 reproduces the link-level anchor); LTE-M continuous Eb/N0 model with a 300 kbit/s cap (legacy model; no cap applies to the NB-IoT table model); protocol overhead; device current profiles; polarisation loss 3 dB; scintillation allowance 1 dB; transmit policy (wait for 30° elevation). TR 38.811 clutter tables are S-band values used at sub-GHz.

Phase 2 (v1.2) added event-driven traffic, NB-IoT TBS/RU/repetition tables with two documented calibrations, packet-level LR-FHSS hopping grids, scan broadening and optional finite beams, equal-infrastructure smallsat controls and spectral efficiency, symmetric frequency-offset limits and a TR 38.811 nearest-angle mode. Phase 3 items are listed in CHANGELOG.

Not modelled: symbol-level cell acquisition and control decoding; acknowledgement-triggered retransmissions; feeder links and gateway availability; satellite downlink interference into terrestrial users; J2 and drag; inter-satellite handover within a message; NB-IoT HARQ at physical-layer detail; LR-FHSS onboard demodulator limits (an optional cap can be added); economics are a template with no prices (fill in quotes).

The operator low-band stacks assume large direct-to-device arrays and a 120-satellite constellation, while the IoT-only stacks assume 16 to 64 small satellites. Results therefore compare **hypothetical architectures**, in which infrastructure scale, spectrum and technology are confounded. The control stacks isolate the air interface at one configured operating point (spectrum slices still differ: 180, 137 and 125 kHz); the sensitivity analysis shows how far each assumption moves the result. Equal-spectrum and equal-infrastructure controls are Phase 2. B20 reuse from space is a hypothetical configuration: B20 is not an NTN band in TS 36.102.

## Citation

See `CITATION.cff`. Please cite the paper when using the simulator.

## License

MIT, see `LICENSE`.
