"""Medium access: target-centric Monte Carlo for LoRa and LR-FHSS, and a
contention + scheduled-capacity model for NB-IoT / LTE-M NTN.

LoRa:    pure ALOHA per (channel, SF); co-SF interferers overlapping the target
         are Poisson with mean lambda_ch * 2T; success needs SNR >= threshold and
         SIR >= capture threshold against the SUM of interferers.
LR-FHSS: every header replica and payload fragment is checked separately on a
         random OBW channel, with interfering headers/fragments from other
         devices (Ullah et al. 2022 overlap counts) plus capture; decode needs
         >= 1 header and the CR-dependent fraction of fragments.
3GPP:    NPRACH preamble contention (M preambles per opportunity, retries) and
         uplink tone-time capacity per carrier; data is scheduled, so there are
         no data collisions, only queueing / blocking when demand exceeds capacity.
"""
import math


def db(x):
    return 10 * math.log10(x)


class Pool(list):
    """Interferer received powers (mW) with cached moments for large-k sums."""
    def __init__(self, vals):
        super().__init__(vals)
        n = len(vals)
        self.mean = sum(vals) / n
        self.std = math.sqrt(max(sum((v - self.mean) ** 2 for v in vals) / n, 0.0))


def interference_sum(rng, k, pool):
    """Sum of k interferer powers drawn from the pool; CLT shortcut above 200."""
    if k > 200:
        return max(k * pool.mean + math.sqrt(k) * pool.std * rng.normal(), 1e-30)
    n = len(pool)
    s = 0.0
    for _ in range(k):
        s += pool[rng.randint(n)]
    return s


def lin(x_db):
    return 10 ** (x_db / 10)


# ------------------------------------------------------------------ LoRa
def lora_attempt(rng, snr_db, snr_req_db, p_t_mw, k_mean, pool_mw, capture_db=6.0):
    """Returns (success, cause) with cause in {'ok','snr','collision'}."""
    if snr_db < snr_req_db:
        return False, "snr"
    k = rng.poisson(k_mean)
    if k == 0:
        return True, "ok"
    s = interference_sum(rng, k, pool_mw)
    if db(p_t_mw / s) >= capture_db:
        return True, "ok"
    return False, "collision"


# ------------------------------------------------------------------ LR-FHSS
LRFHSS_TH = 0.233472
def lrfhss_overlap_means(lam_pkts, frame):
    """Mean number of interfering elements on the same OBW channel overlapping
    a header and a fragment (Ullah et al. 2022, eqs. for A_h and A_f / C)."""
    th, tf = 0.233472, 0.1024
    lh, lf = frame["nh"] * lam_pkts, frame["nf"] * lam_pkts
    C = frame["C"]
    a_h = (lh * 2 * th + lf * (th + tf)) / C
    a_f = (lf * 2 * tf + lh * (th + tf)) / C
    return a_h, a_f


def _element_ok(rng, snr_db, thr, p_mw, k_mean, pool_mw, capture_db, fade_k_db):
    g = rng.rician_power(fade_k_db) if fade_k_db is not False else 1.0
    if snr_db + db(max(g, 1e-12)) < thr:
        return False, "snr"
    k = rng.poisson(k_mean)
    if k == 0:
        return True, "ok"
    s = interference_sum(rng, k, pool_mw)
    if db(p_mw * g / s) >= capture_db:
        return True, "ok"
    return False, "collision"


def lrfhss_attempt(rng, snr_db, frame, p_t_mw, a_h, a_f, pool_mw, capture_db=6.0,
                   fade_k_db=10.0):
    thr = frame["snr_req_db"]
    hdr_ok, causes = 0, {"snr": 0, "collision": 0}
    for _ in range(frame["nh"]):
        ok, c = _element_ok(rng, snr_db, thr, p_t_mw, a_h, pool_mw, capture_db, fade_k_db)
        if ok:
            hdr_ok += 1
        else:
            causes[c] += 1
    if hdr_ok == 0:
        return False, "snr" if causes["snr"] >= causes["collision"] else "collision"
    got, left = 0, frame["nf"]
    for _ in range(frame["nf"]):
        ok, c = _element_ok(rng, snr_db, thr, p_t_mw, a_f, pool_mw, capture_db, fade_k_db)
        left -= 1
        if ok:
            got += 1
        else:
            causes[c] += 1
        if got >= frame["need"]:
            return True, "ok"
        if got + left < frame["need"]:
            break
    return False, "snr" if causes["snr"] >= causes["collision"] else "collision"


def lrfhss_elements(frame):
    """Relative (start, end) times of the header replicas and payload hops."""
    th, tf = 0.233472, 0.1024
    el, t = [], 0.0
    for _ in range(frame["nh"]):
        el.append((t, t + th)); t += th
    for k in range(frame["nf"]):
        d = tf if k < frame["nf"] - 1 else frame.get("t_last_s", tf)
        el.append((t, t + d)); t += d
    return el



def faded_gain(rng, fades, t0, t1, coh_s, k_db):
    """Duration-weighted mean fading power over [t0, t1) on a channel made of
    independent Rician blocks of length coh_s (P03). fades caches one draw per
    block index, so every receiver and every retransmission sharing the same
    clock sees the same channel; zero-overlap blocks are excluded."""
    if k_db is False:
        return 1.0
    coh = max(coh_s, 1e-3)
    dur = t1 - t0
    if dur <= 0:
        b = int(t0 // coh)
        if b not in fades:
            fades[b] = rng.rician_power(k_db)
        return fades[b]
    b0, b1 = int(t0 // coh), int(t1 // coh)
    if (b1 + 1) * coh - t1 >= coh - 1e-12:      # t1 exactly on a boundary: the next block has zero overlap
        b1 -= 1
    if b1 - b0 > 255:                            # very long transmissions: 256 equally spaced blocks
        blks = [b0 + (b1 - b0) * q // 255 for q in range(256)]
        acc = 0.0
        for b in blks:
            if b not in fades:
                fades[b] = rng.rician_power(k_db)
            acc += fades[b]
        return acc / len(blks)
    acc = 0.0
    for b in range(b0, b1 + 1):
        ov = min(t1, (b + 1) * coh) - max(t0, b * coh)
        if ov > 0:
            if b not in fades:
                fades[b] = rng.rician_power(k_db)
            acc += fades[b] * ov
    return acc / dur


def lrfhss_attempt_packet(rng, snr_db, frame, p_t_mw, lam_pkts, pool_mw, capture_db=6.0,
                          fade_k_db=10.0, n_grids=8, coh_s=1.0, max_packets=200, fades=None, t_start=None,
                          return_flags=False):
    """Packet-level LR-FHSS reception (F14, N04, M03).

    * Interfering packets arrive as a Poisson process over the two-packet
      vulnerability window; only packets on the target's hopping grid
      (1 of n_grids) can collide.
    * Every packet (target and interferers) carries a PERSISTENT hopping
      sequence: one channel per element drawn once from frame['grid']
      channels, never repeating the previous hop.
    * For each target element, interference is the time-weighted power of
      co-channel interferer elements: sum over overlaps of P_i * overlap /
      element duration.
    * Decoding uses SIR (time-averaged) >= capture and SNR >= threshold per
      element; target fading is the duration-weighted mean over the coherence
      blocks each element spans, on a channel clock with random block phase
      (P03); passing `fades` and `t_start` shares that channel with other
      copies of the same message.
    * Above max_packets same-grid packets the interferer enumeration is
      replaced by an ELEMENT-LEVEL Poisson APPROXIMATION with the same
      per-channel element rates, exact overlap weighting and the same target
      fading. It drops packet clustering, the shared power of one interferer
      across target elements, hop persistence, and unequal fragment lengths
      (mean fragment length). Its deviation from enumeration near the switch
      is quantified in validate.py and reported as a limitation (P06). The
      third return value flags the branch.
    Returns (ok, cause, used_element_branch), plus the per-element decode
    flags (headers first) when return_flags is set (v1.7 joint blanking mask;
    no extra random draws)."""
    el = lrfhss_elements(frame)
    T = el[-1][1]
    cg = frame["grid"]
    k = rng.poisson(lam_pkts * 2 * T / n_grids)
    big = k > max_packets
    thr = frame["snr_req_db"]
    n = len(pool_mw)

    def hop_seq():
        seq, prev = [], -1
        for _ in el:
            c = rng.randint(cg)
            if c == prev:
                c = (c + 1 + rng.randint(cg - 1)) % cg
            seq.append(c); prev = c
        return seq
    tgt = hop_seq()
    if big:   # per-channel element arrival rates (elements/s) on the target grid
        durs = [b - a for a, b in el[frame["nh"]:]]
        r_h = lam_pkts / n_grids * frame["nh"] / cg
        r_f = lam_pkts / n_grids * frame["nf"] / cg
        d_f = sum(durs) / len(durs)
        inter = None
    else:
        # interferer elements bucketed by channel: (start, end, power) in target time (same draws as before)
        # only hops that overlap the target in time are drawn (others cannot interfere); the
        # no-repeat rule is kept between consecutive drawn hops
        inter = [[] for _ in range(cg)]
        for _ in range(k):
            off, pw = rng.uniform(-T, T), pool_mw[rng.randint(n)]
            prev = -1
            for s0, e0 in el:
                if e0 + off <= 0.0:
                    continue
                if s0 + off >= T:
                    break
                c = rng.randint(cg)
                if c == prev:
                    c = (c + 1 + rng.randint(cg - 1)) % cg
                prev = c
                inter[c].append((s0 + off, e0 + off, pw))
    if fades is None:
        fades = {}
    t0 = rng.random() * max(coh_s, 1e-3) if t_start is None else t_start
    n_snr = n_col = 0
    ok_flags = []
    for idx, (a, b) in enumerate(el):
        g = faded_gain(rng, fades, t0 + a, t0 + b, coh_s, fade_k_db)
        if snr_db + db(max(g, 1e-12)) < thr:
            ok_flags.append(False); n_snr += 1; continue
        dur = b - a
        s_int = 0.0
        if big:
            for r, d in ((r_h, LRFHSS_TH), (r_f, d_f)):
                for _ in range(rng.poisson(r * (dur + d))):
                    st = a - d + rng.random() * (dur + d)
                    ov = min(b, st + d) - max(a, st)
                    if ov > 0:
                        s_int += pool_mw[rng.randint(n)] * ov / dur
        else:
            for s0, e0, pw in inter[tgt[idx]]:
                lo, hi = max(a, s0), min(b, e0)
                if hi > lo:
                    s_int += pw * (hi - lo) / dur
        good = s_int == 0.0 or db(p_t_mw * g / s_int) >= capture_db
        ok_flags.append(good)
        n_col += 0 if good else 1
    hdr = sum(ok_flags[:frame["nh"]])
    frag = sum(ok_flags[frame["nh"]:])
    if hdr >= 1 and frag >= frame["need"]:
        return (True, "ok", big, ok_flags) if return_flags else (True, "ok", big)
    res = (False, ("snr" if n_snr >= n_col else "collision"), big)
    return res + (ok_flags,) if return_flags else res


def lrfhss_analytic(lam_pkts, frame, zeta=1.0):
    """Closed-form success probability, no capture (Ullah et al. 2022)."""
    th, tf = 0.233472, 0.1024
    lh, lf = frame["nh"] * lam_pkts, frame["nf"] * lam_pkts
    C = frame["C"]
    Ah = 2 * lh * th + lf * (th + tf)
    Af = 2 * lf * tf + lh * (th + tf)
    ph = 1 - (1 - zeta * (1 - 1 / C) ** Ah) ** frame["nh"]
    po = zeta * (1 - 1 / C) ** Af
    nf, need = frame["nf"], frame["need"]
    pf = 1 - sum(math.comb(nf, k) * po ** k * (1 - po) ** (nf - k) for k in range(need))
    return ph * pf


def aloha_analytic(g_per_channel):
    return math.exp(-2 * g_per_channel)


# ------------------------------------------------------------------ 3GPP
def nprach_success(lam_msgs, t_prach_s, n_preambles, n_max):
    """Fixed point: attempt rate inflated by retries; returns (p_access, p_coll,
    mean_attempts)."""
    p = 0.0
    for _ in range(200):
        retry = sum(p ** n for n in range(n_max))
        lam_att = lam_msgs * retry
        m = lam_att * t_prach_s
        p_new = 1 - math.exp(-m / n_preambles)
        if abs(p_new - p) < 1e-10:
            break
        p = 0.5 * p + 0.5 * p_new
    p_acc = 1 - p ** n_max
    mean_att = sum((n + 1) * (p ** n) * (1 - p) for n in range(n_max)) + n_max * p ** n_max
    return p_acc, p, mean_att


def scheduled_capacity(lam_msgs, mean_res_hz_s, carriers, carrier_hz, overhead_frac,
                       mean_t_s):
    """Utilisation, served fraction and M/D/1-style queueing delay."""
    avail = carriers * carrier_hz * (1 - overhead_frac)
    rho = lam_msgs * mean_res_hz_s / avail
    if rho >= 1:
        return rho, 1.0 / rho, float("inf")
    w = rho / (2 * (1 - rho)) * mean_t_s
    return rho, 1.0, w
