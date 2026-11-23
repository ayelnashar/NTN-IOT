"""Orbit geometry: Walker constellations, site visibility, range, Doppler.

Circular two-body orbits on a spherical Earth with Earth rotation. No J2, no
drag. Adequate for pass timing, elevation statistics and Doppler magnitude over
a 24 h window; not an ephemeris tool.
"""
import math

RE_KM = 6371.0
MU = 398600.4418            # km^3/s^2
OMEGA_E = 7.2921159e-5      # rad/s
C_KMS = 299792.458
C_MS = 299792458.0


# ---------------------------------------------------------------- closed form
def slant_range_km(h_km, elev_deg):
    """3GPP TR 38.811 eq. for distance satellite-device at elevation angle."""
    e = math.radians(elev_deg)
    return math.sqrt((RE_KM * math.sin(e)) ** 2 + h_km ** 2 + 2 * h_km * RE_KM) - RE_KM * math.sin(e)


def central_angle_rad(h_km, elev_deg):
    e = math.radians(elev_deg)
    return math.acos(RE_KM * math.cos(e) / (RE_KM + h_km)) - e


def elev_from_central_angle_deg(h_km, psi_rad):
    r = RE_KM + h_km
    d = math.sqrt(RE_KM ** 2 + r ** 2 - 2 * RE_KM * r * math.cos(psi_rad))
    s = (r * math.cos(psi_rad) - RE_KM) / d
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))


def off_nadir_deg(h_km, elev_deg):
    """Angle at the satellite between nadir and the device."""
    return math.degrees(math.asin(RE_KM * math.cos(math.radians(elev_deg)) / (RE_KM + h_km)))


def footprint_area_km2(h_km, elev_mask_deg):
    psi = central_angle_rad(h_km, elev_mask_deg)
    return 2 * math.pi * RE_KM ** 2 * (1 - math.cos(psi))


def orbital_period_s(h_km):
    return 2 * math.pi * math.sqrt((RE_KM + h_km) ** 3 / MU)


def orbital_speed_kms(h_km):
    return math.sqrt(MU / (RE_KM + h_km))


def max_doppler_hz(f_hz, h_km, elev_deg=0.0):
    """Upper bound for an overhead pass (Earth rotation neglected)."""
    v = orbital_speed_kms(h_km)
    return f_hz * v / C_KMS * RE_KM * math.cos(math.radians(elev_deg)) / (RE_KM + h_km)


# ---------------------------------------------------------------- propagation
def walker(n_sats, n_planes, inc_deg, h_km, phasing=1):
    """Walker-delta i:T/P/F. Returns list of dicts (raan, m0, inc, h)."""
    if n_sats % n_planes != 0:
        raise ValueError(f"Walker: {n_sats} satellites not divisible by {n_planes} planes")
    s = n_sats // n_planes
    sats = []
    for p in range(n_planes):
        raan = 2 * math.pi * p / n_planes
        for k in range(s):
            m0 = 2 * math.pi * k / s + 2 * math.pi * phasing * p / n_sats
            sats.append(dict(raan=raan, m0=m0, inc=math.radians(inc_deg), h=h_km))
    return sats


def sat_state(sat, t):
    """ECI position (km), velocity (km/s), acceleration (km/s^2)."""
    r = RE_KM + sat["h"]
    n = math.sqrt(MU / r ** 3)
    u = sat["m0"] + n * t
    cu, su = math.cos(u), math.sin(u)
    co, so = math.cos(sat["raan"]), math.sin(sat["raan"])
    ci, si = math.cos(sat["inc"]), math.sin(sat["inc"])
    pos = (r * (cu * co - su * ci * so), r * (cu * so + su * ci * co), r * su * si)
    v = r * n
    vel = (v * (-su * co - cu * ci * so), v * (-su * so + cu * ci * co), v * cu * si)
    acc = tuple(-MU * x / r ** 3 for x in pos)
    return pos, vel, acc


def site_state(lat_deg, lon_deg, t):
    la, lo = math.radians(lat_deg), math.radians(lon_deg) + OMEGA_E * t
    pos = (RE_KM * math.cos(la) * math.cos(lo), RE_KM * math.cos(la) * math.sin(lo), RE_KM * math.sin(la))
    vel = (-OMEGA_E * pos[1], OMEGA_E * pos[0], 0.0)
    acc = (-OMEGA_E ** 2 * pos[0], -OMEGA_E ** 2 * pos[1], 0.0)
    return pos, vel, acc


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def look(sat, lat, lon, t):
    """Elevation (deg), range (km), range rate (km/s), range acceleration (km/s^2)."""
    ps, vs, as_ = sat_state(sat, t)
    pg, vg, ag = site_state(lat, lon, t)
    rho = (ps[0] - pg[0], ps[1] - pg[1], ps[2] - pg[2])
    vr = (vs[0] - vg[0], vs[1] - vg[1], vs[2] - vg[2])
    ar = (as_[0] - ag[0], as_[1] - ag[1], as_[2] - ag[2])
    d = math.sqrt(_dot(rho, rho))
    up = tuple(x / RE_KM for x in pg)
    el = math.degrees(math.asin(_dot(rho, up) / d))
    rr = _dot(rho, vr) / d
    rra = (_dot(vr, vr) + _dot(rho, ar) - rr * rr) / d
    return el, d, rr, rra


def visibility_timeline(const, lat, lon, t_end_s=172800.0, dt_s=10.0, mask_deg=10.0, serving="sticky"):
    """Serving satellite per time step over a horizon longer than the arrival
    window, so messages generated late in the day still see future contacts.

    serving = 'sticky': keep the current satellite while it stays above the mask
    (handover only on loss); 'best': highest elevation each step.
    A contact (pass) is a contiguous run of the SAME serving satellite.
    Returns parallel lists t, vis, sid, el, d_km, rr_kms, rra, n_vis, next_vis,
    pass_end (index of the last step of the current contact). No wrap-around.
    """
    n = int(t_end_s / dt_s)
    T, V, SID, EL, D, RR, RRA, NV = [], [], [], [], [], [], [], []
    cur = None
    for i in range(n):
        t = i * dt_s
        looks = {}
        for k, s in enumerate(const):
            el, d, rr, rra = look(s, lat, lon, t)
            if el >= mask_deg:
                looks[k] = (el, d, rr, rra)
        if serving == "sticky" and cur in looks:
            k = cur
        elif looks:
            k = max(looks, key=lambda q: looks[q][0])
        else:
            k = None
        cur = k
        T.append(t); NV.append(len(looks)); SID.append(k)
        if k is not None:
            el, d, rr, rra = looks[k]
            V.append(True); EL.append(el); D.append(d); RR.append(rr); RRA.append(rra)
        else:
            V.append(False); EL.append(None); D.append(None); RR.append(None); RRA.append(None)
    nxt = [None] * n
    j = None
    for i in range(n - 1, -1, -1):
        if V[i]:
            j = i
        nxt[i] = j
    pend = [None] * n
    e = None
    for i in range(n - 1, -1, -1):
        if V[i]:
            if e is None or SID[i + 1 if i + 1 < n else i] != SID[i] or not V[min(i + 1, n - 1)]:
                e = i
            pend[i] = e
        else:
            e = None
    return dict(t=T, vis=V, sid=SID, el=EL, d_km=D, rr_kms=RR, rra=RRA, n_vis=NV,
                next_vis=nxt, pass_end=pend, dt=dt_s, t_end=t_end_s, mask=mask_deg, serving=serving)


def coverage_stats(tl, window_s=86400.0, start_s=0.0):
    """Coverage over [start_s, start_s + window_s]. Gaps touching the window
    edges are reported as censored; no contact reports the whole window."""
    i0 = int(start_s / tl["dt"])
    n = min(len(tl["vis"]) - i0, int(window_s / tl["dt"]))
    vis = tl["vis"][i0:i0 + n]
    frac = sum(vis) / n
    gaps, run, start = [], 0, 0
    for i, v in enumerate(vis):
        if not v:
            if run == 0:
                start = i
            run += 1
        elif run:
            gaps.append((run * tl["dt"], start == 0)); run = 0
    if run:
        gaps.append((run * tl["dt"], True))
    closed = sorted(g for g, c in gaps if not c)
    allg = sorted(g for g, _ in gaps)
    V, S = tl["vis"][i0:i0 + n], tl["sid"][i0:i0 + n]
    handovers = sum(1 for i in range(1, n) if V[i] and V[i - 1] and S[i] != S[i - 1])
    contacts = sum(1 for i in range(n) if V[i] and (i == 0 or not V[i - 1] or S[i] != S[i - 1]))
    p = lambda q, g: g[min(len(g) - 1, int(q * len(g)))] if g else 0.0
    return dict(coverage_fraction=frac, n_gaps=len(gaps), n_censored_gaps=len(gaps) - len(closed),
                mean_gap_s=(sum(allg) / len(allg)) if allg else 0.0, p95_gap_s=p(0.95, allg),
                max_gap_s=allg[-1] if allg else 0.0, contacts_per_day=contacts * 86400.0 / window_s,
                handovers_per_day=handovers * 86400.0 / window_s,
                never_visible=(frac == 0))
