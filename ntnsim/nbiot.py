"""NB-IoT NPUSCH format 1 link model built from 3GPP structures (F07).

Structures taken from the specifications:
  * TBS table (TS 36.213 Table 16.5.1.2-2), I_TBS 0..12 x N_RU {1,2,3,4,5,6,8,10};
    Rel-13 maximum 1000 bits; larger messages are segmented into transport
    blocks, each with its own HARQ process in the engine (the Rel-14 2536-bit
    TBS extension is not implemented);
  * resource-unit durations: 12 tones 1 ms, 6 tones 2 ms, 3 tones 4 ms,
    1 tone @15 kHz 8 ms, 1 tone @3.75 kHz 32 ms; 96 data REs per RU for single
    tone and 144 for multi-tone (one DMRS symbol per slot);
  * repetitions N_rep in {1,2,4,...,128}; single tone limited to I_TBS <= 10.

SNR mapping (the part not in the specifications):
    SNR_req = 10log10(2^(bits/RE) - 1) + GAP - beta * 10log10(N_rep)
GAP is calibrated to the published link-level point TBS 1000 / N_RU 10 /
N_rep 32 / 10 % BLER / -13.8 dB (Sensors 2020 Table 2, IMT-2020 164 dB case),
which assumes ideal combining (beta = 1, 'link_level' calibration).
Hardware measurements give 9.6-11.9 dB between N_rep 1 and 128 instead of the
ideal 21 dB (Electronics 2020, 9(11):1947), and the RAN4 single-tone
requirements improve 6.7 dB from 1 to 16 repetitions instead of 12 dB
(arXiv 1906.07096, Table 2): beta ~ 0.5 ('hardware' calibration, default; a
hardware-inspired sensitivity curve, not a deployment calibration).
A measured or link-level BLER table can replace the mapping (load_snr_table()).
"""
import math

TBS_REL13 = [  # rows I_TBS 0..12, columns N_RU = 1,2,3,4,5,6,8,10
    [16, 32, 56, 88, 120, 152, 208, 256],
    [24, 56, 88, 144, 176, 208, 256, 344],
    [32, 72, 144, 176, 208, 256, 328, 424],
    [40, 104, 176, 208, 256, 328, 440, 568],
    [56, 120, 208, 256, 328, 408, 552, 680],
    [72, 144, 224, 328, 424, 504, 680, 872],
    [88, 176, 256, 392, 504, 600, 808, 1000],
    [104, 224, 328, 472, 584, 712, 1000, None],
    [120, 256, 392, 536, 680, 808, None, None],
    [136, 296, 456, 616, 776, 936, None, None],
    [144, 328, 504, 680, 872, 1000, None, None],
    [176, 376, 584, 776, 1000, None, None, None],
    [208, 440, 680, 1000, None, None, None, None],
]
NRU = [1, 2, 3, 4, 5, 6, 8, 10]
NREP = [1, 2, 4, 8, 16, 32, 64, 128]
# allocation: (label, bandwidth Hz, RU duration s, data REs per RU, single-tone)
ALLOC = [("1x3.75k", 3750.0, 0.032, 96, True),
         ("1x15k", 15000.0, 0.008, 96, True),
         ("3x15k", 45000.0, 0.004, 144, False),
         ("6x15k", 90000.0, 0.002, 144, False),
         ("12x15k", 180000.0, 0.001, 144, False)]
ANCHOR = dict(tbs=1000, nru=10, nrep=32, alloc="1x15k", snr_db=-13.8)
# repetition efficiency beta. 'hardware' (0.5) is a hardware-inspired curve from
# single-tone 3.75 kHz measurements (9.6-11.9 dB for 1->128, beta 0.46-0.57),
# corroborated (not calibrated) by RAN4 ratios; it does NOT reproduce the
# anchor, which only beta = 1.0 ('link_level') does.
CALIBRATION = {"hardware": 0.5, "link_level": 1.0}
MAX_TBS = 1000      # Rel-13 only; the Rel-14 extension is not implemented
_SNR_TABLE = None


def _shannon_snr_db(bits_per_re):
    return 10 * math.log10(2 ** bits_per_re - 1)


def _gap_db():
    a = next(x for x in ALLOC if x[0] == ANCHOR["alloc"])
    bpr = (ANCHOR["tbs"] + 24) / (ANCHOR["nru"] * a[3])
    return ANCHOR["snr_db"] - (_shannon_snr_db(bpr) - 10 * math.log10(ANCHOR["nrep"]))


GAP_DB = _gap_db()


def load_snr_table(rows):
    """rows: iterable of dicts {alloc, itbs, nru, nrep, snr_db} from link-level
    or measured BLER = 10 % points; overrides the gap model where present."""
    global _SNR_TABLE
    _SNR_TABLE = {(r["alloc"], r["itbs"], r["nru"], r["nrep"]): r["snr_db"] for r in rows}


def required_snr_db(alloc, itbs, nru_i, nrep, tbs, beta=0.5):
    if _SNR_TABLE and (alloc[0], itbs, NRU[nru_i], nrep) in _SNR_TABLE:
        return _SNR_TABLE[(alloc[0], itbs, NRU[nru_i], nrep)]
    bpr = (tbs + 24) / (NRU[nru_i] * alloc[3])
    return _shannon_snr_db(bpr) + GAP_DB - beta * 10 * math.log10(nrep)


def frontier(msg_bits, max_tbs=MAX_TBS, calibration="hardware", objective="resource"):
    """Configurations able to carry msg_bits, reduced to a frontier over
    required C/N0 with a LEXICOGRAPHIC objective (M06):
      objective = 'resource': minimise bandwidth x time (cell capacity), then
                  airtime (device energy and latency) among equal resource;
      objective = 'airtime':  minimise airtime, then resource.
    Each frontier entry is the best configuration for every C/N0 at or above
    its own requirement, so select() remains a binary search.
    Messages above max_tbs are segmented into n_tb equal transport blocks sent
    with the same configuration (N11); each TB is decoded and HARQ-processed
    separately by the engine (M07). airtime_s and res_hz_s are message totals;
    tb_airtime_s is one transmission of one TB."""
    n_tb = max(1, math.ceil(msg_bits / max_tbs))
    tb_bits = math.ceil(msg_bits / n_tb)
    cands = []
    for a in ALLOC:
        for itbs, row in enumerate(TBS_REL13):
            if a[4] and itbs > 10:
                continue
            for ni, tbs in enumerate(row):
                if tbs is None or tbs < tb_bits or tbs > max_tbs:
                    continue
                for nrep in NREP:
                    snr = required_snr_db(a, itbs, ni, nrep, tbs, CALIBRATION[calibration])
                    cn0 = snr + 10 * math.log10(a[1])
                    t1 = NRU[ni] * a[2] * nrep
                    t = t1 * n_tb
                    cands.append(dict(alloc=a[0], b_hz=a[1], itbs=itbs, nru=NRU[ni], nrep=nrep, tbs=tbs, n_tb=n_tb,
                                      snr_req_db=snr, cn0_req_dbhz=cn0, airtime_s=t, tb_airtime_s=t1,
                                      res_hz_s=a[1] * t))
    keys = ("res_hz_s", "airtime_s") if objective == "resource" else ("airtime_s", "res_hz_s")
    lex = lambda c: (round(c[keys[0]], 9), round(c[keys[1]], 9))
    front, best = [], (float("inf"), float("inf"))
    for c in sorted(cands, key=lambda c: (c["cn0_req_dbhz"],) + lex(c)):
        if lex(c) < best:
            front.append(c); best = lex(c)
    return front


def select(front, cn0_dbhz):
    """Best configuration (frontier objective) whose required C/N0 is met, or None."""
    lo, hi, best = 0, len(front) - 1, None
    while lo <= hi:
        m = (lo + hi) // 2
        if front[m]["cn0_req_dbhz"] <= cn0_dbhz:
            best = front[m]; lo = m + 1
        else:
            hi = m - 1
    return best


def mcl_at_floor(msg_bits, ptx_dbm=23.0, nf_db=5.0, calibration="hardware"):
    """Coupling loss supported by the most robust configuration (terrestrial
    reference, no antenna gains, kT at 290 K)."""
    f = frontier(msg_bits, calibration=calibration)
    c = f[0]
    return ptx_dbm - (-174 + nf_db + c["cn0_req_dbhz"]), c
