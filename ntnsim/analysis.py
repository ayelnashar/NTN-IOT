"""Comparison metrics: link budget, path loss, coverage, cell radius,
throughput, capacity and interference.

Everything except capacity() is closed-form (no Monte Carlo) so it ports
one-to-one to the HTML simulator. capacity() and goodput_curve() call the
Monte Carlo engine.
"""
import math

from . import geometry as G
from . import channel as CH
from . import phy as P
from . import interference as I
from . import presets as PR
from .engine import Case, run_case


def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


# ------------------------------------------------------------------ required C/N0
def required_cn0_dbhz(case):
    return case.required_cn0()


def phy_rate_bps(case, cn0=None):
    """Information rate on the air interface."""
    if case.tech == "LORA":
        return P.lora_rate_bps(case.st["sf"])
    if case.tech == "LRFHSS":
        return 488.28125 * (1 / 3 if P.LRFHSS_DR[case.st["dr"]]["cr"] == "1/3" else 2 / 3)
    if cn0 is None:
        return None
    if getattr(case, "front", None):
        from . import nbiot as NB
        cfg = NB.select(case.front, cn0 - case.g["la_margin_db"])
        return None if cfg is None else case.bits / cfg["airtime_s"]
    return P.cellular_rate_bps(case.tech, cn0)


def message_airtime_s(case, cn0=None):
    if case.tech in ("LORA", "LRFHSS"):
        return case.toa
    r = phy_rate_bps(case, cn0)
    return None if r is None else case.bits / r


# ------------------------------------------------------------------ link budget
def link_budget(stack, scen, el_deg=30.0, los=True, **kw):
    """Itemised uplink budget at one elevation (median shadowing, no fading)."""
    case = Case(stack, scen, **kw)
    st, sc, g = case.st, case.sc, case.g
    d = G.slant_range_km(case.h, el_deg)
    a = G.off_nadir_deg(case.h, el_deg)
    fspl = CH.fspl_db(d, case.f)
    cl = CH.median_loss_db(sc["env"], max(el_deg, 10.0), los, case.amode)
    gs = case.ant.gain_toward(a, 0.0)
    gt = case.ant.g_over_t(gs)
    n0 = case.n0
    i0 = case.i0(el_deg)
    n0e = I.effective_n0(n0, i0)
    eirp = case.eirp
    prx = eirp - fspl - cl + gs
    cn0 = prx - n0e
    req = required_cn0_dbhz(case)
    rows = [
        ("Device transmit power", st["ptx_dbm"], "dBm"),
        ("Device antenna gain", st["g_dev_dbi"], "dBi"),
        ("Device-side loss (body, vehicle, indoor)", -sc["device_loss_db"], "dB"),
        ("Device EIRP", case.eirp_dev, "dBm"),
        ("Slant range", d, "km"),
        ("Free-space path loss", -fspl, "dB"),
        ("Polarisation mismatch (propagation allowance)", -g["pol_loss_db"], "dB"),
        ("Scintillation allowance", -g["scint_margin_db"], "dB"),
        ("Atmospheric gas", -g["gas_loss_db"], "dB"),
        ("Clutter loss (median, %s, %s)" % (sc["env"], "LOS" if los else "NLOS"), -cl, "dB"),
        ("Satellite antenna gain toward device", gs, "dBi"),
        ("Satellite system noise temperature", case.ant.t_sys_k(), "K"),
        ("Satellite G/T toward device", gt, "dB/K"),
        ("Received power at antenna output", prx, "dBm"),
        ("Thermal noise density k*Tsys", n0, "dBm/Hz"),
        ("Interference density (ISM or co-channel TN)", i0 if i0 > -900 else None, "dBm/Hz"),
        ("Noise rise from interference", I.noise_rise_db(i0, n0), "dB"),
        ("C/(N0+I0) achieved", cn0, "dB-Hz"),
        ("C/N0 required", req, "dB-Hz"),
        ("Link margin", cn0 - req, "dB"),
    ]
    r = phy_rate_bps(case, cn0)
    rows.append(("Information rate", r, "bit/s"))
    rows.append(("Message airtime", message_airtime_s(case, cn0), "s"))
    # MAPL: device EIRP to satellite antenna output, path + clutter + allowances.
    # MCL: device antenna port to satellite antenna port (excludes both antenna gains).
    dl_rows, dl_margin = None, None
    if case.dl_on:
        from . import downlink as DLm
        from .antenna import airy_rel_db
        fspl_dl = CH.fspl_db(d, case.f_dl)
        snr = case.dl_snr_median(el_deg, los)
        ci = (DLm.c_over_i_db(0.0, 0.0, airy_rel_db, case.ant.bw, g["dl_reuse"])
              if case.ant.kind == "multibeam" else None)
        if case.tech in DLm.TECH:
            req_dl, req_lbl = case.dl_floor, "assumed acquisition threshold (NPDSCH reference point)"
        else:
            req_dl, req_lbl = P.LORA_SNR_DB[case.sf_dl], "LoRa SF%d acknowledgement" % case.sf_dl
        dl_margin = snr - req_dl
        dl_rows = [
            ("Downlink frequency", case.f_dl / 1e6, "MHz"),
            ("Satellite EIRP density at beam centre", case.dl_eirp_dbw_mhz, "dBW/MHz"),
            ("Satellite EIRP in the downlink bandwidth", case.dl_eirp_dbm, "dBm"),
            ("Downlink bandwidth", case.dl_bw / 1e3, "kHz"),
            ("Satellite pattern relative to beam centre", gs - case.ant.g0, "dB"),
            ("Free-space path loss", -fspl_dl, "dB"),
            ("Allowances (polarisation, scintillation, gas)", -case.allow, "dB"),
            ("Clutter loss (median)", -cl, "dB"),
            ("Device-side loss", -sc["device_loss_db"], "dB"),
            ("Device antenna gain", st["g_dev_dbi"], "dBi"),
            ("Device noise power in the bandwidth", case.dl_n_dbm, "dBm"),
            ("Carrier-to-interference, co-channel beams (beam centre)", ci, "dB"),
            ("Downlink SINR", snr, "dB"),
            ("Required: " + req_lbl, req_dl, "dB"),
            ("Downlink margin", dl_margin, "dB"),
        ]
    return dict(stack=stack, scenario=scen, elev_deg=el_deg, rows=rows, margin_db=cn0 - req,
                dl_rows=dl_rows, dl_margin_db=dl_margin,
                mapl_db=case.eirp_dev + gs - n0e - req,
                mcl_db=st["ptx_dbm"] - (n0e + req),
                mapl_definition="device EIRP + satellite gain - (N0+I0) - required C/N0",
                mcl_definition="device conducted power - (N0+I0) - required C/N0 (antenna gains excluded)")


# ------------------------------------------------------------------ path loss
def path_loss_curve(stack, scen, elevs=None, **kw):
    case = Case(stack, scen, **kw)
    elevs = elevs or list(range(10, 91, 5))
    out = []
    for e in elevs:
        d = G.slant_range_km(case.h, e)
        f = CH.fspl_db(d, case.f)
        out.append(dict(el=e, slant_km=d, fspl_db=f,
                        pl_los_db=f + CH.median_loss_db(case.sc["env"], max(e, 10), True, case.amode),
                        pl_nlos_db=f + CH.median_loss_db(case.sc["env"], max(e, 10), False, case.amode),
                        p_los=CH.los_probability(case.sc["env"], max(e, 10), case.amode)))
    return out


# ------------------------------------------------------------------ coverage
def coverage_probability(case, el):
    """P(margin >= 0) with TR 38.811 LOS/NLOS mixture and lognormal SF."""
    env = case.sc["env"]
    e = max(el, 10.0)
    d = G.slant_range_km(case.h, el)
    gs = case.ant.gain_toward(G.off_nadir_deg(case.h, el), 0.0)
    if case.ant.kind == "multibeam":
        gs -= 1.5                      # average over the beam spot
    base = case.eirp - CH.fspl_db(d, case.f) + gs - case.n0_eff(el) - required_cn0_dbhz(case)
    pl = CH.los_probability(env, e, case.amode)
    s_l, _ = CH.sf_cl(env, e, True, case.amode)
    s_n, cl = CH.sf_cl(env, e, False, case.amode)
    p_los = _phi(base / max(s_l, 1e-6))
    p_nlos = _phi((base - cl) / max(s_n, 1e-6))
    return pl * p_los + (1 - pl) * p_nlos


def coverage_curve(stack, scen, elevs=None, **kw):
    case = Case(stack, scen, **kw)
    elevs = elevs or list(range(10, 91, 5))
    return [dict(el=e, p_cov=coverage_probability(case, e),
                 margin_los_db=case.margin_at(e, True)["margin_db"]) for e in elevs]


def cell_radius(stack, scen, target=0.9, **kw):
    """Ground radius around the sub-satellite point inside which the link closes
    with probability >= target. For multibeam arrays the 'cell' is one beam spot;
    the service radius is the scan range over which beams still close."""
    case = Case(stack, scen, **kw)
    el_min = None
    for e10 in range(900, 49, -5):         # 90.0 .. 5.0 deg
        e = e10 / 10
        if e < case.mask:
            break
        if coverage_probability(case, e) >= target:
            el_min = e
        else:
            break
    service_r = None if el_min is None else G.RE_KM * G.central_angle_rad(case.h, el_min)
    out = dict(stack=stack, scenario=scen, target=target, served_mask_deg=case.mask,
               el_min_link_deg=el_min, service_radius_km=service_r,
               service_area_km2=None if el_min is None else G.footprint_area_km2(case.h, el_min))
    if case.ant.kind == "multibeam":
        d = G.slant_range_km(case.h, 90.0)
        out["beam_spot_radius_nadir_km"] = d * math.tan(math.radians(case.ant.bw / 2))
        out["beam_spot_area_nadir_km2"] = case.ant.beam_spot_area_km2(case.h, 90.0, d)
        out["cell_radius_km"] = out["beam_spot_radius_nadir_km"]
    else:
        # a broad-beam satellite has one cell: every device above the elevation mask contends for the same
        # receiver (the population used for contention), whether or not its own link closes
        out["cell_radius_km"] = G.RE_KM * G.central_angle_rad(case.h, case.mask)
    return out


def time_coverage(stack, scen, target=0.9, **kw):
    """Fraction of the arrival window a device at the site has a serving
    satellite whose link closes with probability >= target, with gap statistics
    over the same window as geometric coverage (F17): gaps touching the window
    edges are censored; no link at all reports the whole window."""
    case = Case(stack, scen, **kw)
    tl = case.tl
    i0, n = case.a0, case.n_arr
    ok = [bool(tl["vis"][i]) and coverage_probability(case, tl["el"][i]) >= target for i in range(i0, i0 + n)]
    gaps, run, start = [], 0, 0
    for i, v in enumerate(ok):
        if not v:
            if run == 0:
                start = i
            run += 1
        elif run:
            gaps.append((run * tl["dt"], start == 0)); run = 0
    if run:
        gaps.append((run * tl["dt"], True))
    allg = sorted(g for g, _ in gaps)
    return dict(stack=stack, scenario=scen, geometric_coverage=case.cov["coverage_fraction"],
                link_coverage=sum(ok) / n, mean_gap_s=(sum(allg) / len(allg)) if allg else 0.0,
                max_gap_s=allg[-1] if allg else 0.0, n_censored_gaps=sum(1 for _, c in gaps if c),
                window_s=n * tl["dt"])


# ------------------------------------------------------------------ interference
def noise_rise_vs_density(stack, scen, densities, source="ism", el=45.0, **kw):
    """Noise rise (dB) at the satellite versus emitter density (active per km^2)."""
    case = Case(stack, scen, **kw)
    out = []
    for dens in densities:
        if source == "ism":
            v = I.aggregate_i0_dbm_hz(case.ant, case.h, case.f, dens, case.g["ism_eirp_dbm"],
                                      case.g["ism_band_hz"], "suburban", extra_loss_db=case.g["pol_loss_db"],
                                      serving_el_deg=el)
        else:
            loss = I.indoor_mix_loss_db(case.g["tn_indoor_frac"], case.g["tn_bpl_db"]) + case.g["pol_loss_db"]
            v = I.aggregate_i0_dbm_hz(case.ant, case.h, case.f, dens, case.g["tn_ue_eirp_dbm"],
                                      case.g["tn_carrier_hz"], case.sc["env"], extra_loss_db=loss,
                                      serving_el_deg=el)
        out.append(dict(density_km2=dens, i0_dbm_hz=v, noise_rise_db=I.noise_rise_db(v, case.n0)))
    return out


# ------------------------------------------------------------------ throughput and capacity
def goodput_curve(stack, scen, scales, n_mc=1200, **kw):
    """Delivered messages/s and bits/s per cell versus offered load."""
    out = []
    for s in scales:
        so = dict(kw.get("scen_over") or {}, load_scale=s)
        go = dict(kw.get("g_over") or {}, n_mc=n_mc)
        r = run_case(stack, scen, stack_over=kw.get("stack_over"), scen_over=so, g_over=go,
                     cache_dir=kw.get("cache_dir"))
        sc = dict(PR.SCENARIOS[scen], **(kw.get("scen_over") or {}))
        lam = r["devices_in_cell_at_45"] / sc["interval_s"]
        out.append(dict(load_scale=s, devices_per_cell=r["devices_in_cell_at_45"],
                        offered_msgs_s=lam, pdr=r["pdr"],
                        goodput_msgs_s=lam * r["pdr"],
                        goodput_bps=lam * r["pdr"] * sc["payload_b"] * 8,
                        contention_loss=r["causes"]["collision"] + r["causes"]["blocked"]))
    return out


def _run_scaled(stack, scen, scale, n_mc, seed, kw):
    so = dict(kw.get("scen_over") or {}, load_scale=scale)
    go = dict(kw.get("g_over") or {}, n_mc=n_mc, seed=seed)
    return run_case(stack, scen, stack_over=kw.get("stack_over"), scen_over=so, g_over=go,
                    cache_dir=kw.get("cache_dir"))


def _bisect(stack, scen, ok_fn, n_mc, seed, dev_lo, dev_hi, iters, kw):
    base = Case(stack, scen, stack_over=kw.get("stack_over"), scen_over=kw.get("scen_over"),
                g_over=kw.get("g_over"), cache_dir=kw.get("cache_dir")).devices_in_cell(45.0)[0]
    lo, hi = math.log10(dev_lo / base), math.log10(dev_hi / base)
    r_lo = _run_scaled(stack, scen, 10 ** lo, n_mc, seed, kw)
    if not ok_fn(r_lo):
        return 0.0, r_lo, "infeasible: requirement not met even at %g device per cell" % dev_lo
    r_hi = _run_scaled(stack, scen, 10 ** hi, n_mc, seed, kw)
    if ok_fn(r_hi):
        return r_hi["devices_in_cell_at_45"], r_hi, "not reached: capacity >= this value"
    best = r_lo
    for _ in range(iters):
        m = (lo + hi) / 2
        r = _run_scaled(stack, scen, 10 ** m, n_mc, seed, kw)
        if ok_fn(r):
            lo, best = m, r
        else:
            hi = m
    return best["devices_in_cell_at_45"], best, ""


T975 = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262,
        11: 2.228, 12: 2.201, 13: 2.179, 14: 2.160, 15: 2.145, 16: 2.131, 20: 2.093, 30: 2.045}


def t_interval(vals):
    """Mean and 95 % Student-t interval over independent replications."""
    n = len(vals)
    m = sum(vals) / n
    if n < 2:
        return m, (None, None), 0.0
    sd = math.sqrt(sum((v - m) ** 2 for v in vals) / (n - 1))
    t = T975.get(n, T975[max(k for k in T975 if k <= n)])
    return m, (m - t * sd / math.sqrt(n), m + t * sd / math.sqrt(n)), sd


def capacity(stack, scen, target=0.9, max_contention_loss=0.1, n_mc=3000, seeds=None,
             dev_lo=1.0, dev_hi=1e7, iters=12, metrics=("service", "contention"), ci=True,
             check_load=True, key="pdr_deadline", **kw):
    """Two capacity metrics, each bisected on log(devices per cell):

    service capacity    - largest devices per cell with delivery within deadline
                          >= target, counting EVERY failure (link, Doppler,
                          collision, blocking, coverage, lateness); 0 when the
                          unloaded link already misses the target (F01).
    contention capacity - largest devices per cell with collision + blocking
                          <= max_contention_loss among link-feasible messages
                          (conditional metric, named as such).

    Estimand (P07): the EXPECTED FINITE-SAMPLE CROSSING, i.e. the mean over
    replications of the load at which one replication's on-time fraction
    (n_mc samples, common random numbers along its bisection) falls to the
    target. This is not the crossing of the mean delivery curve; the fresh
    on-time fraction at the reported capacity is given beside it so the
    difference is visible (e.g. 0.914 for LTE-M).

    Uncertainty (M02): every seed is an INDEPENDENT REPLICATION of the complete
    procedure (new random streams for geometry, links, access, group fitting,
    interference pools and the bisection itself). The point estimate is the
    MEAN over replications and, with >= 5 replications, the 95 % interval is
    the Student-t interval of that mean (Monte Carlo uncertainty only; orbital
    phase and model uncertainty are reported separately). The interval
    procedure is checked for coverage on a problem with a known crossing
    (validate.py). With fewer replications only the min-max range is given.
    on_time_at_capacity is re-estimated AT the reported capacity with fresh
    seeds (same estimand and load); a monotonicity check evaluates the
    on-time fraction at 0.5x, 1x and 2x the capacity."""
    seeds = seeds or [20261122, 20261123, 20261124]
    svc_ok = lambda r: r[key] >= target

    def cont_ok(r):
        c = r["causes"]
        den = r["pdr"] + c["collision"] + c["blocked"]
        return den > 0 and (c["collision"] + c["blocked"]) / den <= max_contention_loss
    out = dict(stack=stack, scenario=scen, target=target, seeds=seeds, n_mc=n_mc, replications=len(seeds), metric=key)
    base = Case(stack, scen, stack_over=kw.get("stack_over"), scen_over=kw.get("scen_over"),
                g_over=kw.get("g_over"), cache_dir=kw.get("cache_dir")).devices_in_cell(45.0)[0]
    for name, fn in (("service", svc_ok), ("contention", cont_ok)):
        if name not in metrics:
            continue
        vals, notes, area = [], [], None
        for sd in seeds:
            n, r, note = _bisect(stack, scen, fn, n_mc, sd, dev_lo, dev_hi, iters, kw)
            vals.append(n); notes.append(note); area = r["cell_area_km2_at_45"]
        vs = sorted(vals)
        mean, ci95, sdv = t_interval(vals)
        boundary = any(x for x in notes)
        res = dict(devices_per_cell=mean, devices_per_cell_median=vs[len(vs) // 2],
                   devices_per_cell_min=vs[0], devices_per_cell_max=vs[-1], devices_per_cell_sd=sdv,
                   cell_area_km2=area, devices_per_km2=(mean / area) if area else None,
                   devices_per_km2_min=(vs[0] / area) if area else None,
                   devices_per_km2_max=(vs[-1] / area) if area else None,
                   estimator="mean over %d independent replications" % len(seeds),
                   estimand="expected finite-sample crossing (n_mc %d per evaluation)" % n_mc,
                   per_seed_devices_per_km2=[(v / area) if area else None for v in vals],
                   note="; ".join(sorted(set(x for x in notes if x))))
        if ci and len(seeds) >= 5 and not boundary and mean > 0 and area:
            res["devices_per_km2_ci95"] = (ci95[0] / area, ci95[1] / area)
            res["ci_method"] = "Student-t over replications of the whole procedure (Monte Carlo uncertainty)"
        else:
            res["devices_per_km2_ci95"] = None
            res["ci_method"] = ("none: fewer than 5 replications, min-max range only" if len(seeds) < 5
                                else "none: capacity at a search boundary or zero")
        if name == "service" and mean > 0 and check_load and not boundary:
            sc_load = mean / base
            ot = [_run_scaled(stack, scen, sc_load, n_mc, sd + 1000, kw)[key] for sd in seeds]
            m_ot, ci_ot, _ = t_interval(ot)
            res["on_time_at_capacity"] = m_ot
            res["on_time_at_capacity_ci95"] = ci_ot if len(seeds) >= 5 else None
            mono = [_run_scaled(stack, scen, sc_load * f, n_mc, seeds[0] + 2000, kw)[key]
                    for f in (0.5, 1.0, 2.0)]
            res["monotonicity_check"] = dict(load_factors=[0.5, 1.0, 2.0], on_time=mono,
                                             monotone=bool(mono[0] >= mono[1] - 0.01 and mono[1] >= mono[2] - 0.01))
        out[name] = res
    return out


def capacity_ratio(stack_a, stack_b, scen, seeds, n_mc=3000, target=0.9, **kw):
    """Paired service-capacity ratio a/b over the same replications (seed-paired);
    95 % t-interval on the log ratio, reported back on the linear scale."""
    ra, rb = [], []
    for sd in seeds:
        na = capacity(stack_a, scen, target=target, n_mc=n_mc, seeds=[sd], metrics=("service",), ci=False,
                      check_load=False, **kw)["service"]["devices_per_km2"]
        nb = capacity(stack_b, scen, target=target, n_mc=n_mc, seeds=[sd], metrics=("service",), ci=False,
                      check_load=False, **kw)["service"]["devices_per_km2"]
        ra.append(na); rb.append(nb)
    pairs = [(a, b) for a, b in zip(ra, rb) if a and b and a > 0 and b > 0]
    if len(pairs) < 2:
        return dict(a=stack_a, b=stack_b, scenario=scen, cap_a=ra, cap_b=rb, ratio=None, ratio_ci95=None,
                    note="ratio undefined: zero capacity in some replication")
    lr = [math.log(a / b) for a, b in pairs]
    m, ci, _ = t_interval(lr)
    return dict(a=stack_a, b=stack_b, scenario=scen, cap_a=ra, cap_b=rb, ratio=math.exp(m),
                ratio_ci95=(math.exp(ci[0]), math.exp(ci[1])) if ci[0] is not None else None,
                replications=len(pairs), method="seed-paired, t-interval on log ratio")


def paired_ratio(a_vals, b_vals):
    """Seed-paired ratio of two per-replication capacity lists; t-interval on log ratio."""
    pairs = [(a, b) for a, b in zip(a_vals, b_vals) if a and b and a > 0 and b > 0]
    if len(pairs) < 2 or len(pairs) < len(a_vals):
        return dict(ratio=None, ratio_ci95=None, replications=len(pairs),
                    note="undefined: zero capacity in at least one replication")
    lr = [math.log(a / b) for a, b in pairs]
    m, ci, _ = t_interval(lr)
    return dict(ratio=math.exp(m), ratio_ci95=(math.exp(ci[0]), math.exp(ci[1])), replications=len(pairs),
                method="seed-paired, Student-t interval on log ratio")
