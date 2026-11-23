"""Aggregate uplink interference density at the satellite receiver.

Integration is done over the full sphere of solid angle around the serving
beam axis (fine near the main lobe, logarithmic out to 180 deg, so Earth
directions behind a scanned beam are included). Each direction is intersected with the Earth;
the ground area seen in dOmega is dA = d^2 dOmega / sin(el). For every area
element the gain uses the true two-dimensional angle between the beam axis and
the emitter (antenna.gain_direction), so in-beam and side-lobe emitters are
counted exactly once.

    I0 = sum  rho * EIRP_eff * G(dir) * E[1/L(el)] * dA / band_hz

EIRP_eff already includes the emitter-side polarisation and penetration losses.
Results are cached: identical inputs are integrated only once per process.
"""
import math
from . import geometry as G
from . import channel as CH

_CACHE = {}


def _mean_inv_loss(env, el, mode="interp"):
    p = CH.los_probability(env, el, mode)
    s_l, _ = CH.sf_cl(env, el, True, mode)
    s_n, cl = CH.sf_cl(env, el, False, mode)
    lg = lambda s: math.exp((s * math.log(10) / 10) ** 2 / 2)
    return p * lg(s_l) + (1 - p) * lg(s_n) * 10 ** (-cl / 10)


def _ray_earth(sz, ux, uy, uz):
    """Satellite at (0,0,sz) with sz = RE+h, direction u. Returns (d, P) or None."""
    b = sz * uz
    disc = b * b - (sz * sz - G.RE_KM ** 2)
    if disc < 0:
        return None
    t = -b - math.sqrt(disc)
    if t <= 0:
        return None
    return t, (t * ux, t * uy, sz + t * uz)


def aggregate_i0_dbm_hz(ant, h_km, f_hz, density_km2, eirp_dbm, band_hz, env,
                        extra_loss_db=0.0, el_min_deg=5.0, serving_el_deg=None,
                        n_fine=160, n_coarse=160, n_az=72, angle_mode="interp"):
    if density_km2 <= 0:
        return -999.0
    axis_el = 90.0 if (ant.kind == "broad" or serving_el_deg is None) else serving_el_deg
    # value-based key (N10): full antenna configuration and numerical state,
    # propagation mode and quadrature settings
    import json as _json
    key = (_json.dumps(ant.cfg, sort_keys=True, default=str), ant.f, ant.kind, round(ant.g0, 6), round(ant.bw, 6),
           getattr(ant, "side_model", None), h_km, f_hz, density_km2, eirp_dbm, band_hz, env, extra_loss_db,
           el_min_deg, round(axis_el, 1), n_fine, n_coarse, n_az, angle_mode)
    if key in _CACHE:
        return _CACHE[key]
    sz = G.RE_KM + h_km
    # beam axis: from satellite toward the ground point at elevation axis_el (azimuth 0)
    a0 = math.radians(G.off_nadir_deg(h_km, axis_el))
    ax = (math.sin(a0), 0.0, -math.cos(a0))              # nadir is -z
    e1 = (math.cos(a0), 0.0, math.sin(a0))               # orthonormal basis around axis
    e2 = (0.0, 1.0, 0.0)
    smax = math.radians(180.0)             # whole sphere around the axis: scanned beams see Earth behind them (N06)
    s_fine = math.radians(min(max(12 * ant.bw, 3.0), 30.0))
    edges = [s_fine * i / n_fine for i in range(n_fine + 1)]
    edges += [s_fine * (smax / s_fine) ** (i / n_coarse) for i in range(1, n_coarse + 1)]
    eirp = 10 ** ((eirp_dbm - extra_loss_db) / 10)
    total = 0.0
    db_ = 2 * math.pi / n_az
    for k in range(len(edges) - 1):
        s0, s1 = edges[k], edges[k + 1]
        sm = 0.5 * (s0 + s1)
        dom_ring = 2 * math.pi * (math.cos(s0) - math.cos(s1))
        cs, ss = math.cos(sm), math.sin(sm)
        for j in range(n_az):
            be = (j + 0.5) * db_
            cb, sb = math.cos(be), math.sin(be)
            ux = cs * ax[0] + ss * (cb * e1[0] + sb * e2[0])
            uy = cs * ax[1] + ss * (cb * e1[1] + sb * e2[1])
            uz = cs * ax[2] + ss * (cb * e1[2] + sb * e2[2])
            hit = _ray_earth(sz, ux, uy, uz)
            if hit is None:
                continue
            d, P = hit
            # elevation at the ground point
            nx, ny, nz = P[0] / G.RE_KM, P[1] / G.RE_KM, P[2] / G.RE_KM
            sin_el = (-ux * nx - uy * ny - uz * nz)
            if sin_el <= math.sin(math.radians(el_min_deg)):
                continue
            el = math.degrees(math.asin(min(1.0, sin_el)))
            off = math.degrees(math.acos(max(-1.0, min(1.0, -uz))))
            g = ant.gain_direction(off, math.degrees(sm), be, math.degrees(a0))
            dA = d * d * dom_ring / n_az / sin_el
            l = 10 ** (-CH.fspl_db(d, f_hz) / 10) * _mean_inv_loss(env, max(el, 10.0), angle_mode)
            total += density_km2 * eirp * 10 ** (g / 10) * l * dA
    val = 10 * math.log10(total / band_hz) if total > 0 else -999.0
    _CACHE[key] = val
    return val


def noise_rise_db(i0_dbm_hz, n0_dbm_hz):
    if i0_dbm_hz <= -900:
        return 0.0
    return 10 * math.log10(1 + 10 ** ((i0_dbm_hz - n0_dbm_hz) / 10))


def effective_n0(n0_dbm_hz, i0_dbm_hz):
    if i0_dbm_hz <= -900:
        return n0_dbm_hz
    return 10 * math.log10(10 ** (n0_dbm_hz / 10) + 10 ** (i0_dbm_hz / 10))


def indoor_mix_loss_db(indoor_frac, bpl_db):
    """Mean linear penetration for a population with indoor fraction."""
    return -10 * math.log10((1 - indoor_frac) + indoor_frac * 10 ** (-bpl_db / 10))
