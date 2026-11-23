"""Batch runner: every comparison dimension for every stack, written to
results.json (+ CSV tables). Figures are produced separately by figures.py so
this module stays dependency-free (portable to the HTML version)."""
import csv
import json
import os

from . import analysis as AN
from . import presets as PR
from .engine import run_case, Case
from . import phy as P
from . import access as A
from . import refsched as RS

MAIN = ["OP-LB-NBIOT", "OP-LB-LTEM", "OP-MSS-NBIOT", "IO-ISM-LRFHSS", "IO-ISM-LORA-SF10",
        "IO-ISM-LORA-SF12", "IO-SBAND-LRFHSS", "IO-SBAND-LRFHSS-HP"]
CONTROL = ["CTRL-NBIOT", "CTRL-LRFHSS", "CTRL-LORA-SF12", "CTRL-SS-NBIOT", "CTRL-SS-LRFHSS", "CTRL-SS-LORA-SF12"]
ALL = MAIN + CONTROL
REF_SCEN = "utility_wells"


CKPT_DIR = None     # set to a folder to checkpoint the expensive stages (resume after a crash)


def _ck(name, fn):
    """Run fn() once and store its JSON result under CKPT_DIR; reuse it on a rerun.
    Clears in-memory caches after each computed stage to bound memory."""
    if not CKPT_DIR:
        return fn()
    path = os.path.join(CKPT_DIR, name.replace("/", "_") + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    val = fn()
    os.makedirs(CKPT_DIR, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        json.dump(val, f, default=lambda o: None)
    os.replace(path + ".tmp", path)
    from . import engine as _E, interference as _I
    _E._PROF_CACHE.clear(); _I._CACHE.clear()
    with open(path) as f:                      # identical object whether computed or resumed
        return json.load(f)


def run_all(out_dir="out", cache_dir="out/cache", n_mc=3000, quick=False, log=print):
    os.makedirs(out_dir, exist_ok=True)
    g_over = dict(n_mc=n_mc)
    kw = dict(cache_dir=cache_dir)
    R = dict(meta=dict(site=PR.GLOBAL["site"], n_mc=n_mc, param_sources=P.PARAM_SOURCES,
                       presets=dict(stacks=PR.STACKS, scenarios=PR.SCENARIOS,
                                    satellites=PR.SATELLITES, constellations=PR.CONSTELLATIONS,
                                    global_=PR.GLOBAL)))
    log("1/9 link budgets")
    R["link_budget"] = {s: {e: AN.link_budget(s, REF_SCEN, e, **kw) for e in (10, 30, 60, 90)} for s in ALL}
    log("2/9 path loss")
    R["path_loss"] = {s: AN.path_loss_curve(s, REF_SCEN, **kw) for s in ALL}
    log("3/9 margin and coverage probability")
    R["coverage_curve"] = {sc: {s: AN.coverage_curve(s, sc, **kw) for s in ALL} for sc in PR.SCENARIOS}
    log("4/9 cell radius and time coverage")
    R["cell_radius"] = {sc: {s: AN.cell_radius(s, sc, **kw) for s in ALL} for sc in PR.SCENARIOS}
    R["time_coverage"] = {sc: {s: AN.time_coverage(s, sc, **kw) for s in ALL} for sc in PR.SCENARIOS}
    log("5/9 throughput vs elevation")
    thr = {}
    for s in ALL:
        c = Case(s, REF_SCEN, **kw)
        rows = []
        for e in range(10, 91, 5):
            m = c.margin_at(e)
            cn0 = m["cn0_dbhz"]
            ok = m["margin_db"] >= 0
            rows.append(dict(el=e, rate_bps=AN.phy_rate_bps(c, cn0) if ok else 0.0, cn0_dbhz=cn0))
        thr[s] = rows
    R["throughput_vs_elevation"] = thr
    log("6/9 interference")
    dens = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1]
    R["interference"] = dict(
        ism={s: AN.noise_rise_vs_density(s, REF_SCEN, dens, "ism", **kw)
             for s in ["IO-ISM-LRFHSS", "IO-ISM-LORA-SF12", "CTRL-LRFHSS"]},
        tn_cochannel={s: AN.noise_rise_vs_density(s, REF_SCEN, [d * 10 for d in dens], "tn", **kw)
                      for s in ["OP-LB-NBIOT", "OP-MSS-NBIOT"]})
    ism_sweep = {}
    for lvl in ["off", "low", "medium", "high"]:
        ism_sweep[lvl] = {s: run_case(s, REF_SCEN, stack_over=dict(ism=lvl), g_over=g_over, **kw)["pdr"]
                          for s in ["IO-ISM-LRFHSS", "IO-ISM-LORA-SF12"]}
    R["interference"]["ism_pdr"] = ism_sweep
    coex = {}
    for mode in ["dedicated", "cochannel"]:
        coex[mode] = {sc: run_case("OP-LB-NBIOT", sc, stack_over=dict(coexistence=mode),
                                   g_over=g_over, **kw)["pdr"] for sc in PR.SCENARIOS}
    R["interference"]["tn_coexistence_pdr"] = coex
    log("7/9 goodput vs load")
    scales = [10 ** (x / 2) for x in range(-6, 9)] if not quick else [0.01, 1, 100]
    R["goodput"] = {s: AN.goodput_curve(s, REF_SCEN, scales, n_mc=max(600, n_mc // 3), **kw) for s in ALL}
    log("8/9 capacity: service (10 replications + CI in the reference scenario, 3 elsewhere) and contention")
    seeds = PR.GLOBAL["seeds"] if not quick else PR.GLOBAL["seeds"][:1]
    seeds_ref = PR.GLOBAL["seeds_ref"] if not quick else PR.GLOBAL["seeds"][:1]
    R["capacity"] = {}
    for sc in (PR.SCENARIOS if not quick else [REF_SCEN]):
        ref = sc == REF_SCEN
        R["capacity"][sc] = {}
        for s in ALL:
            def _cap(s=s, sc=sc, ref=ref):
                if ref:
                    c = AN.capacity(s, sc, n_mc=n_mc, seeds=seeds_ref, iters=12, metrics=("service",), **kw)
                    c["contention"] = AN.capacity(s, sc, n_mc=n_mc, seeds=seeds, iters=12, metrics=("contention",),
                                                  ci=False, **kw)["contention"]
                    return c
                return AN.capacity(s, sc, n_mc=max(1000, n_mc // 2), seeds=seeds, iters=10, ci=False,
                                   check_load=False, metrics=("service",), **kw)
            R["capacity"][sc][s] = _ck("cap_%s_%s" % (sc, s), _cap)
    log("9/9 scenario matrix (PDR, latency, energy, battery)")
    R["scenario_matrix"] = {sc: _ck("matrix_%s" % sc, lambda sc=sc: {s: run_case(s, sc, g_over=g_over,
                                                                             keep_samples=True, **kw)
                                                                    for s in ALL})
                            for sc in PR.SCENARIOS}
    R.update(run_extras(n_mc=n_mc, cache_dir=cache_dir, log=log))
    with open(os.path.join(out_dir, "results.json"), "w") as f:
        json.dump(R, f, indent=1, default=lambda o: None)
    _csv(R, out_dir)
    return R


def run_extras(n_mc=3000, cache_dir="out/cache", log=print):
    """ISM noise rise by satellite class, and one-at-a-time sensitivity of the
    delivery ratio to the assumptions that drive the comparison."""
    kw = dict(cache_dir=cache_dir)
    g_over = dict(n_mc=n_mc)
    log("extra 1/2 ISM noise rise by satellite class")
    dens = [1e-5, 3e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1e-1]
    ism_sat = {}
    for sat in ["smallsat_patch", "smallsat_deployable", "d2d_array_64m2"]:
        ism_sat[sat] = AN.noise_rise_vs_density("IO-ISM-LRFHSS", REF_SCEN, dens, "ism",
                                                stack_over=dict(sat=sat), **kw)
    log("extra 2/2 sensitivity")
    cases = {
        "IO-ISM-LRFHSS": [
            ("baseline", {}, {}, {}),
            ("ISM interference off", dict(ism="off"), {}, {}),
            ("ISM interference medium", dict(ism="medium"), {}, {}),
            ("dense constellation (64 sats)", dict(const="iot_dense"), {}, {}),
            ("no polarisation loss", {}, {}, dict(pol_loss_db=0.0)),
            ("device antenna 0 dBi", dict(g_dev_dbi=0.0), {}, {}),
            ("transmit at pass maximum", {}, {}, dict(tx_policy="best_in_pass")),
            ("3 blind copies", dict(copies=3), {}, {}),
            ("LR-FHSS DR10 (336 kHz, 688 ch)", dict(dr="DR10"), {}, {}),
            ("no other networks in band", dict(other_networks_load=0.0), {}, {}),
        ],
        "OP-MSS-NBIOT": [
            ("baseline", {}, {}, {}),
            ("dense constellation (64 sats)", dict(const="iot_dense"), {}, {}),
            ("no polarisation loss", {}, {}, dict(pol_loss_db=0.0)),
            ("transmit at pass maximum", dict(tx_policy="best_in_pass"), {}, {}),
            ("pass-aware policy (wait for 30 deg)", dict(tx_policy="elev_threshold"), {}, {}),
            ("deployable 12 dBi antenna", dict(sat="smallsat_deployable"), {}, {}),
            ("3x NPRACH preambles at CE1/CE2", dict(rach=dict(PR.RACH["NBIOT"], ce=[
                dict(reps=2, period_s=0.16, preambles=24), dict(reps=16, period_s=0.32, preambles=36),
                dict(reps=128, period_s=1.28, preambles=36)])), {}, {}),
            ("4 NB-IoT carriers per beam", dict(carriers_per_beam=4, rach=dict(PR.RACH["NBIOT"], ce=[
                dict(reps=2, period_s=0.16, preambles=96), dict(reps=16, period_s=0.32, preambles=48),
                dict(reps=128, period_s=1.28, preambles=48)])), {}, {}),
        ],
        "OP-LB-NBIOT": [
            ("baseline", {}, {}, {}),
            ("co-channel with terrestrial network", dict(coexistence="cochannel"), {}, {}),
            ("64 m2 array instead of 223 m2", dict(sat="d2d_array_64m2"), {}, {}),
            ("60-satellite constellation", dict(const="d2d_60"), {}, {}),
            ("transmit at first visibility", {}, {}, dict(tx_policy="first_visible")),
            ("co-channel TN, realised pattern", dict(coexistence="cochannel"), {}, {}),
            ("co-channel TN, S.1528 envelope (bound)", dict(coexistence="cochannel"), {}, dict(sidelobe_model="s1528")),
            ("pass-aware policy (wait for 30 deg)", dict(tx_policy="elev_threshold"), {}, {}),
            ("256 active beams per satellite", dict(beams_per_sat=256), {}, {}),
        ],
        "CTRL-NBIOT": [
            ("baseline (hardware-inspired repetition efficiency, beta 0.5)", {}, dict(), {}),
            ("link-level repetition efficiency (optimistic)", {}, {}, dict(nbiot_calibration="link_level")),
            ("legacy continuous rate model", {}, {}, dict(nbiot_model="continuous")),
            ("link adaptation minimises airtime", {}, {}, dict(nbiot_objective="airtime")),
            ("fluid traffic (lambda / f_cov)", {}, {}, dict(traffic_model="fluid")),
            ("TR 38.811 nearest reference angle", {}, {}, dict(angle_mode="nearest")),
            ("coherence time 1 ms (independent HARQ fading)", {}, {}, dict(coh_s=0.001)),
            ("coherence time 10 s", {}, {}, dict(coh_s=10.0)),
        ],
        "CTRL-LRFHSS": [
            ("baseline (packet-level hopping grids)", {}, {}, {}),
            ("marginal model (Ullah et al.)", {}, {}, dict(lrfhss_model="marginal")),
            ("fluid traffic (lambda / f_cov)", {}, {}, dict(traffic_model="fluid")),
            ("TR 38.811 nearest reference angle", {}, {}, dict(angle_mode="nearest")),
        ],
    }
    sens = {}
    for stack, lst in cases.items():
        sens[stack] = []
        for name, so, sco, go in lst:
            r = run_case(stack, REF_SCEN, stack_over=so, scen_over=sco or None, g_over=dict(g_over, **go), **kw)
            sens[stack].append(dict(case=name, pdr=r["pdr"], pdr_deadline=r["pdr_deadline"],
                                    pdr_deadline_ci95=r["pdr_deadline_ci95"],
                                    latency_p95_s=r["latency_p95_s"], energy_per_msg_j=r["energy_per_msg_j"],
                                    noise_rise_db=r["noise_rise_db_at_45"]))
    # urban disaster sensitivity for the operator stack (coverage-capacity trade-off)
    for name, so, go in (("baseline", {}, {}), ("link-level repetition efficiency", {}, dict(nbiot_calibration="link_level")),
                         ("4 NB-IoT carriers per beam", dict(carriers_per_beam=4), {}),
                         ("cheapest-first admission", {}, dict(admission="cheapest_first")),
                         ("cheapest-first admission + link-level", {}, dict(admission="cheapest_first",
                                                                             nbiot_calibration="link_level"))):
        r = run_case("OP-LB-NBIOT", "disaster_urban", stack_over=so, g_over=dict(g_over, **go), **kw)
        sens.setdefault("OP-LB-NBIOT@disaster_urban", []).append(
            dict(case=name, pdr=r["pdr"], pdr_deadline=r["pdr_deadline"], pdr_deadline_ci95=r["pdr_deadline_ci95"],
                 latency_p95_s=r["latency_p95_s"], energy_per_msg_j=r["energy_per_msg_j"],
                 noise_rise_db=r["noise_rise_db_at_45"], causes=r["causes"], rho_max=r.get("rho_max"),
                 admitted_fraction_min=r.get("admitted_fraction_min"), on_time_by_ce=r.get("on_time_by_ce")))
    log("extra: LR-FHSS element-level approximation vs enumeration near the 200-packet switch (P06)")
    from .rng import Rng as _R
    fr8 = P.lrfhss_frame("DR8", 33)
    r0 = _R(3)
    pool_u = A.Pool([10 ** ((-125 + 6 * r0.normal()) / 10) for _ in range(500)])
    lrb = []
    for p_off in (10.0, 15.0):             # target power above the interferer-pool median (capture regime)
        for k_target in (150, 200, 250):
            lam_t = k_target * fr8["C"] // fr8["grid"] / (2 * fr8["toa_s"])
            res = []
            for mp in (10 ** 9, -1):
                rr = _R(int(k_target + 1000 * p_off)); ok_n = 0
                for _ in range(600):
                    ok_n += A.lrfhss_attempt_packet(rr, 20.0, fr8, 10 ** ((-125 + p_off) / 10), lam_t, pool_u, 6.0,
                                                    10.0, max_packets=mp)[0]
                res.append(ok_n / 600)
            lrb.append(dict(target_above_pool_db=p_off, same_grid_packets=k_target, enumeration=res[0],
                            element_branch=res[1], difference=res[1] - res[0],
                            se=((res[0] * (1 - res[0]) + res[1] * (1 - res[1])) / 600) ** 0.5))
    log("extra: technology x transmit-policy matrix, 10 replications, paired ratios (N05, M02)")
    pmat, per = [], {}
    sref = PR.GLOBAL["seeds_ref"]
    for stck in ("CTRL-NBIOT", "CTRL-LRFHSS", "CTRL-LORA-SF12", "CTRL-SS-NBIOT", "CTRL-SS-LRFHSS", "CTRL-SS-LORA-SF12"):
        for pol in ("first_visible", "elev_threshold"):
            so = dict(tx_policy=pol)
            chk = Case(stck, REF_SCEN, stack_over=so, cache_dir=cache_dir)
            assert chk.st["tx_policy"] == pol
            def _pm(stck=stck, so=so):
                r = run_case(stck, REF_SCEN, stack_over=so, g_over=g_over, **kw)
                sv = AN.capacity(stck, REF_SCEN, n_mc=n_mc, seeds=sref, iters=12, metrics=("service",),
                                 check_load=False, stack_over=so, **kw)["service"]
                ct = AN.capacity(stck, REF_SCEN, n_mc=n_mc, seeds=PR.GLOBAL["seeds"], iters=12,
                                 metrics=("contention",), ci=False, stack_over=so, **kw)["contention"]
                return dict(r=dict(pdr_deadline=r["pdr_deadline"], pdr_deadline_ci95=r["pdr_deadline_ci95"]),
                            sv=sv, ct=ct)
            pm = _ck("pmat_%s_%s" % (stck, pol), _pm)
            r, sv, ct = pm["r"], pm["sv"], pm["ct"]
            per[(stck, pol)] = sv["per_seed_devices_per_km2"]
            pmat.append(dict(stack=stck, policy=pol, on_time=r["pdr_deadline"], on_time_ci95=r["pdr_deadline_ci95"],
                             service_per_km2=sv["devices_per_km2"], service_ci95=sv["devices_per_km2_ci95"],
                             service_note=sv["note"], contention_per_km2=ct["devices_per_km2"],
                             contention_min=ct["devices_per_km2_min"], contention_max=ct["devices_per_km2_max"]))
    ratios = []
    for a, b in (("CTRL-NBIOT", "CTRL-LRFHSS"), ("CTRL-SS-NBIOT", "CTRL-SS-LRFHSS")):
        for pol in ("first_visible", "elev_threshold"):
            ratios.append(dict(a=a, b=b, policy=pol, **AN.paired_ratio(per[(a, pol)], per[(b, pol)])))
    log("extra: chronological reference scheduler vs engine queue (rank-1 item)")
    cap_cell = None
    refs = []
    try:
        base = Case("OP-LB-NBIOT", REF_SCEN, cache_dir=cache_dir).devices_in_cell(45.0)[0]
        cap_cell = AN.capacity("OP-LB-NBIOT", REF_SCEN, n_mc=n_mc, seeds=PR.GLOBAL["seeds"][:1], iters=12,
                               metrics=("service",), ci=False, check_load=False, **kw)["service"]["devices_per_cell"]
        ls = cap_cell / base
    except Exception:
        ls = 250.0
    for sc, scale, go in ((REF_SCEN, ls, {}), (REF_SCEN, 3 * ls, {}), ("disaster_urban", 1.0, {}),
                          ("disaster_urban", 1.0, dict(nbiot_calibration="link_level")),
                          ("disaster_urban", 1.0, dict(admission="cheapest_first")),
                          ("disaster_urban", 1.0, dict(admission="cheapest_first", nbiot_calibration="link_level"))):
        refs.append(RS.reference_scheduler("OP-LB-NBIOT", sc, scale, dict(g_over, **go), cache_dir=cache_dir, hours=6))
    log("extra: orbital phase (three overlapping arrival windows; a sensitivity, not an independent ensemble)")
    phases = {}
    for start in (21600.0, 43200.0, 64800.0):
        phases[str(int(start / 3600)) + "h"] = {s: run_case(s, REF_SCEN, g_over=dict(g_over, arrival_start_s=start),
                                                            **kw)["pdr_deadline"] for s in ALL}
    log("extra 3/3 Monte Carlo convergence of service capacity")
    conv = {}
    for stck in ("CTRL-NBIOT", "CTRL-LRFHSS"):
        conv[stck] = []
        for nmc in (1000, 3000, 6000):
            c = AN.capacity(stck, REF_SCEN, n_mc=nmc, seeds=PR.GLOBAL["seeds"][:1], iters=12,
                            metrics=("service",), **kw)["service"]
            conv[stck].append(dict(n_mc=nmc, devices_per_km2=c["devices_per_km2"]))
    return dict(ism_by_satellite=ism_sat, sensitivity=sens, convergence=conv, policy_matrix=pmat,
                policy_ratios=ratios, reference_scheduler=refs, orbital_phase=phases, lrfhss_branch_boundary=lrb,
                orbital_phase_note="windows start at 6, 12 and 18 h and each spans 24 h, so they overlap")


def _csv(R, out_dir):
    with open(os.path.join(out_dir, "summary_by_scenario.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "stack", "model", "tech", "f_MHz", "payload", "coverage_fraction", "link_coverage",
                    "contacts_per_day", "cell_radius_km", "service_radius_km", "devices_in_cell",
                    "service_capacity_devices_per_km2", "service_capacity_min", "service_capacity_max",
                    "service_capacity_ci95_low", "service_capacity_ci95_high", "replications", "on_time_at_capacity",
                    "contention_capacity_devices_per_km2", "uplink_reception", "on_time", "on_time_ci_low",
                    "on_time_ci_high", "latency_p50_s", "latency_p95_s", "energy_per_msg_J",
                    "energy_per_on_time_msg_J", "battery_years", "battery_limited_by", "noise_rise_dB",
                    "alloc_kHz", "on_time_msgs_per_s_per_MHz", "on_time_msgs_per_s_per_MHz_at_service_capacity"])
        for sc, rows in R["scenario_matrix"].items():
            for s, r in rows.items():
                cr = R["cell_radius"][sc][s]
                tc = R["time_coverage"][sc][s]
                cap = R["capacity"].get(sc, {}).get(s, {})
                sv, ct = cap.get("service", {}), cap.get("contention", {})
                ci = r["pdr_deadline_ci95"]
                w.writerow([sc, s, r["model"], r["tech"], r["f_mhz"], r.get("payload"),
                            round(r["coverage"]["coverage_fraction"], 3), round(tc["link_coverage"], 3),
                            _r(r["coverage"].get("contacts_per_day")), _r(cr.get("cell_radius_km")),
                            _r(cr.get("service_radius_km")), _r(r["devices_in_cell_at_45"]),
                            _r(sv.get("devices_per_km2"), 5), _r(sv.get("devices_per_km2_min"), 5),
                            _r(sv.get("devices_per_km2_max"), 5),
                            _r((sv.get("devices_per_km2_ci95") or (None, None))[0], 5),
                            _r((sv.get("devices_per_km2_ci95") or (None, None))[1], 5),
                            len(cap.get("seeds") or []) or None, _r(sv.get("on_time_at_capacity"), 4),
                            _r(ct.get("devices_per_km2"), 5),
                            round(r["pdr"], 4), round(r["pdr_deadline"], 4), _r(ci[0], 4), _r(ci[1], 4),
                            _r(r["latency_p50_s"]), _r(r["latency_p95_s"]), round(r["energy_per_msg_j"], 4),
                            _r(r.get("energy_per_on_time_j"), 4), round(r["battery_years"], 2),
                            r.get("battery_limited_by"), round(r["noise_rise_db_at_45"], 2),
                            _r((r.get("alloc_hz") or 0) / 1e3), _r(r.get("on_time_msgs_per_s_per_mhz"), 4),
                            _r((sv.get("devices_per_cell") or 0) * sv["on_time_at_capacity"]
                               / PR.SCENARIOS[sc]["interval_s"] / (r["alloc_hz"] / 1e6), 4)
                            if r.get("alloc_hz") and sv.get("on_time_at_capacity") is not None
                            else (0.0 if r.get("alloc_hz") and not sv.get("devices_per_cell") else None)])
    with open(os.path.join(out_dir, "link_budgets.csv"), "w", newline="") as f:
        w = csv.writer(f)
        stacks = list(R["link_budget"].keys())
        LB = {st: {int(k): v for k, v in d.items()} for st, d in R["link_budget"].items()}
        for el in (10, 30, 60, 90):
            w.writerow([f"Elevation {el} deg"] + stacks)
            rows0 = LB[stacks[0]][el]["rows"]
            for i, (name, _, unit) in enumerate(rows0):
                w.writerow([f"{name} [{unit}]"] + [_r(LB[s][el]["rows"][i][1], 2) for s in stacks])
            w.writerow([])


def _r(x, n=1):
    return None if x is None else round(x, n)


def compare_with_v1(R, v1_path, out_dir, name="change_vs_v1.csv"):
    """Headline deltas against the v1 results file."""
    if not os.path.exists(v1_path):
        return None
    V = json.load(open(v1_path))
    rows = []
    for sc, d in R["scenario_matrix"].items():
        for s, r in d.items():
            v = V.get("scenario_matrix", {}).get(sc, {}).get(s)
            c2 = R["capacity"].get(sc, {}).get(s, {}).get("service", {}).get("devices_per_km2")
            cv = V.get("capacity", {}).get(sc, {}).get(s, {})
            c1 = cv.get("service", {}).get("devices_per_km2") if "service" in cv else cv.get("devices_per_km2")
            rows.append(dict(scenario=sc, stack=s,
                             on_time_prev=None if v is None else round(v["pdr_deadline"], 4),
                             on_time_now=round(r["pdr_deadline"], 4),
                             capacity_prev=None if c1 is None else round(c1, 5),
                             capacity_now_service=None if c2 is None else round(c2, 5),
                             battery_prev=None if v is None else round(v["battery_years"], 2),
                             battery_now=round(r["battery_years"], 2),
                             noise_rise_prev=None if v is None else round(v["noise_rise_db_at_45"], 2),
                             noise_rise_now=round(r["noise_rise_db_at_45"], 2)))
    with open(os.path.join(out_dir, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    return rows
