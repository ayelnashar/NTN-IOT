"""Device-to-satellite channel: 3GPP TR 38.811 Sec. 6.6 path loss model.

PL = FSPL + SF + CL (+ gas, scintillation, polarisation, device-side losses).
LOS probability: TR 38.811 Table 6.6.1-1.
Shadow fading sigma and clutter loss: TR 38.811 Tables 6.6.2-1..3, S-band
columns. 38.811 tabulates S-band and Ka-band only; applying the S-band values
at 0.8-0.9 GHz is an extrapolation and is reported as such.
"""
import math

ELEVS = [10, 20, 30, 40, 50, 60, 70, 80, 90]

LOS_PROB = {   # percent
    "dense_urban": [28.2, 33.1, 39.8, 46.8, 53.7, 61.2, 73.8, 82.0, 98.1],
    "urban":       [24.6, 38.6, 49.3, 61.3, 72.6, 80.5, 91.9, 96.8, 99.2],
    "suburban":    [78.2, 86.9, 91.9, 92.9, 93.5, 94.0, 94.9, 95.2, 99.8],
    "rural":       [78.2, 86.9, 91.9, 92.9, 93.5, 94.0, 94.9, 95.2, 99.8],
}

SBAND = {   # (sigma_LOS, sigma_NLOS, CL_NLOS) in dB
    "dense_urban": ([3.5, 3.4, 2.9, 3.0, 3.1, 2.7, 2.5, 2.3, 1.2],
                    [15.5, 13.9, 12.4, 11.7, 10.6, 10.5, 10.1, 9.2, 9.2],
                    [34.3, 30.9, 29.0, 27.7, 26.8, 26.2, 25.8, 25.5, 25.5]),
    "urban":       ([4.0] * 9, [6.0] * 9,
                    [34.3, 30.9, 29.0, 27.7, 26.8, 26.2, 25.8, 25.5, 25.5]),
    "suburban":    ([1.79, 1.14, 1.14, 0.92, 1.42, 1.56, 0.85, 0.72, 0.72],
                    [8.93, 9.08, 8.78, 10.25, 10.56, 10.74, 10.17, 11.52, 11.52],
                    [19.52, 18.17, 18.42, 18.28, 18.63, 17.68, 16.50, 16.30, 16.30]),
}
SBAND["rural"] = SBAND["suburban"]


# Angle handling is passed explicitly per call (no module state, F10/N10):
# mode = 'interp' (linear between reference angles, extrapolation mode) or
# 'nearest' (TR 38.811 reference-angle reproduction).


def _interp(table, el, mode="interp"):
    el = max(10.0, min(90.0, el))
    if mode == "nearest":
        return table[min(8, int(round((el - 10) / 10.0)))]
    i = min(int((el - 10) // 10), 7)
    w = (el - ELEVS[i]) / 10.0
    return table[i] * (1 - w) + table[i + 1] * w


def fspl_db(d_km, f_hz):
    return 32.45 + 20 * math.log10(f_hz / 1e6) + 20 * math.log10(d_km)


def los_probability(env, el, mode="interp"):
    return _interp(LOS_PROB[env], el, mode) / 100.0


def sf_cl(env, el, los, mode="interp"):
    s_los, s_nlos, cl = SBAND[env]
    if los:
        return _interp(s_los, el, mode), 0.0
    return _interp(s_nlos, el, mode), _interp(cl, el, mode)


def sample_loss_db(env, el, rng, mode="interp"):
    """Random SF + CL draw. Returns (los, extra_loss_db)."""
    los = rng.random() < los_probability(env, el, mode)
    sig, cl = sf_cl(env, el, los, mode)
    return los, rng.normal(0.0, sig) + cl


def median_loss_db(env, el, los=True, mode="interp"):
    return sf_cl(env, el, los, mode)[1]


def expected_extra_loss_db(env, el, mode="interp"):
    """LOS-probability-weighted mean of CL (SF is zero-mean)."""
    p = los_probability(env, el, mode)
    return (1 - p) * sf_cl(env, el, False, mode)[1]
