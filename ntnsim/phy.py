"""Physical-layer models for LoRa, LR-FHSS, NB-IoT NTN and LTE-M NTN.

All links are evaluated in C/N0 form so that every technology sees the same
satellite receiver (G/T) and the same interference density:

    C/N0 = EIRP_dev - PL + G/T - k                      [dB-Hz]
    SNR(B) = C/N0_eff - 10 log10(B)

Provenance of each parameter is recorded in PARAM_SOURCES and printed with the
results. 'assumed' means a modelling choice exposed for change.
"""
import math

K_DBM = -198.6   # Boltzmann, dBm/K/Hz

# ------------------------------------------------------------------ LoRa
LORA_SNR_DB = {7: -7.5, 8: -10.0, 9: -12.5, 10: -15.0, 11: -17.5, 12: -20.0}
LORAWAN_OVERHEAD_B = 13       # MHDR1 + DevAddr4 + FCtrl1 + FCnt2 + FPort1 + MIC4


def lora_toa_s(sf, payload_phy_b, bw_hz=125e3, cr=1, n_pre=8, explicit_header=True, crc=True):
    """Semtech AN1200.13 time on air."""
    tsym = (2 ** sf) / bw_hz
    de = 1 if tsym > 0.016 else 0
    ih = 0 if explicit_header else 1
    num = 8 * payload_phy_b - 4 * sf + 28 + 16 * (1 if crc else 0) - 20 * ih
    n_payload = 8 + max(math.ceil(num / (4 * (sf - 2 * de))) * (cr + 4), 0)
    return (n_pre + 4.25) * tsym + n_payload * tsym


def lora_symbol_s(sf, bw_hz=125e3):
    return (2 ** sf) / bw_hz


def lora_rate_bps(sf, bw_hz=125e3, cr=1):
    """Information bit rate; LDRO (on when Tsym > 16 ms) removes 2 bits/symbol."""
    de = 1 if lora_symbol_s(sf, bw_hz) > 0.016 else 0
    return (sf - 2 * de) * bw_hz / 2 ** sf * 4 / (4 + cr)


def lora_doppler_ok(sf, bw_hz, f_dopp_hz, f_rate_hzps, frac=0.5):
    """Static offset within +-25 % BW and drift per symbol below frac of a bin.
    Tolerances are assumptions (see PARAM_SOURCES)."""
    if abs(f_dopp_hz) > 0.25 * bw_hz:
        return False
    return abs(f_rate_hzps) * lora_symbol_s(sf, bw_hz) <= frac * bw_hz / 2 ** sf


# ------------------------------------------------------------------ LR-FHSS
LRFHSS_DR = {
    # name: OCW (Hz), OBW channels C, header replicas, coding rate
    "DR8":  dict(ocw_hz=137e3, C=280, nh=3, cr="1/3", region="EU868"),
    "DR9":  dict(ocw_hz=137e3, C=280, nh=2, cr="2/3", region="EU868"),
    "DR10": dict(ocw_hz=336e3, C=688, nh=3, cr="1/3", region="EU868"),
    "DR11": dict(ocw_hz=336e3, C=688, nh=2, cr="2/3", region="EU868"),
    "DR5":  dict(ocw_hz=1.523e6, C=3120, nh=3, cr="1/3", region="US915"),
    "DR6":  dict(ocw_hz=1.523e6, C=3120, nh=2, cr="2/3", region="US915"),
}
LRFHSS_OBW_HZ = 488.28125
LRFHSS_TH_S = 0.233472     # header replica
LRFHSS_TF_S = 0.1024       # payload fragment
LRFHSS_SNR_DB = {"1/3": 4.0, "2/3": 7.0}


LRFHSS_GRID = {"DR8": 35, "DR9": 35, "DR10": 86, "DR11": 86, "DR5": 60, "DR6": 60}   # channels per packet grid


def lrfhss_frame(dr, payload_phy_b):
    """Frame per RP002-1.0.5: coded bits = ((L+2)*8 + 6) / CR, 48 bits per hop,
    shorter final hop of (bits_last + 2) * 2.048 ms."""
    p = LRFHSS_DR[dr]
    bits = (payload_phy_b + 2) * 8 + 6
    bits = bits * 3 if p["cr"] == "1/3" else math.ceil(bits * 3 / 2)
    nf = math.ceil(bits / 48)
    last_bits = bits - (nf - 1) * 48
    t_last = (last_bits + 2) * 0.002048
    need = math.ceil(nf / 3) if p["cr"] == "1/3" else math.ceil(2 * nf / 3)
    toa = p["nh"] * LRFHSS_TH_S + (nf - 1) * LRFHSS_TF_S + t_last
    return dict(nh=p["nh"], nf=nf, need=need, C=p["C"], grid=LRFHSS_GRID[dr], toa_s=toa,
                t_last_s=t_last, snr_req_db=LRFHSS_SNR_DB[p["cr"]], ocw_hz=p["ocw_hz"])


def lrfhss_doppler_ok(f_rate_hzps, frac=0.5):
    """Drift across one header replica below frac of an OBW channel (assumed, default 0.5)."""
    return abs(f_rate_hzps) * LRFHSS_TH_S <= frac * LRFHSS_OBW_HZ


# ------------------------------------------------------------------ 3GPP IoT-NTN
CELLULAR = {
    # Eb/N0 including implementation loss; floor rate set by max repetitions;
    # cap = practical peak over NTN; b_min = smallest uplink allocation.
    # floor back-solved: MCL_ref = Ptx_ref + 174 - NF_ref - 10log10(floor) - Eb/N0
    "NBIOT": dict(ebn0_db=5.0, floor_bps=10 ** ((23.0 + 174 - 3.0 - 5.0 - 164.0) / 10), cap_bps=20e3,
                  b_min_hz=3.75e3, eta_bps_hz=1.0, carrier_ul_hz=180e3, overhead_b=25,
                  mcl_ref_db=164.0, ref_nf_db=3.0, ref_ptx_dbm=23.0),
    # LTE-M floor from the TR 36.888 Table 9.5.7.1-3 point quoted in the RAN1 NTN
    # link-budget summary: 56-bit TBS, 250 repetitions (1 ms), 2 PRBs, SNR -27 dB.
    "LTEM":  dict(ebn0_db=5.0, floor_bps=56 / 0.250, cap_bps=300e3,
                  b_min_hz=180e3, eta_bps_hz=1.0, carrier_ul_hz=1.08e6, overhead_b=25,
                  mcl_ref_db=155.7, ref_nf_db=5.0, ref_ptx_dbm=20.0),
}


def cellular_rate_bps(tech, cn0_dbhz):
    """Link-adapted information rate from C/N0, or None if below floor."""
    p = CELLULAR[tech]
    r = 10 ** ((cn0_dbhz - p["ebn0_db"]) / 10)
    if r < p["floor_bps"]:
        return None
    return min(r, p["cap_bps"])


def cellular_mcl_check(tech):
    """Back-solve: MCL implied by floor rate, Eb/N0 and the reference NF/power."""
    p = CELLULAR[tech]
    sens = -174 + p["ref_nf_db"] + 10 * math.log10(p["floor_bps"]) + p["ebn0_db"]
    return p["ref_ptx_dbm"] - sens


def cellular_resource_hz_s(tech, rate_bps, bits):
    """Tone-time consumed: occupied bandwidth x airtime (Hz*s)."""
    p = CELLULAR[tech]
    t = bits / rate_bps
    b = max(p["b_min_hz"], rate_bps / p["eta_bps_hz"])
    return b * t, t, b


# ------------------------------------------------------------------ helpers
def noise_floor_dbm(b_hz, nf_db, t_ant_k=290.0):
    t = t_ant_k + 290.0 * (10 ** (nf_db / 10) - 1)
    return K_DBM + 10 * math.log10(t) + 10 * math.log10(b_hz)


def lora_sensitivity_dbm(sf, nf_db=6.0, bw_hz=125e3):
    return -174 + nf_db + 10 * math.log10(bw_hz) + LORA_SNR_DB[sf]


PARAM_SOURCES = {
    "LoRa SNR thresholds": "Semtech SX126x/SX127x datasheets (SF7 -7.5 dB ... SF12 -20 dB)",
    "LoRa time on air": "Semtech AN1200.13",
    "LoRaWAN MAC overhead 13 B": "LoRaWAN L2 1.0.4 frame format",
    "LoRa Doppler tolerance": "assumed: offset <= 25% BW, drift/symbol <= 0.5 bin",
    "LR-FHSS DR table": "LoRaWAN RP002-1.0.4 regional parameters",
    "LR-FHSS header/fragment durations": "233.472 ms / 102.4 ms (RP002, Boquet et al. 2021)",
    "LR-FHSS frame": "RP002-1.0.5: ((L+2)*8+6)/CR coded bits, 48 bits per hop, shorter final hop; decode needs 1/3 (CR 1/3) or 2/3 (CR 2/3) of hops",
    "LR-FHSS SNR threshold": "assumed: 4 dB (CR 1/3), 7 dB (CR 2/3)",
    "LR-FHSS Doppler tolerance": "assumed: drift over one header <= 50% of 488 Hz",
    "NB-IoT (legacy continuous model) floor 316 bit/s": "only used when nbiot_model='continuous'; back-solved to 164 dB at 23 dBm / NF 3 dB",
    "LTE-M floor 224 bit/s, Eb/N0 5 dB": "TR 36.888 Table 9.5.7.1-3 point (56 b, 250 reps, 2 PRB, -27 dB) quoted in RAN1#104e NTN summary; implies Eb/N0 5.06 dB",
    "NB-IoT NPUSCH": "TS 36.213 TBS table (Rel-13, <= 1000 bits, segmentation above) and RU structure; Shannon-gap SNR with gap fitted to TBS1000/NRU10/Nrep32/-13.8 dB, which only beta = 1.0 ('link_level') reproduces; default beta = 0.5 is a hardware-inspired curve (single-tone 3.75 kHz measurements), corroborated not calibrated by RAN4 ratios; not a validated BLER model",
    "NB-IoT HARQ": "chase combining of received energy over up to 2 attempts, feedback time RTT + 12 ms (assumed); no BLER curve",
    "NB-IoT burst rate": "reported burst_rate_bps is the PHY burst rate of the selected configuration, not transaction goodput; no 20 kbit/s cap is applied in the table model",
    "NPRACH / PRACH CE configuration": "assumed values chosen from TS 36.331 allowed sets; periodicity >= repetitions x preamble duration enforced",
    "NTN rate caps": "legacy continuous model only: NB-IoT 20 kbit/s, LTE-M 300 kbit/s (assumed); LTE-M still uses the continuous model",
    "NB-IoT/LTE-M protocol overhead 25 B": "assumed (CIoT control-plane, header compression)",
}
