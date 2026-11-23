# Changelog

## v1.5.1 (paper version)

Energy accounting of the 3GPP stacks follows one causal clock per message.

- Random-access preambles stop at contact end or message expiry; for devices below the coupling-loss floor, the number of preambles is bounded by the remaining contact and deadline.
- RRC setup, queue waiting, data and release are charged only when access completes inside the contact and before expiry.
- A transport-block attempt cut by contact end or expiry is charged for the part transmitted.
- Release is charged only after data has been sent.

The random-number stream is unchanged, so delivery, latency, capacity, policy ratios and all other non-energy results are identical to v1.5.0 (checked field by field). Only energy per message and battery life change, by at most 3% (largest change: OP-LB-NBIOT in the disaster scenario, 1.483 J to 1.439 J per message, 0.68 to 0.70 years). The 55 validation checks pass.

## v1.5.0 (final; review round 4)

Frozen as the paper version. P01-P04 change results and are fixed; P05-P08 are corrected in labelling and stated as limitations.

| Finding | Status | Change |
|---|---|---|
| P01 | Fixed | Executed per-device schedules replace reconstructed histories: each device generates at its own phase, one persistent FIFO and next-free time carry across contacts, expired messages are dropped without airtime, waiting = start time - generation time (a message sent at once waits 0 s). A stratified grid of device schedules (phase x release slot x beam phase) is computed once per configuration; the release profile and the Monte Carlo targets come from the same executed schedules. Validation: zero FIFO/busy-time violations in the agriculture LR-FHSS grid. |
| P02 | Fixed | Starts are searched over opportunities until the transmission fits or expires: policy-allowed step, a dwell of the cell's fixed beam calendar (period hop_frame/duty, cell offset), and the remaining contact. LoRa-family devices require the packet to fit (ephemeris pass prediction); 3GPP devices require synchronisation and GNSS fix to fit (Rel-17 cell stop time, t-Service). Profile quadrature: doubling phases and release slots changes the normalised profile by 1.2 % (agri LR-FHSS). Limitation: the beam calendar gates the start only; a transaction may run past its dwell. |
| P03 | Fixed | One channel clock: Rician blocks of length coh_s with random phase, duration-weighted fading over every block a transmission spans, zero-overlap blocks excluded; shared by NB-IoT HARQ attempts, LR-FHSS elements and LoRa copies of the same message. |
| P04 | Fixed | Executed-state clock after access and queueing: data attempts run only while the contact lasts and before expiry; only executed attempts are charged; LoRa copies are limited to those that start inside the contact and before expiry. |
| P05 | Relabelled | refsched.py is an exploratory policy comparison, not a validation of the engine queue (different admission and service order, realised airtime, elevation-only marks, scheduling completions only). Removed from the validation suite. Matched chronological validation is an open item. |
| P06 | Relabelled, quantified | LR-FHSS element branch documented as an approximation (drops packet clustering, shared interferer power, hop persistence; mean fragment length). Checked at the actual switch (150-250 same-grid packets, capture regime): differences within about 0.04 (results.json lrfhss_branch_boundary). Without capture both branches give zero. |
| P07 | Relabelled | Capacity estimand named: expected finite-sample crossing; fresh on-time at the reported capacity reported beside it (LTE-M about 0.91). |
| P08 | Fixed / relabelled | Back lobe selected on the physical separation; the option is an S.1528-based scanned envelope (circular branches on the equivalent angle), not the full elliptical S.1528. |

Frozen results (v1.5.0, utility wells unless stated; v1.4 -> v1.5):

| Quantity | v1.4 | v1.5 (frozen) |
|---|---|---|
| Operator NB-IoT on time | 0.973 | 0.986 |
| Operator NB-IoT service capacity (10 replications) | 12.74 [12.52, 12.97] | 13.58 [13.43, 13.72] devices/km2 |
| Operator LTE-M service capacity | 50.1 [44.9, 55.3] | 58.3 [53.1, 63.4] devices/km2 |
| Control NB-IoT / LR-FHSS, both first-visible | 1.13x [1.09, 1.16] | 1.19x [1.17, 1.21] |
| Control NB-IoT / LR-FHSS, both wait for 30 deg | 1.11x [1.08, 1.13] | 1.24x [1.21, 1.26] |
| Smallsat controls, service capacity | 0 / 0 | 0 / 0 (on time 0.85-0.89) |
| IoT-only ISM LR-FHSS on time | 0.285 | 0.297 (46 % expired, 23 % SNR, 1 % collision) |
| Urban disaster, operator NB-IoT | 0.603 | 0.616 (CE0 0.99, CE1 0.87, CE2 0.01) |
| Disaster, link-level + cheapest-first | 0.738 | 0.755 |
| LR-FHSS element branch vs enumeration at the 200-packet switch | not tested | max difference 0.035 |

Main drivers of the v1.5 moves: correct waiting time (no frac*dt double count), duration-weighted fading over the blocks a transmission actually spans with random block phase (P03), and the executed-state clock (P04).

Limitations carried into the paper: uplink only (no downlink acquisition, grant or ACK reliability); threshold PHY with hardware-inspired repetition efficiency, no link-level BLER calibration; LTE-M continuous Eb/N0 abstraction; heuristic NPRACH detection and control-channel capacity; uncalibrated ISM/TN occupancy and sub-GHz propagation extrapolated from TR 38.811; 1 s coherence assumed (1 ms and 10 s sensitivities); assumed device currents; minimum-area device counts instead of geographic intersections; no shared payload resources; mean-field queue without matched chronological validation; LR-FHSS element-branch approximation above 200 same-grid packets.

## v1.4.0 (review round 3: chronology, admission, uncertainty)

Every M item was reproduced against the code before any change (M03: 30.8 % packet vs 75.8 % fallback at 4 dB; M06: 96 ms chosen where 2 ms has the same resource; F11: CTRL-LRFHSS had no payload type; N06: integration stopped at 90 deg, no back lobe).

| Finding | Status | Change |
|---|---|---|
| M01 | Fixed | Cheapest-first admission orders requests by the causal grant cost (first-pass resource of the selected configuration), not by realised HARQ outcomes. Requests form equal-cost tiers; whole tiers are admitted in increasing cost until rho_admit, the boundary tier with probability f_cut; packets and queue moments use the same f_cut, so booked and admitted utilisation agree (validation: 0.900 at rho_admit 0.9). Admitted fraction reported per group; delivery and blocking reported per CE level. Uniform random admission stays the primary baseline. |
| M02 | Fixed | Capacity = mean over independent replications of the complete procedure (geometry, links, access, group fitting, interference pools, bisection). Reference scenario: 10 replications, Student-t 95 % interval (Monte Carlo uncertainty only). On-time fraction re-estimated at the reported capacity with fresh seeds; monotonicity check at 0.5x/1x/2x. Interval coverage tested on a known-crossing problem with the same 10 x 12-step procedure: 0.947. Other scenarios: 3 replications, min-max only. Technology x policy matrix: 10 replications, seed-paired ratios with t-interval on the log ratio. |
| M03 | Fixed | The marginal fallback is removed. Above 200 same-grid packets an element-level Poisson branch keeps the same coherence-block target fading and exact time-weighted overlaps; only hop persistence across consecutive target elements is dropped. Continuity test in six regimes (SNR 4-10 dB, fading, unequal powers, non-zero throughput): max difference 0.023, within 3 standard errors. |
| M04 | Fixed | One chronology per message (Case.chronology): device keeps its generation phase; device-level release slot; per-device FIFO backlog (older buffered messages of the same device sent first, already-expired ones dropped without airtime, expiry rechecked at every send time); deferral to the next real contact when the current one ends; expiry checked after every deferral with zero energy. The release profile is built from the same chronology (quadrature over generation phase, release slot and hop phase), so target and background traffic share one schedule. Validation: zero transmissions start after the deadline or after contact end. |
| M05 | Fixed | Beam-hop waiting advances to a real beam opportunity in the current contact or, if none remains, in the next contact (then re-checked for expiry); included in the release profile. |
| M06 | Fixed | Link-adaptation frontier uses a lexicographic objective: resource, then airtime (default) or airtime, then resource. 60 dB-Hz, 360 bits: 2 ms (12 tones) instead of 96 ms. Operator NB-IoT energy per message 0.424 -> 0.35 J. |
| M07 | Fixed | Each transport block of a segmented message has its own HARQ attempts, feedback and resource; the message needs every TB; later TBs are not sent after a TB fails. |
| N02 | Fixed | Fractional generation time: the transmission starts frac*dt into the release step, and remaining contact is reduced accordingly (this also removed an optimistic contact-end error for messages sent in their generation step). |
| N03 | Fixed | Fading indexed by absolute time in coherence blocks: retransmissions inside one coherence time see the same channel. Coherence 1 ms and 10 s added to the sensitivity set. |
| N06 / F03 | Fixed (partly) | S.1528 back lobe L_B = max(15 + L_N + 0.25 G_m + 5 log10 z, 0) dBi for 90-180 deg; interference integration over the full sphere around the axis. Elliptical S.1528 branches (z > 1) not implemented: scanned beams use the equivalent-angle ellipse. |
| N08 | Fixed | Energy averaged over every generated message (no-coverage samples count with zero energy; asserted ledger length). |
| F11 | Fixed | CTRL-LRFHSS payload set to transparent like the other large-array controls. |
| F22 | Extended | See M02; orbital-phase windows labelled as overlapping (sensitivity, not an ensemble). |
| F24 | Fixed | 'measured' calibration alias removed; nbiot docstring no longer mentions the unimplemented Rel-14 TBS; README rate-cap wording corrected. |
| Rank-1 | Added | refsched.py: chronological reference scheduler (event-by-event server, deadline-aware FIFO for uniform admission, smallest-cost priority for cheapest-first) driven by the engine's own marks and release profile; compared with the engine queue in the batch and in validation. |

Result changes (utility wells unless stated; v1.3 -> v1.4):

| Quantity | v1.3 | v1.4 | Driver |
|---|---|---|---|
| Operator NB-IoT on time | 0.998 | 0.973 | N03 coherence-correlated HARQ (1 ms coherence gives 0.988) and the N02 contact-end correction |
| Operator NB-IoT energy per message | 0.424 J | 0.348 J | M06 airtime tie-break |
| Operator NB-IoT service capacity | 13.8 (3-seed median) | 12.74, CI [12.52, 12.97] | 10 replications; N03 |
| Operator LTE-M service capacity | 56.8 (seed-1 CI excluded the median) | 50.1, CI [44.9, 55.3] | M02 |
| Control NB-IoT / LR-FHSS, both first-visible | 1.21x (1 seed) | 1.13x, CI [1.09, 1.16] | M02 paired ratio; N03 |
| Control NB-IoT / LR-FHSS, both wait for 30 deg | 1.37x (1 seed) | 1.11x, CI [1.08, 1.13] | M02 paired ratio; N03 |
| Smallsat controls, service capacity | 0 / 0 | 0 / 0 (on time 0.87-0.89) | unchanged |
| IoT-only ISM LR-FHSS on time | 0.279 | 0.285 | M04 chronology |
| Urban disaster operator NB-IoT | 0.621 | 0.603 | N03; CE2 devices 0.02 on time |
| Disaster, link-level + cheapest-first | 0.770 | 0.738 | M01 causal tiers |

Reference scheduler vs engine (served fraction of scheduled requests): wells at capacity 0.986 (device-weighted) vs 0.991; disaster 0.992 vs 0.987; disaster link-level overload, FIFO vs uniform 0.680 vs 0.605; cost priority vs cheapest-first 0.935 vs 0.905. In overload the engine's admitted queue waits (< 1 s) are far below the FIFO reference (80 s mean), because the engine blocks at admission while FIFO lets the queue grow to the deadline.

Open: F05 downlink/ACK; F06 NPRACH detection and control-channel calibration; F07 link-level BLER (LTE-M still continuous model); F09 geographic population intersection; F10 shared payload resources; F13 interference calibration; F16 sub-GHz propagation; independent receiver validation; energy parameters.

## v1.3.0 (review round 2: ledger and model corrections)

| Finding | Status | Change |
|---|---|---|
| N01 | Fixed | Scheduled demand is computed after access: per CE level NPRACH collision and access success first, then data requests only from devices that pass access and have a feasible configuration, including the resource of every HARQ attempt. Queue wait uses the Pollaczek-Khinchine M/G/1 formula (validated against a chronological FIFO simulation); admission at rho = 0.9. Urban-disaster operator NB-IoT moves from 20 % to 62 % on time. |
| N02 | Fixed | One expiry rule: sampled messages and background traffic are discarded when their wait (after jitter) exceeds the deadline; they count as 'expired' and are not transmitted. Release-profile smoothing removed; mass preserved. |
| N03 | Fixed (abstraction labelled) | HARQ uses chase combining of received energy over attempts, feedback time RTT + 12 ms, resources and energy for every attempt; still a threshold abstraction, not a BLER model. |
| N04 | Fixed | LR-FHSS: persistent per-packet hopping sequences (no repeat of the previous hop), time-weighted co-channel interference so one packet never counts twice at an instant, fading per coherence block; marginal-model fallback reported as a fraction and validated for continuity at the boundary. |
| N05 | Fixed | Technology x transmit-policy matrix for all six controls (on-time, service and contention capacity); MSS policy sensitivities use the stack override (asserted); S.1528 sensitivity run with co-channel interference enabled. |
| N06 | Fixed | One scanned (elliptical) beam pattern for wanted gain, footprint and interference: width bw/cos(scan) in the scan plane; S.1528 recommends 1.2 main-lobe exponent 1.5 (revision to be pinned). |
| N07 | Fixed | Link adaptation objective: 'resource' (bandwidth x time, default) or 'airtime'; both on the Pareto frontier; airtime objective in sensitivity. |
| N08 | Fixed | Energy follows executed states: expired = 0; failed access = sync + GNSS + preambles; blocked = no data; data = every HARQ attempt + feedback windows + queue wait at idle current + release. |
| N09 | Fixed | Beam-hopping wait advances the time step and geometry and shortens the remaining contact. |
| N10 | Fixed | Value-based interference cache keys (full antenna configuration, numerical state, angle mode, quadrature); angle mode passed per call, no module state (regression test). |
| N11 | Fixed | Messages above 1000 bits are segmented into equal transport blocks; Rel-14 extension claim removed. |
| N12 | Fixed | Spectral efficiency multiplies by the on-time fraction at the capacity point (delivered, not offered). |
| F17 | Fixed | analysis.time_coverage uses the arrival window with censored gaps (regression test). |
| F19 | Extended | Backlog spacing: a message buffered through a gap waits behind earlier buffered messages from the same device, each occupying copies x airtime plus duty-cycle off-time. |
| F22 | Extended | Three seeds in every scenario; 95 % bounds on the service-capacity crossing from Wilson-interval bisection; seed min-max labelled as spread, not CI; on-time fraction over three orbital-phase windows. |
| Admission | Added option | 'cheapest_first' admission (block the largest service demands first, CE-aware scheduler) beside the reviewed 'uniform' mean-field default. With uniform admission the optimistic link-level calibration lowers urban-disaster delivery (54.9 % vs 62.1 %) because newly feasible deep-coverage devices drive blocking for everyone; with cheapest-first it raises it (77.0 % vs 62.5 %). Admission policy is a first-order assumption for dense deep-indoor cases and is reported as such. |
| F24 | Fixed | Inactive 20 kbit/s NB-IoT cap removed from documentation; burst rate reported separately from goodput; 0.5 repetition efficiency renamed 'hardware'-inspired. |

Open: F05 downlink/ACK; F06 NPRACH detection and control-channel calibration; F07 link-level BLER (LTE-M still continuous model); F13 interference calibration; F09 geographic population intersection; F10 shared payload resources; independent receiver validation.

## v1.2.0 (Phase 2: protocol realism and fairness controls)

| Finding | Status | Change |
|---|---|---|
| F07 | Fixed (structure), calibrated (SNR) | NB-IoT NPUSCH uses the TS 36.213 TBS table, resource-unit durations (1/2/4/8/32 ms), data REs per RU and repetitions {1..128}; link adaptation picks the fastest configuration meeting the long-term C/N0 with a 1 dB back-off; fading looks follow airtime; up to 2 HARQ attempts. SNR mapping: Shannon gap calibrated to the TBS 1000 / N_RU 10 / N_rep 32 / -13.8 dB link-level point, with repetition efficiency 0.5 (measured: Electronics 2020 hardware study, RAN4 single-tone requirements) as default and 1.0 (link level) as the optimistic bound. A BLER table can be loaded to replace the mapping. LTE-M floor taken from the TR 36.888 point (56 b, 250 reps, 2 PRB, -27 dB), which also confirms Eb/N0 = 5.06 dB. |
| F08 | Fixed | Event-driven traffic: every generation instant over the 48 h run is mapped through the transmit policy onto a transmit step; expired messages are discarded; buffered releases are spread over a 60 s jitter window; arrivals sampled in 12-36 h so backlog and future contacts exist. Per-sample load comes from this profile (beam cells) or its contact average (broad footprints). Fluid model retained as an option. |
| F10 | Fixed | Beam spot broadens as 1/cos(scan) in the scan plane; optional finite active beams per satellite with beam-hopping duty and wait; default remains an isolated-beam upper bound and is labelled so. |
| F11 | Fixed | Equal-infrastructure smallsat controls (CTRL-SS-*: 5 dBi, 64 satellites, 847 MHz, 22 dBm) added beside the large-array controls; every stack carries its allocated spectrum and results report on-time messages per second per allocated MHz. |
| F14 | Fixed | Packet-level LR-FHSS receiver: interfering packets on the same hopping grid (35 channels for DR8, 8 grids), actual start times, partial overlaps, per-hop channel hits sharing the interfering packet's power. Agrees with the Ullah closed form in its regime (validation). Marginal model retained as an option. |
| F15 | Fixed (parameterised) | Symmetric frequency limits: NB-IoT/LTE-M residual after GNSS pre-compensation (0.1 ppm plus Doppler rate x 0.5 s, limit 10 % of subcarrier); LoRa offset includes a 2 ppm oscillator term; LR-FHSS acquisition limit available (unknown, off by default). All values labelled assumed. |
| F16 | Fixed | Standards-reproduction mode uses the nearest TR 38.811 reference angle; fading looks derived from airtime and an assumed 1 s coherence time. |
| F17 | Extended | Transactions must fit in the remaining contact (3GPP and LoRa); late completion counts as lost. |
| F22 | Extended | Convergence of service capacity at 1,000 / 3,000 / 6,000 samples reported; 3 seeds in the reference scenario. |
| Policies | Changed | 3GPP stacks transmit when in coverage (network-scheduled); LoRaWAN stacks wait for 30 deg (pass-aware). The alternative policy is in the sensitivity analysis. |
| Bug | Fixed | Packet-level LR-FHSS now separates link (SNR) and collision causes. |

Still open (Phase 3): F05 downlink and acknowledgements; F13 interference calibration against measurements; independent link-level BLER tables for NB-IoT; NPRACH detection requirement and control-channel capacity (F06 calibration); measured device current profiles.

## v1.1.0 (Phase 1: correctness fixes after external review)

Each item references the external review finding it resolves.

| Finding | Status | Change |
|---|---|---|
| F01 | Fixed | `analysis.capacity` now returns service capacity (largest devices/cell with >= 90 % on-time uplink reception, every failure counted; 0 when infeasible unloaded) and, separately named, contention capacity. |
| F02 | Fixed | 3GPP load, CE mix, resource demand and RACH contention are evaluated per 5-degree elevation bin from the samples themselves, not at the mean elevation. |
| F03 | Fixed | Multibeam side lobes use a physically normalised circular-aperture pattern (integral 0.93, v1 gave 9.2); ITU-R S.1528 recommends 1.2 envelope available as a labelled bound (integral 2.28). Interference is integrated over solid angle around the true beam axis with the 2-D beam-to-emitter angle; the in-beam double count is gone. |
| F04 | Fixed | Overload no longer converts infinite delay to zero: admission control at rho = 0.9; rejected traffic is counted as blocked; admitted traffic sees M/D/1 delay at the admitted load. |
| F05 | Relabelled | Delivery is reported as uplink reception; `ground_delay_s` adds a store-and-forward wait for regenerative payloads. Downlink is Phase 3. |
| F06 | Partly fixed | NB-IoT NPRACH and LTE-M PRACH are separate, with three CE levels each; periodicity >= repetitions x preamble duration is asserted (v1 had 717 ms of preamble in a 320 ms period). Full calibration is Phase 2. |
| F09 | Fixed | One population for all stacks: local disc around the site plus background, applied identically to beam spots and footprints. |
| F12 | Fixed | ISM and terrestrial interferers pay the same polarisation loss as wanted signals (ISM noise rise 3.51 to 2.11 dB at the low level). |
| F17 | Fixed | Serving-satellite identity kept (sticky serving, handover only on loss); a contact is a run of one satellite; 48 h orbit horizon with arrivals in the first 24 h (no wrap-around); censored gaps reported; never-visible timelines report the full window. |
| F18 | Fixed | Payload architecture per stack (transparent / regenerative); transparent RTT includes the feeder leg; latency and energy are built from the same timeline (sync, GNSS, preamble repetitions, RAR windows, backoff, queue, data, contention resolution). |
| F19 | Partly fixed | Copies are scheduled with duty-cycle spacing and timestamped at the successful copy; a copy that falls after the contact ends is lost. Charging energy for every blind copy is retained: an unconfirmed sender cannot know an earlier copy succeeded. |
| F20 | Partly fixed | Failed access is charged sync, GNSS and preambles only; Class A RX1/RX2 windows charged for LoRaWAN stacks; battery life capped at an assumed 15-year calendar life and the limiting factor reported; energy per on-time message added. Cloud-solved GNSS scans are retained as a valid position method. |
| F21 | Fixed | Wording: hypothetical architectures; confounding stated in README and notebook. |
| F22 | Partly fixed | Wilson 95 % intervals on delivery; capacity uses 3,000 samples and three seeds with min-max spread. Convergence and independent benchmarks are Phase 3. |
| F23 | Fixed | Timeline cache key hashes constellation parameters, site, mask, horizon, serving rule and model version; Walker rejects non-divisible inputs. |
| F24 | Fixed | Device EIRP separated from propagation allowances; C/(N0+I0) labelled; MAPL and MCL boundaries stated; LoRa rate applies LDRO; LR-FHSS airtime follows RP002-1.0.5 (shorter final hop). |
| Parameters | Fixed | NB-IoT floor back-solved at 23 dBm / NF 3 dB (316 bit/s); LTE-M at 20 dBm / NF 5 dB (676 bit/s); S-band split into LR1120 (+11.5 dBm) and +27 dBm module variants; duty-cycle note limited to 868.0-868.6 MHz. |

Open for Phase 2: F07, F08, F10, F11, F13, F14, F15, F16, F06 calibration. Phase 3: F05 downlink, F13 calibration, F22 independent benchmarks.
