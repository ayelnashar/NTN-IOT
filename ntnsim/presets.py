"""Presets: satellites, constellations, technology stacks, UAE scenarios.

Values marked 'illustrative' describe a class of system, not a specific
operator's design. Every preset is a plain dict so it serialises to JSON for
the HTML port (see export_presets()).
"""
import json

SITE_UAE = dict(name="Abu Dhabi, UAE", lat=24.45, lon=54.38)

SATELLITES = {
    "smallsat_patch": dict(pattern="broad", gain_dbi=5.0, nf_db=2.0, t_ant_k=290.0, dl_eirp_dbw_mhz=21.45,
                           note="illustrative cubesat patch, nadir beam"),
    "smallsat_deployable": dict(pattern="broad", gain_dbi=12.0, nf_db=2.0, t_ant_k=290.0, dl_eirp_dbw_mhz=21.45,
                                note="illustrative deployable antenna on a small LEO IoT satellite"),
    "d2d_array_64m2": dict(pattern="multibeam", beams_per_sat=None, aperture_m2=64.0, eff=0.65, nf_db=2.0,
                           t_ant_k=290.0, scan_loss_exp=1.2, sidelobe_db=-25.0, dl_rf_psd_dbw_mhz=8.5,
                           note="64 m2 phased array (AST Block 1 class)"),
    "d2d_array_223m2": dict(pattern="multibeam", beams_per_sat=None, aperture_m2=223.0, eff=0.65, nf_db=2.0,
                            t_ant_k=290.0, scan_loss_exp=1.2, sidelobe_db=-25.0, dl_rf_psd_dbw_mhz=8.5,
                            note="223 m2 phased array (AST Block 2 class)"),
}

CONSTELLATIONS = {
    "iot_sparse": dict(n=16, planes=4, inc=97.5, h=550.0, phasing=1,
                       note="illustrative sparse IoT smallsat constellation (SSO)"),
    "iot_dense": dict(n=64, planes=8, inc=97.5, h=550.0, phasing=1,
                      note="illustrative dense IoT smallsat constellation (SSO)"),
    "mss_mid": dict(n=32, planes=8, inc=97.5, h=500.0, phasing=1,
                    note="illustrative MSS-band IoT-NTN constellation"),
    "d2d_60": dict(n=60, planes=6, inc=53.0, h=520.0, phasing=1,
                   note="illustrative direct-to-device constellation, 60 large arrays"),
    "d2d_120": dict(n=120, planes=12, inc=53.0, h=520.0, phasing=1,
                    note="illustrative direct-to-device constellation, 120 large arrays"),
}

# Downlink EIRP density: small satellites use 3GPP TR 36.763 Set-4 LEO-600
# (21.45 dBW/MHz, small IoT satellite). No TR set describes a large phased
# array: the arrays use an RF power density of 8.5 dBW/MHz behind their own
# aperture gain at the downlink frequency (as the uplink G/T is derived from
# the same aperture). 8.5 dBW/MHz is the downlink power density (-51.5 dBW/Hz,
# peak EIRP density -16.5 dBW/Hz at 889 MHz) in a public FCC experimental-
# licence exhibit for a 64 m2 array of this class. Downlink carrier per stack:
# B20 791-821 MHz (806 MHz), MSS L-band 1525-1559 MHz (1542 MHz), MSS S-band
# 2170-2200 MHz (2185 MHz), ISM RX2 869.525 MHz (500 mW e.r.p. = 29.15 dBm
# EIRP, 10 % duty, half-duplex gateway).

# ISM short-range-device activity seen from orbit (active transmitters per km^2,
# footprint average). Assumed levels for sensitivity analysis, not measurements.
ISM_ACTIVITY = {"off": 0.0, "low": 1e-4, "medium": 1e-3, "high": 1e-2}

# Random-access configurations per coverage-enhancement (CE) level. Values are
# picked from the TS 36.331 allowed sets (NB-IoT nprach-Periodicity,
# numRepetitionsPerPreambleAttempt, nprach-NumSubcarriers); the split across CE
# levels is an assumption. Periodicity >= repetitions x preamble duration is
# asserted in the engine.
RACH = {
    "NBIOT": dict(preamble_s=0.0056, rar_window_s=0.25, backoff_s=0.256,
                  ce=[dict(reps=2, period_s=0.16, preambles=24),
                      dict(reps=16, period_s=0.32, preambles=12),
                      dict(reps=128, period_s=1.28, preambles=12)]),
    "LTEM": dict(preamble_s=0.001, rar_window_s=0.1, backoff_s=0.08,
                 ce=[dict(reps=1, period_s=0.02, preambles=18),
                     dict(reps=8, period_s=0.04, preambles=18),
                     dict(reps=64, period_s=0.16, preambles=18)]),
}

STACKS = {
    # ---- operator-led 3GPP IoT-NTN -----------------------------------------
    "OP-LB-NBIOT": dict(model="operator", label="Operator NB-IoT NTN, 800 MHz (B20) reuse",
                        tech="NBIOT", f_hz=847e6, f_dl_hz=806e6, sat="d2d_array_223m2", const="d2d_120", alloc_hz=200e3,
                        ptx_dbm=23.0, g_dev_dbi=0.0, device="nbiot_ntn",
                        spectrum="licensed_terrestrial", coexistence="dedicated",
                        carriers_per_beam=1, payload="transparent",
                        rach_max=5, edt=True, rai=True, ctrl_overhead=0.3, tx_policy="first_visible"),
    "OP-LB-LTEM": dict(model="operator", label="Operator LTE-M NTN, 800 MHz (B20) reuse",
                       tech="LTEM", f_hz=847e6, f_dl_hz=806e6, sat="d2d_array_223m2", const="d2d_120", alloc_hz=1.4e6,
                       ptx_dbm=23.0, g_dev_dbi=0.0, device="nbiot_ntn",
                       spectrum="licensed_terrestrial", coexistence="dedicated",
                       carriers_per_beam=1, payload="transparent",
                       rach_max=5, edt=True, rai=True, ctrl_overhead=0.3, tx_policy="first_visible"),
    "OP-MSS-NBIOT": dict(model="operator", label="NB-IoT NTN via MSS partner, L-band",
                         tech="NBIOT", f_hz=1643.5e6, f_dl_hz=1542e6, sat="smallsat_patch", const="mss_mid", alloc_hz=200e3,
                         ptx_dbm=23.0, g_dev_dbi=0.0, device="nbiot_ntn",
                         spectrum="licensed_mss", coexistence="dedicated",
                         carriers_per_beam=1, payload="regenerative",
                         rach_max=5, edt=True, rai=True, ctrl_overhead=0.3, tx_policy="first_visible"),
    # ---- IoT-only / non-operator LoRaWAN NTN --------------------------------
    "IO-ISM-LRFHSS": dict(model="iot_only", label="IoT-only LR-FHSS DR8, ISM 868 MHz",
                          tech="LRFHSS", dr="DR8", f_hz=868.1e6, f_dl_hz=869.525e6, dl_eirp_cap_dbm=29.15, dl_duty=0.10, gw_half_duplex=True, sat="smallsat_patch", alloc_hz=137e3,
                          const="iot_sparse", ptx_dbm=14.0, g_dev_dbi=2.15, device="lora_lr11xx",
                          spectrum="ism", ism="low", other_networks_load=1.0, copies=1,
                          duty_cycle_limit=0.01, payload="regenerative", class_a_rx=True),
    "IO-ISM-LORA-SF10": dict(model="iot_only", label="IoT-only LoRa SF10, ISM 868 MHz",
                             tech="LORA", sf=10, channels=8, f_hz=868.1e6, f_dl_hz=869.525e6, dl_eirp_cap_dbm=29.15, dl_duty=0.10, gw_half_duplex=True, sat="smallsat_patch", alloc_hz=1e6,
                             const="iot_sparse", ptx_dbm=14.0, g_dev_dbi=2.15, device="lora_lr11xx",
                             spectrum="ism", ism="low", other_networks_load=1.0, copies=1,
                             duty_cycle_limit=0.01, payload="regenerative", class_a_rx=True),
    "IO-ISM-LORA-SF12": dict(model="iot_only", label="IoT-only LoRa SF12, ISM 868 MHz",
                             tech="LORA", sf=12, channels=8, f_hz=868.1e6, f_dl_hz=869.525e6, dl_eirp_cap_dbm=29.15, dl_duty=0.10, gw_half_duplex=True, sat="smallsat_patch", alloc_hz=1e6,
                             const="iot_sparse", ptx_dbm=14.0, g_dev_dbi=2.15, device="lora_lr11xx",
                             spectrum="ism", ism="low", other_networks_load=1.0, copies=1,
                             duty_cycle_limit=0.01, payload="regenerative", class_a_rx=True),
    "IO-SBAND-LRFHSS": dict(model="iot_only", label="IoT-only LR-FHSS, licensed S-band, LR1120 (+11.5 dBm)",
                            tech="LRFHSS", dr="DR8", f_hz=1995e6, f_dl_hz=2185e6, sat="smallsat_patch", alloc_hz=137e3,
                            const="iot_dense", ptx_dbm=11.5, g_dev_dbi=2.15, device="lora_lr1120_sband",
                            spectrum="licensed_mss", ism="off", other_networks_load=0.0, copies=1,
                            duty_cycle_limit=None, payload="regenerative", class_a_rx=False),
    "IO-SBAND-LRFHSS-HP": dict(model="iot_only", label="IoT-only LR-FHSS, licensed S-band, high-power module (+27 dBm)",
                               tech="LRFHSS", dr="DR8", f_hz=1995e6, f_dl_hz=2185e6, sat="smallsat_patch", alloc_hz=137e3,
                               const="iot_dense", ptx_dbm=27.0, g_dev_dbi=2.15, device="sband_hp_module",
                               spectrum="licensed_mss", ism="off", other_networks_load=0.0, copies=1,
                               duty_cycle_limit=None, payload="regenerative", class_a_rx=False),
    # ---- same-band control (air interface only) -----------------------------
    "CTRL-NBIOT": dict(model="control", label="Control: NB-IoT NTN, 847 MHz, equal satellite and power",
                       tech="NBIOT", f_hz=847e6, f_dl_hz=806e6, sat="d2d_array_223m2", const="d2d_120", alloc_hz=200e3,
                       ptx_dbm=22.0, g_dev_dbi=0.0, device="nbiot_ntn", spectrum="licensed_terrestrial",
                       coexistence="dedicated", carriers_per_beam=1, payload="transparent",
                       rach_max=5, edt=True, rai=True, ctrl_overhead=0.3, tx_policy="first_visible"),
    "CTRL-LRFHSS": dict(model="control", label="Control: LR-FHSS DR8, 847 MHz, equal satellite and power",
                        tech="LRFHSS", dr="DR8", f_hz=847e6, f_dl_hz=806e6, sat="d2d_array_223m2", const="d2d_120", alloc_hz=200e3,
                        ptx_dbm=22.0, g_dev_dbi=0.0, device="lora_lr11xx", spectrum="licensed_terrestrial",
                        ism="off", other_networks_load=0.0, copies=1, duty_cycle_limit=None, payload="transparent"),
    "CTRL-LORA-SF12": dict(model="control", label="Control: LoRa SF12, 847 MHz, equal satellite and power",
                           tech="LORA", sf=12, channels=1, f_hz=847e6, f_dl_hz=806e6, sat="d2d_array_223m2", alloc_hz=200e3,
                           const="d2d_120", ptx_dbm=22.0, g_dev_dbi=0.0, device="lora_lr11xx",
                           spectrum="licensed_terrestrial", ism="off", other_networks_load=0.0,
                           copies=1, duty_cycle_limit=None, payload="transparent", class_a_rx=True),
}
for _t, _extra in (("NBIOT", dict(device="nbiot_ntn", coexistence="dedicated", carriers_per_beam=1, rach_max=5,
                                   edt=True, rai=True, ctrl_overhead=0.3, tx_policy="first_visible")),
                   ("LRFHSS", dict(dr="DR8", device="lora_lr11xx", ism="off", other_networks_load=0.0, copies=1,
                                   duty_cycle_limit=None, class_a_rx=False)),
                   ("LORA", dict(sf=12, channels=1, device="lora_lr11xx", ism="off", other_networks_load=0.0,
                                 copies=1, duty_cycle_limit=None, class_a_rx=True))):
    _name = {"NBIOT": "NB-IoT", "LRFHSS": "LR-FHSS DR8", "LORA": "LoRa SF12"}[_t]
    STACKS["CTRL-SS-" + {"NBIOT": "NBIOT", "LRFHSS": "LRFHSS", "LORA": "LORA-SF12"}[_t]] = dict(
        model="control_smallsat", label=f"Control (smallsat): {_name}, 847 MHz, 5 dBi, 64 sats, 22 dBm",
        tech=_t, f_hz=847e6, f_dl_hz=806e6, sat="smallsat_patch", const="iot_dense", alloc_hz=200e3, ptx_dbm=22.0,
        g_dev_dbi=0.0, spectrum="licensed_terrestrial", payload="regenerative", **_extra)

SCENARIOS = {
    "utility_wells": dict(label="Remote utility wells (desert)", env="rural",
                          payload_b=20, interval_s=3600, deadline_s=3600, device_loss_db=0.0,
                          local_density_km2=0.05, local_area_km2=30000, background_density_km2=1e-3,
                          gnss_per_msg=False, tn_active_km2=0.005, tn_down=False),
    "agri_water": dict(label="Agriculture and water metering (farms)", env="rural",
                       payload_b=12, interval_s=900, deadline_s=1800, device_loss_db=0.0,
                       local_density_km2=1.0, local_area_km2=2000, background_density_km2=1e-3,
                       gnss_per_msg=False, tn_active_km2=0.02, tn_down=False),
    "logistics": dict(label="Logistics: trucks and trailers on highways", env="suburban",
                      payload_b=24, interval_s=900, deadline_s=900, device_loss_db=3.0,
                      local_density_km2=0.02, local_area_km2=50000, background_density_km2=1e-3,
                      gnss_per_msg=True, tn_active_km2=0.05, tn_down=False),
    "disaster_urban": dict(label="Disaster fallback, urban, terrestrial network down", env="urban",
                           payload_b=50, interval_s=600, deadline_s=600, device_loss_db=10.0,
                           local_density_km2=20.0, local_area_km2=1500, background_density_km2=1e-3,
                           gnss_per_msg=False, tn_active_km2=0.0, tn_down=True),
}

GLOBAL = dict(
    site=SITE_UAE, elev_mask_deg=10.0, t_end_s=172800.0, arrival_window_s=86400.0, dt_s=10.0,
    arrival_start_s=43200.0,    # targets generated in [12 h, 36 h): warm-up backlog before, future contacts after
    traffic_model="event",      # 'event' (arrivals, buffering, expiry mapped onto contacts) | 'fluid' (lambda / f_cov)
    discard_expired=True,       # devices drop messages older than the deadline instead of sending them
    angle_mode="interp",        # 'interp' (extrapolation) | 'nearest' (TR 38.811 reference-angle reproduction)
    nbiot_model="tables",       # 'tables' (TS 36.213 TBS/RU/repetitions) | 'continuous' (legacy Eb/N0 model)
    nbiot_calibration="hardware",   # repetition efficiency 0.5 ('hardware'-inspired) | 1.0 ('link_level', reproduces the anchor)
    nbiot_objective="resource",     # link adaptation minimises cell resource ('resource') or airtime ('airtime')
    harq_proc_s=0.012,              # HARQ feedback / scheduling processing time per retransmission (assumed)
    la_margin_db=1.0, harq_max=2,   # link-adaptation back-off and NPUSCH HARQ attempts
    coh_s=1.0,                  # fading coherence time for independent looks (assumed)
    osc_ppm=2.0,                # LoRa/LR-FHSS device TCXO error (assumed)
    nbiot_residual_ppm=0.1, precomp_update_s=0.5, nbiot_max_fo_frac=0.1,   # residual after GNSS pre-compensation (assumed)
    lrfhss_acq_hz=None,         # LR-FHSS receiver absolute offset limit; unknown -> not applied
    lrfhss_model="packet",      # 'packet' (hopping grids, time overlaps) | 'marginal' (Ullah et al.)
    hop_frame_s=1.0,            # beam-hopping frame when active beams < cells
    release_jitter_s=60.0,      # buffered messages are released at a random time within this window
    serving="sticky",           # keep serving satellite until it sets ('best' = highest each step)
    feeder_el_deg=30.0,         # transparent payload: gateway seen at this elevation (feeder leg)
    ground_delay_s=0.0,         # regenerative payload: store-and-forward wait for a ground station (unknown; 0 = uplink reception time)
    rho_admit=0.9,              # admission threshold for scheduled 3GPP traffic
    admission="uniform",        # 'uniform' (mean-field random blocking) | 'cheapest_first' (block largest demands first)
    calendar_life_years=15.0,   # assumed cell calendar/shelf limit on battery life
    rx_window_symbols=6,        # Class A receive-window preamble detection length
    seeds=[20261122, 20261123, 20261124],
    seeds_ref=list(range(20261122, 20261132)),   # 10 independent replications for reference-scenario capacity CIs (M02)
    pol_loss_db=3.0,            # linear device antenna vs circular satellite polarisation
    scint_margin_db=1.0,        # ionospheric scintillation allowance at UHF, assumed
    gas_loss_db=0.1,
    capture_db=6.0, sidelobe_model="airy",
    fade_k_los_db=10.0, fade_k_nlos_db=3.0,
    ism_eirp_dbm=16.15, ism_band_hz=7e6,
    tn_ue_eirp_dbm=0.0, tn_carrier_hz=10e6, tn_indoor_frac=0.8, tn_bpl_db=15.0,
    tx_policy="elev_threshold",  # 'first_visible' | 'elev_threshold' | 'best_in_pass'
    tx_min_elev_deg=30.0,       # pass-aware devices wait for this elevation (else pass maximum)
    n_mc=3000, pool_size=4000, seed=20261122,
    battery_mah=5200.0, battery_v=3.6,
    gnss_validity_s=86400.0,
    downlink=True,              # v1.6/v1.7: downlink link budget, control/data channels, acknowledgements
    dl_nf_cell_db=7.0,          # cellular module noise figure (TR 36.763 PC3 assumption; 9 dB = RAN1 common PC5 value)
    dl_nf_lora_db=6.0,          # LoRa transceiver noise figure (SX1262: -137 dBm at SF12/125 kHz)
    dl_reuse=3,                 # multibeam downlink frequency reuse (TR 38.821 FRF 3)
    dl_retx_max=4,              # network re-sends of a missed grant or final message, repetitions doubled up to R_max
    dl_floor_db=-14.7,          # assumed acquisition limit: NPDSCH reference threshold (Matz et al. 2020, 164 dB MCL)
    dl_policy="ce_barring",     # v1.7 downlink admission: 'uniform' | 'ce_barring' | 'rar_priority' (v1.6 stress)
    ce_select="measured",       # v1.7 initial CE level: 'measured' (downlink thresholds) | 'max_ul_dl' (oracle)
    rx1_mapping="configured",   # v1.7 LoRaWAN RX1 rate in licensed bands: 'configured' (= RX2 rate) | 'eu868' (DR8 -> SF11)
    ack_policy="fastest",       # v1.7 LoRaWAN: 'fastest' (RX1 only if not slower than RX2) | 'rx1_first' (RX1 then RX2)
    ce_attempts=3,              # preamble attempts per coverage level before moving up (maxNumPreambleAttemptCE, n3)
    dl_eirp_offset_db=0.0,      # sensitivity: offset on every satellite downlink EIRP density
    dl_sf_margin_db=3.0,        # LoRaWAN downlink SF: lowest SF with this margin at the elevation mask, median LOS
)


def export_presets(path):
    with open(path, "w") as f:
        json.dump(dict(satellites=SATELLITES, constellations=CONSTELLATIONS, stacks=STACKS,
                       scenarios=SCENARIOS, ism_activity=ISM_ACTIVITY, global_=GLOBAL), f, indent=1)
