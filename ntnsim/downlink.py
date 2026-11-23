"""Downlink model (v1.7): link budget, 3GPP downlink control and data
channels, and the LoRaWAN acknowledgement downlink.

Link budget
    Small satellites use the EIRP density of the small-satellite parameter set
    of 3GPP TR 36.763 Section 6.2.1 (Set-4, LEO-600, 21.45 dBW/MHz), held as a
    fixed EIRP (not rescaled with the antenna gain). Arrays use an assumed RF
    power density of 8.5 dBW/MHz (attributed to a public experimental-license
    exhibit for a 64 m2 array) plus the aperture gain at the downlink
    frequency. In the ISM band the model imposes the terrestrial short-range-
    device limits as an engineering cap: RX2 in 869.40-869.65 MHz (500 mW
    e.r.p., 10 % duty cycle) and RX1 on the uplink channel in 868.0-868.6 MHz
    (25 mW e.r.p., 1 % duty cycle), ERC/REC 70-03 Annex 1. The slant range,
    clutter and shadowing, building loss and allowances are the uplink
    realisation of the same device; free-space loss and the multibeam pattern
    are evaluated at the downlink frequency in the same physical direction.
    Fast fading is drawn independently (FDD separation). Device noise figure:
    7 dB for cellular modules (TR 36.763 PC3 assumption) and 6 dB for LoRa
    transceivers (SX1262 sensitivity of -137 dBm at SF12/125 kHz). Multibeam
    satellites add inter-beam interference from six first-tier co-channel
    beams at frequency reuse 3 (TR 38.821 FRF 3), all transmitting; beam
    centres are fixed on the ground by the uplink footprint and the gains are
    evaluated with the downlink beamwidth.

3GPP channels (NB-IoT NPDCCH/NPDSCH; LTE-M MPDCCH/PDSCH)
    Same Shannon-gap abstraction as the uplink:
        SNR_req = 10log10(2^(bits/RE) - 1) + GAP_DL - beta 10log10(R)
    with GAP_DL anchored to the published NPDSCH reference point TBS 680,
    8 subframes, 128 repetitions, 10 % BLER at -14.7 dB (Matz et al., Sensors
    2020, Table 2, the IMT-2020 164 dB case) for the active repetition
    efficiency beta, so the anchor is reproduced in both calibrations (a
    pivoted sensitivity: the gap is refitted for each beta). Cell acquisition
    (NPSS/NSSS/NPBCH) is not modelled at symbol level; the NPDSCH reference
    threshold of -14.7 dB is adopted as an acquisition assumption.
    Declared configuration: NB-IoT standalone carrier, 152 RE per subframe
    (168 minus 16 NRS), maximum DL TBS 680 bits; LTE-M one 1.4 MHz narrowband
    (6 PRB, 3-symbol legacy control region and CRS, 720 RE), MPDCCH at
    aggregation level 24 over the narrowband, PDSCH in the same narrowband in
    later subframes, maximum DL TBS 1000 bits, PDSCH repetitions up to 32 in
    CE mode A (levels 0-1) and 2048 in CE mode B (level 2), MPDCCH up to 256.
    Control and data parts of one message are sequential.

Random-access response (v1.7)
    One MAC PDU per non-empty NPRACH occasion and level carries one 7-byte
    subheader plus RAR per detected preamble (collided preambles included).
    With Poisson attempts each of n_p preambles is occupied independently with
    probability q = 1 - exp(-m/n_p), so the number of distinct detected
    preambles is Binomial(n_p, q). A PDU holds at most floor(TBS_max/56) RARs;
    larger batches are split into several PDUs. The RAR carries the uplink
    grant of the first Msg3 (EDT) transmission.
"""
import math

NB_RE_SF = 152
LTEM_RE_SF = 720
DL_ANCHOR = dict(tbs=680, nsf=8, nrep=128, snr_db=-14.7)
SNR_FLOOR_DB = -14.7
REPS = [2 ** k for k in range(12)]          # 1 ... 2048
NSF = [1, 2, 3, 4, 5, 6, 8, 10]
TECH = {
    # dci_bits: assumed payload + 16-bit CRC; rmax_ctrl: control-channel repetition limit;
    # rmax_data: shared-channel repetition limit per coverage level (LTE-M: CE mode A, A, B);
    # avail: assumed fraction of downlink subframes left after sync, broadcast and system information
    "NBIOT": dict(re_sf=NB_RE_SF, bw_hz=180e3, dci_bits=23 + 16, rmax_ctrl=2048, rmax_data=[2048, 2048, 2048],
                  nsf=NSF, avail=0.70, tbs_max=680),
    "LTEM": dict(re_sf=LTEM_RE_SF, bw_hz=1.08e6, dci_bits=29 + 16, rmax_ctrl=256, rmax_data=[32, 32, 2048],
                 nsf=[1], avail=0.80, tbs_max=1000),
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


def _rmax_data(tech, level):
    rm = TECH[tech]["rmax_data"]
    return rm[min(max(level, 0), len(rm) - 1)]


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
            return dict(sf=r, req=q, nsf=1, r=r, bits=t["dci_bits"], cap=t["rmax_ctrl"])
    return None


def data_config(tech, bits, snr_db, beta, margin_db, floor_db=SNR_FLOOR_DB, level=2):
    """Fewest subframes (N_SF x R) of a shared-channel transport block, with
    the repetition limit of the coverage level (CE mode for LTE-M)."""
    t = TECH[tech]
    if snr_db < floor_db:
        return None
    cap = _rmax_data(tech, level)
    best = None
    for nsf in t["nsf"]:
        for r in REPS:
            if r > cap:
                break
            q = req_snr_db(bits + 24, nsf * t["re_sf"], r, beta)
            if q <= snr_db - margin_db:
                if best is None or nsf * r < best["sf"]:
                    best = dict(sf=nsf * r, req=q, nsf=nsf, r=r, bits=bits + 24, cap=cap)
                break
    return best


def message_config(tech, bits, snr_db, beta, margin_db, floor_db=SNR_FLOOR_DB, level=2):
    """Control (DCI) plus optional shared-channel part. Returns total
    subframes, the binding requirement and the two parts, or None."""
    c = ctrl_config(tech, snr_db, beta, margin_db, floor_db)
    if c is None:
        return None
    if not bits:
        return dict(sf=c["sf"], req=c["req"], ctrl=c, data=None)
    d = data_config(tech, bits, snr_db, beta, margin_db, floor_db, level)
    if d is None:
        return None
    return dict(sf=c["sf"] + d["sf"], req=max(c["req"], d["req"]), ctrl=c, data=d)


def escalate(tech, cfg, k, beta):
    """k-th network re-send of a missed downlink message (v1.7): each part keeps
    its N_SF and its repetitions become min(R 2^k, R_max) with the channel's
    own limit (CE-mode limit for LTE-M PDSCH); the requirement is recomputed
    for the new repetition number. Returns (subframes, req)."""
    t = TECH[tech]
    sf, req = 0, -1e9
    for part in [cfg["ctrl"]] + ([cfg["data"]] if cfg.get("data") else []):
        r = min(part["r"] * 2 ** k, part["cap"])
        sf += part["nsf"] * r
        req = max(req, req_snr_db(part["bits"], part["nsf"] * t["re_sf"], r, beta))
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
    """Single-RAR response per coverage level, configured for the level's lower
    SNR threshold (kept for reference and validation)."""
    return [message_config(tech, RAR_BITS, t, beta, margin_db, floor_db, i)
            for i, t in enumerate(ce_thresholds(beta, floor_db))]


def rar_per_pdu(tech):
    return max(1, TECH[tech]["tbs_max"] // RAR_BITS)


def rar_pdu_table(tech, beta, margin_db, floor_db=SNR_FLOOR_DB):
    """tab[level][d] = configuration of one RAR MAC PDU carrying d RARs, set for
    the level's lower SNR threshold, for d = 1 up to the largest feasible
    size (TBS limit and, for LTE-M, the CE-mode repetition limit)."""
    n = rar_per_pdu(tech)
    tab = []
    for i, t in enumerate(ce_thresholds(beta, floor_db)):
        row = [None]
        for d in range(1, n + 1):
            c = message_config(tech, RAR_BITS * d, t, beta, margin_db, floor_db, i)
            if c is None:
                break
            row.append(c)
        if len(row) == 1:
            raise ValueError("no feasible RAR configuration at level %d" % i)
        tab.append(row)
    return tab


def rar_batch_pdus(tech, d, n=None):
    """Sizes of the PDUs that carry d detected preambles (at most n per PDU)."""
    n = n or rar_per_pdu(tech)
    return [n] * (d // n) + ([d % n] if d % n else [])


def binom_pmf(n, q):
    return [math.comb(n, k) * q ** k * (1 - q) ** (n - k) for k in range(n + 1)]


def rar_occasion_moments(tech, tab_level, n_pre, m):
    """Non-empty-occasion probability and the first two moments of the RAR
    service time (s) per non-empty occasion, for mean m attempts per occasion
    spread uniformly over n_pre preambles (Poisson arrivals)."""
    if m <= 0:
        return 0.0, 0.0, 0.0
    av = TECH[tech]["avail"]
    q = 1 - math.exp(-m / n_pre)
    pmf = binom_pmf(n_pre, q)
    p_ne = 1 - pmf[0]
    if p_ne <= 0:
        return 0.0, 0.0, 0.0
    e1 = e2 = 0.0
    nmax = len(tab_level) - 1
    for d in range(1, n_pre + 1):
        sv = sum(tab_level[k]["sf"] for k in rar_batch_pdus(tech, d, nmax)) * 1e-3 / av
        e1 += pmf[d] * sv; e2 += pmf[d] * sv * sv
    return p_ne, e1 / p_ne, e2 / p_ne


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


def c_over_i_db(offset, phi, airy_rel_db, bw_deg, reuse=3, bw_eval_deg=None):
    """Carrier-to-interference ratio of a device at radial offset `offset`
    (fraction of the uplink -3 dB radius, which fixes the beam layout on the
    ground) and azimuth phi inside its beam. Gains are evaluated with the
    downlink beamwidth bw_eval_deg (default: the layout beamwidth)."""
    x, y = offset * math.cos(phi), offset * math.sin(phi)
    half = bw_deg / 2
    bwe = bw_eval_deg or bw_deg
    want = airy_rel_db(offset * half, bwe)
    tot = 0.0
    for cx, cy in _hex_cochannel(reuse):
        u = math.hypot(x - cx, y - cy)
        tot += 10 ** (airy_rel_db(u * half, bwe) / 10)
    return want - 10 * math.log10(tot)


# ------------------------------------------------------------------ LoRaWAN acknowledgement downlink
ACK_PHY_B = 12              # MHDR 1 + DevAddr 4 + FCtrl 1 + FCnt 2 + MIC 4, no FPort, ACK bit set
RX1_DELAY_S = 1.0           # LoRaWAN RECEIVE_DELAY1
RX2_DELAY_S = 2.0           # LoRaWAN RECEIVE_DELAY2
RX1_SF_LRFHSS = 11          # RP002 EU868 RX1 mapping, RX1DROffset 0: DR8 -> DR1 (SF11/125 kHz)
ISM_RX1_EIRP_DBM = 16.15    # 25 mW e.r.p. on the uplink channel (868.0-868.6 MHz)
ISM_RX1_DUTY = 0.01


def ack_calendar_params(lam_ack, wins, iters=60):
    """Single half-duplex transmitter serving acknowledgements as a loss
    system (Class A windows are fixed in time, no queue). wins: list of
    dict(used, t, duty) for RX1 and RX2. An acknowledgement goes to RX1 when
    used and the transmitter is idle and the RX1 duty budget admits it,
    otherwise to RX2 under the same conditions. Duty budgets thin the
    admissions so each window's carried occupancy stays at its limit.
    Returns dict(rate=lam_eff, occ, a=[a1, a2], share=[s1, s2], lam=[l1, l2])
    describing the stationary on-off calendar (idle ~ Exp(lam_eff), busy of
    length t_w with probability share_w)."""
    if lam_ack <= 0:
        return dict(rate=0.0, occ=0.0, a=[1.0, 1.0], share=[0.0, 1.0], lam=[0.0, 0.0], served=1.0)
    occ, a = 0.0, [1.0, 1.0]
    for _ in range(iters):
        l1 = lam_ack if wins[0]["used"] else 0.0
        l2 = lam_ack - l1 * (1 - occ) * a[0]
        lam = [l1, l2]
        for w in range(2):
            d = wins[w]["duty"]
            if d is not None and lam[w] > 0:
                a[w] = min(1.0, d / (lam[w] * (1 - occ) * wins[w]["t"]))
            else:
                a[w] = 1.0
        lam_eff = l1 * a[0] + l2 * a[1]
        tbar = (l1 * a[0] * wins[0]["t"] + l2 * a[1] * wins[1]["t"]) / lam_eff if lam_eff > 0 else 0.0
        occ_new = lam_eff * tbar / (1 + lam_eff * tbar)
        if abs(occ_new - occ) < 1e-12:
            occ = occ_new
            break
        occ = 0.5 * occ + 0.5 * occ_new
    share = [l1 * a[0] / lam_eff, l2 * a[1] / lam_eff] if lam_eff > 0 else [0.0, 1.0]
    served = ((l1 * a[0] + (lam_ack - l1 * (1 - occ) * a[0]) * a[1]) * (1 - occ)) / lam_ack
    return dict(rate=lam_eff, occ=occ, a=list(a), share=share, lam=lam, served=served)


def sample_calendar(rng, cal, t_lo, t_hi, wins):
    """Busy intervals of the stationary on-off transmitter calendar on
    [t_lo, t_hi]: non-overlapping by construction."""
    if cal["rate"] <= 0:
        return []
    def busy_len():
        return wins[0]["t"] if rng.random() < cal["share"][0] else wins[1]["t"]
    iv, t = [], t_lo
    if rng.random() < cal["occ"]:
        b = busy_len()
        e = t + rng.random() * b
        iv.append((t - (b - (e - t)), e)); t = e
    while t < t_hi:
        t += -math.log(1.0 - rng.random()) / cal["rate"]
        if t >= t_hi:
            break
        b = busy_len()
        iv.append((t, t + b)); t += b
    return iv


def busy_at(iv, t):
    return any(s <= t < e for s, e in iv)


def overlaps(iv, a, b):
    return any(s < b and e > a for s, e in iv)


def ack_service(lam_ack, t_ack, duty, windows=1):
    """v1.6 average-cap approximation (kept for comparison in validate.py)."""
    if lam_ack * t_ack <= 0:
        return 1.0, 0.0
    b = 0.0
    for _ in range(50):
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


def joint_lrfhss_ok(flags, frame, t0, iv, th_s, tf_s):
    """v1.7 joint mask: an element counts only if it was decoded (flags) and
    is not blanked by the gateway's own transmissions; the packet needs one
    such header replica and `need` such fragments."""
    nh = frame["nh"]
    hdr = sum(1 for k in range(nh) if flags[k] and not overlaps(iv, t0 + k * th_s, t0 + (k + 1) * th_s))
    tb = t0 + nh * th_s
    frag = 0
    for k in range(frame["nf"]):
        d = tf_s if k < frame["nf"] - 1 else frame.get("t_last_s", tf_s)
        if flags[nh + k] and not overlaps(iv, tb, tb + d):
            frag += 1
        tb += d
    return hdr >= 1 and frag >= frame["need"]
