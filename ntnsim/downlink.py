"""Downlink model (v1.6): link budget, 3GPP downlink control and data
channels, and the LoRaWAN acknowledgement downlink.

Link budget
    The satellite downlink EIRP density follows the satellite parameter sets
    of 3GPP TR 36.763 Section 6.2.1 (LEO-600): Set-1, 34 dBW/MHz, for the large
    arrays (conservative for a 223 m2 aperture, which would reach it with a few
    tens of milliwatts per beam) and Set-4, 21.45 dBW/MHz (small IoT satellite),
    for the small satellites. In the ISM band the satellite transmitter is held
    to the short-range-device limit of the 869.40-869.65 MHz sub-band (500 mW
    e.r.p., 10 % duty cycle, ERC/REC 70-03 Annex 1), which is the LoRaWAN RX2
    channel. The relative satellite pattern, slant range, clutter and
    shadowing, building loss and allowances are the uplink realisation of the
    same device, with free-space loss evaluated at the downlink frequency.
    Fast fading is drawn independently (FDD separation). Device noise figure:
    7 dB for cellular modules (TR 36.763 PC3 assumption) and 6 dB for LoRa
    transceivers (SX1262 sensitivity of -137 dBm at SF12/125 kHz). Multibeam
    satellites add inter-beam interference from six first-tier co-channel
    beams at frequency reuse 3 (TR 38.821 FRF 3), all transmitting.

3GPP channels (NB-IoT NPDCCH/NPDSCH; LTE-M MPDCCH/PDSCH)
    Same Shannon-gap abstraction as the uplink:
        SNR_req = 10log10(2^(bits/RE) - 1) + GAP_DL - beta 10log10(R)
    with GAP_DL anchored to the published NPDSCH reference point TBS 680,
    8 subframes, 128 repetitions, 10 % BLER at -14.7 dB (Matz et al., Sensors
    2020, Table 2, the IMT-2020 164 dB case) for the active repetition
    efficiency beta, so the anchor is reproduced in both calibrations. Cell
    acquisition (NPSS/NSSS/NPBCH) is not modelled at symbol level; a device
    whose long-term downlink SNR is below the same -14.7 dB design point
    (164 dB MCL) is treated as unable to acquire the cell. Resource elements per
    subframe: NB-IoT standalone 152 (168 minus 16 NRS); LTE-M 6 PRB with a
    3-symbol legacy control region and CRS, 720.
"""
import math

NB_RE_SF = 152
LTEM_RE_SF = 720
DL_ANCHOR = dict(tbs=680, nsf=8, nrep=128, snr_db=-14.7)
SNR_FLOOR_DB = -14.7
REPS = [2 ** k for k in range(12)]          # 1 ... 2048
NSF = [1, 2, 3, 4, 5, 6, 8, 10]
TECH = {
    # dci_bits: payload + 16-bit CRC; rmax_ctrl: control-channel repetition limit;
    # avail: fraction of downlink subframes left after sync, broadcast and system information
    "NBIOT": dict(re_sf=NB_RE_SF, bw_hz=180e3, dci_bits=23 + 16, rmax_ctrl=2048, rmax_data=2048, nsf=NSF, avail=0.70),
    "LTEM": dict(re_sf=LTEM_RE_SF, bw_hz=1.08e6, dci_bits=29 + 16, rmax_ctrl=256, rmax_data=2048, nsf=[1], avail=0.80),
}
RAR_BITS = 7 * 8            # MAC RAR (6 B) + subheader (1 B)
FINAL_BITS = 20 * 8         # contention resolution + RRCEarlyDataComplete / release
CTRL_GAP_S = 0.004          # control-to-data scheduling gap per downlink message


def _shannon_db(bpr):
    return 10 * math.log10(2 ** bpr - 1)


def gap_db(beta):
    bpr = (DL_ANCHOR["tbs"] + 24) / (DL_ANCHOR["nsf"] * NB_RE_SF)
    return DL_ANCHOR["snr_db"] - (_shannon_db(bpr) - beta * 10 * math.log10(DL_ANCHOR["nrep"]))


def req_snr_db(bits, n_re, nrep, beta):
    return _shannon_db(bits / n_re) + gap_db(beta) - beta * 10 * math.log10(nrep)


def ctrl_config(tech, snr_db, beta, margin_db, floor_db=SNR_FLOOR_DB):
    """Fewest control-channel repetitions whose requirement is met with the
    link-adaptation margin; None if none (or below the acquisition floor)."""
    t = TECH[tech]
    if snr_db < floor_db:
        return None
    for r in REPS:
        if r > t["rmax_ctrl"]:
            break
        q = req_snr_db(t["dci_bits"], t["re_sf"], r, beta)
        if q <= snr_db - margin_db:
            return dict(sf=r, req=q)
    return None


def data_config(tech, bits, snr_db, beta, margin_db, floor_db=SNR_FLOOR_DB):
    """Fewest subframes (N_SF x R) of a shared-channel transport block."""
    t = TECH[tech]
    if snr_db < floor_db:
        return None
    best = None
    for nsf in t["nsf"]:
        for r in REPS:
            if r > t["rmax_data"]:
                break
            q = req_snr_db(bits + 24, nsf * t["re_sf"], r, beta)
            if q <= snr_db - margin_db:
                if best is None or nsf * r < best["sf"]:
                    best = dict(sf=nsf * r, req=q)
                break
    return best


def message_config(tech, bits, snr_db, beta, margin_db, floor_db=SNR_FLOOR_DB):
    """Control (DCI) plus optional shared-channel part. Returns total
    subframes, the binding requirement and the two parts, or None."""
    c = ctrl_config(tech, snr_db, beta, margin_db, floor_db)
    if c is None:
        return None
    if not bits:
        return dict(sf=c["sf"], req=c["req"], ctrl=c, data=None)
    d = data_config(tech, bits, snr_db, beta, margin_db, floor_db)
    if d is None:
        return None
    return dict(sf=c["sf"] + d["sf"], req=max(c["req"], d["req"]), ctrl=c, data=d)


def escalate(tech, cfg, k, beta):
    """k-th network re-send of a missed downlink message: repetitions of each
    part doubled k times (capped at the channel maximum), requirement lowered
    by the repetition gain beta 10log10(multiplier). Returns (subframes, req)."""
    t = TECH[tech]
    parts = [(cfg["ctrl"], t["rmax_ctrl"])] + ([(cfg["data"], t["rmax_data"] * 10)] if cfg.get("data") else [])
    sf, req = 0, -1e9
    for part, cap in parts:
        m = 2 ** k
        while part["sf"] * m > cap and m > 1:
            m //= 2
        sf += part["sf"] * m
        req = max(req, part["req"] - beta * 10 * math.log10(m))
    return sf, req


def ce_thresholds(beta, floor_db=SNR_FLOOR_DB):
    """Downlink SNR thresholds of coverage levels 0, 1, 2. Level 2 starts at the
    acquisition floor; each lower level needs the gain of the 8x repetition step
    between NPRACH levels (2/16/128 for NB-IoT, 1/8/64 for LTE-M) more SNR."""
    step = beta * 10 * math.log10(8)
    return [floor_db + 2 * step, floor_db + step, floor_db]


def dl_level(snr_db, beta, floor_db=SNR_FLOOR_DB):
    for i, t in enumerate(ce_thresholds(beta, floor_db)):
        if snr_db >= t:
            return i
    return None


def rar_level_configs(tech, beta, margin_db, floor_db=SNR_FLOOR_DB):
    """Random-access response per coverage level: one response per NPRACH
    occasion carries every detected preamble of that level (RA-RNTI), so its
    repetitions are set for the level's lower SNR threshold."""
    return [message_config(tech, RAR_BITS, t, beta, margin_db, floor_db) for t in ce_thresholds(beta, floor_db)]


def msg_time_s(tech, sf):
    return sf * 1e-3 / TECH[tech]["avail"] + CTRL_GAP_S


def anchor_check(beta):
    """Requirement of the anchor configuration under the model (must equal -14.7 dB)."""
    return req_snr_db(DL_ANCHOR["tbs"] + 24, DL_ANCHOR["nsf"] * NB_RE_SF, DL_ANCHOR["nrep"], beta)


# ------------------------------------------------------------------ inter-beam interference
def _hex_cochannel(reuse=3):
    """First-tier co-channel beam centres for hexagonal reuse K, in units of
    the -3 dB beam radius R (centre spacing sqrt(3) R, reuse distance
    sqrt(3K) R)."""
    d = math.sqrt(3 * reuse)
    rot = math.radians(30.0) if reuse == 3 else 0.0
    return [(d * math.cos(rot + k * math.pi / 3), d * math.sin(rot + k * math.pi / 3)) for k in range(6)]


def c_over_i_db(offset, phi, airy_rel_db, bw_deg, reuse=3):
    """Carrier-to-interference ratio of a device at radial offset `offset`
    (fraction of the -3 dB radius) and azimuth phi inside its beam."""
    x, y = offset * math.cos(phi), offset * math.sin(phi)
    half = bw_deg / 2
    want = airy_rel_db(offset * half, bw_deg)
    tot = 0.0
    for cx, cy in _hex_cochannel(reuse):
        u = math.hypot(x - cx, y - cy)
        tot += 10 ** (airy_rel_db(u * half, bw_deg) / 10)
    return want - 10 * math.log10(tot)


# ------------------------------------------------------------------ LoRaWAN acknowledgement downlink
ACK_PHY_B = 12              # MHDR 1 + DevAddr 4 + FCtrl 1 + FCnt 2 + MIC 4, no FPort, ACK bit set
RX2_DELAY_S = 2.0           # LoRaWAN RECEIVE_DELAY2


def ack_service(lam_ack, t_ack, duty, windows=1):
    """Fraction of acknowledgements that one satellite transmitter can send
    with no queue (Class A receive windows are fixed in time): single-server
    Erlang loss, a second chance in RX2 when RX1 is usable (windows=2, the
    two chances treated as independent), then the long-run duty-cycle budget.
    Returns (served fraction, carried transmitter occupancy)."""
    if lam_ack * t_ack <= 0:
        return 1.0, 0.0
    b = 0.0
    for _ in range(50):                      # offered load includes RX2 retries of RX1 blocks
        a = lam_ack * t_ack * (1 + (b if windows > 1 else 0.0))
        b_new = a / (1 + a)
        if abs(b_new - b) < 1e-9:
            break
        b = b_new
    s = 1 - b ** windows
    carried = lam_ack * t_ack * s
    if duty is not None and carried > duty:
        s *= duty / carried
        carried = duty
    return s, carried


def blank_ok_lrfhss(rng, frame, lam_tx, t_ack, th_s, tf_s):
    """LR-FHSS packet survives the gateway's own transmissions (half duplex) if
    at least one header replica and at least `need` fragments fall outside
    every transmit interval. Transmit starts are Poisson at rate lam_tx."""
    toa = frame["toa_s"]
    span = toa + t_ack
    n = rng.poisson(lam_tx * span) if lam_tx > 0 else 0
    if n == 0:
        return True
    iv = [(-t_ack + rng.random() * span) for _ in range(n)]
    iv = [(s, s + t_ack) for s in iv]
    hit = lambda a, b: any(s < b and e > a for s, e in iv)
    hdr_ok = any(not hit(k * th_s, (k + 1) * th_s) for k in range(frame["nh"]))
    t0 = frame["nh"] * th_s
    frag_ok = sum(1 for k in range(frame["nf"]) if not hit(t0 + k * tf_s, t0 + (k + 1) * tf_s))
    return hdr_ok and frag_ok >= frame["need"]
