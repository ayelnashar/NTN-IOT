"""Validation suite. Each check compares the simulator against an independent
reference: a published value, a closed-form result, or a second implementation
inside the simulator. Returns rows of (check, simulated, reference, tolerance,
pass, source)."""
import math

from . import geometry as G
from . import antenna as AN
from . import phy as P
from . import access as A
from . import channel as CH
from .rng import Rng


def _row(name, sim, ref, tol, src, rel=False):
    err = abs(sim - ref) / abs(ref) if rel else abs(sim - ref)
    return dict(check=name, simulated=round(sim, 4), reference=round(ref, 4),
                tolerance=("%g%%" % (tol * 100)) if rel else tol, passed=err <= tol, source=src)


def run(log=print):
    rows = []
    # 1 orbital period
    rows.append(_row("Orbital period at 550 km [min]", G.orbital_period_s(550) / 60, 95.6, 0.1,
                     "Kepler's third law, standard value for 550 km"))
    # 2 geometry module vs closed-form slant range (propagated look angles)
    sats = G.walker(8, 2, 97.5, 550)
    worst = 0.0
    for t in range(0, 86400, 60):
        for s in sats:
            el, d, _, _ = G.look(s, 24.45, 54.38, t)
            if el > 5:
                worst = max(worst, abs(d - G.slant_range_km(550, el)) / d)
    rows.append(_row("Propagated range vs TR 38.811 slant-range formula, worst rel. error", worst, 0.0, 1e-3,
                     "internal consistency (two independent geometry paths)"))
    # 3 Doppler bound
    fmax = 0.0
    for t in range(0, 86400, 10):
        for s in sats:
            el, d, rr, _ = G.look(s, 24.45, 54.38, t)
            if el > 0:
                fmax = max(fmax, abs(868.1e6 * rr / G.C_KMS))
    bound = G.max_doppler_hz(868.1e6, 550)
    rows.append(_row("Max |Doppler| at 868 MHz, 550 km [kHz] (<= analytic bound + Earth rotation)",
                     fmax / 1e3, bound / 1e3, 0.05, "analytic overhead-pass bound", rel=True))
    # 4 array gain
    rows.append(_row("64 m2 array gain at 850 MHz, eff=1 [dBi]", AN.gain_from_aperture_dbi(64, 850e6, 1.0),
                     38.0, 0.5, "keeptrack.space AST deep dive: 'roughly 38 dBi'"))
    rows.append(_row("223 m2 array gain at 850 MHz, eff=1 [dBi]", AN.gain_from_aperture_dbi(223, 850e6, 1.0),
                     43.0, 0.6, "keeptrack.space AST deep dive: 'roughly 43 dBi'"))
    # 5 LoRa time on air vs The Things Network airtime calculator (10 B app payload + 13 B MAC)
    ttn = {7: 61.7, 8: 113.2, 9: 205.8, 10: 370.7, 11: 823.3, 12: 1482.8}
    for sf, ref in ttn.items():
        rows.append(_row(f"LoRa SF{sf} time on air, 23 B PHY payload [ms]", P.lora_toa_s(sf, 23) * 1e3, ref, 0.2,
                         "TTN LoRaWAN airtime calculator (Semtech AN1200.13)"))
    # 6 LoRa sensitivity
    rows.append(_row("LoRa SF12/125 kHz sensitivity, NF 6 dB [dBm]", P.lora_sensitivity_dbm(12, 6.0), -137.0, 0.5,
                     "Semtech SX1276 datasheet"))
    # 7 NB-IoT / LTE-M MCL back-solve
    rows.append(_row("NB-IoT MCL implied by Eb/N0 and floor rate at 23 dBm, NF 3 dB [dB]", P.cellular_mcl_check("NBIOT"), 164.0, 0.1,
                     "TR 45.820 target at its stated assumptions (back-solved, consistency only)"))
    m_ltem = P.cellular_mcl_check("LTEM")
    rows.append(dict(check="LTE-M MCL at the TR 36.888 anchor floor, 20 dBm / NF 5 dB, meets the 155.7 dB target [dB]",
                     simulated=round(m_ltem, 2), reference=">= 155.7", tolerance="minimum", passed=m_ltem >= 155.7,
                     source="TR 36.888 target; GSMA LTE-M white paper (target is a minimum; 250 reps exceed it)"))
    # LR-FHSS frame duration (RP002-1.0.5 hop structure, shorter final hop)
    rows.append(_row("LR-FHSS DR8 airtime, 33 B PHY payload [s]", P.lrfhss_frame("DR8", 33)["toa_s"], 2.531328, 1e-6,
                     "RP002-1.0.5 Table 122 structure (value cross-checked in external review)"))
    # antenna energy conservation
    from .antenna import SatAntenna
    from . import presets as PR
    for key, f in (("d2d_array_223m2", 847e6), ("d2d_array_64m2", 847e6), ("smallsat_patch", 868.1e6)):
        a = SatAntenna(dict(PR.SATELLITES[key], sidelobe_model="airy"), f)
        integ = a.pattern_integral(0.0, 1500, 48)
        rows.append(dict(check=f"Pattern energy (1/4pi) int G dOmega, {key} [<= 1]", simulated=round(integ, 3),
                         reference=1.0, tolerance="<= 1 (+1 % quadrature)", passed=integ <= 1.01,
                         source="energy conservation (v1 side-lobe floor gave 9.2)"))
    # RACH configurations valid
    okr = all(lv["period_s"] >= lv["reps"] * PR.RACH[t]["preamble_s"] for t in PR.RACH for lv in PR.RACH[t]["ce"])
    rows.append(dict(check="Every RACH CE level: periodicity >= repetitions x preamble", simulated=okr,
                     reference=True, tolerance="exact", passed=okr, source="TS 36.331 resource validity"))
    # walker input validation and censored gaps
    try:
        G.walker(10, 4, 53, 550); wk = False
    except ValueError:
        wk = True
    rows.append(dict(check="Walker rejects non-divisible satellites/planes", simulated=wk, reference=True,
                     tolerance="exact", passed=wk, source="input validation (F23)"))
    tl = dict(vis=[False] * 100, sid=[None] * 100, dt=10.0)
    cs = G.coverage_stats(tl, 1000.0)
    rows.append(dict(check="Never-visible timeline reports the full window as a censored gap",
                     simulated=cs["max_gap_s"], reference=1000.0, tolerance="exact",
                     passed=cs["max_gap_s"] == 1000.0 and cs["n_censored_gaps"] == 1, source="censoring (F17)"))
    # 8 LoRa Monte Carlo vs pure ALOHA
    rng = Rng(1)
    pool = A.Pool([1.0] * 100)
    for g in (0.05, 0.2, 0.5):
        n, ok = 20000, 0
        for _ in range(n):
            ok += A.lora_attempt(rng, 0, -20, 1.0, 2 * g, pool, capture_db=99)[0]
        rows.append(_row(f"LoRa MC success, no capture, G={g}", ok / n, A.aloha_analytic(g), 0.015,
                         "pure ALOHA exp(-2G)"))
    # 9 LR-FHSS Monte Carlo vs Ullah et al. closed form
    fr = P.lrfhss_frame("DR8", 23)
    for lam in (5, 20, 60):
        a_h, a_f = A.lrfhss_overlap_means(lam, fr)
        n, ok = 8000, 0
        for _ in range(n):
            ok += A.lrfhss_attempt(rng, 30, fr, 1.0, a_h, a_f, pool, capture_db=99, fade_k_db=False)[0]
        rows.append(_row(f"LR-FHSS DR8 MC success, no capture, {lam} pkt/s", ok / n, A.lrfhss_analytic(lam, fr), 0.02,
                         "Ullah, Mikhaylov, Alves, IEEE WCL 2022, eqs. (A_h, A_f, P_h, P_f)"))
    # 10 NPRACH fixed point vs direct preamble-selection MC
    lam, T, M = 60.0, 0.32, 48
    p_acc, p_coll, _ = A.nprach_success(lam, T, M, 1)
    n, coll = 4000, 0
    for _ in range(n):
        k = rng.poisson(lam * T)
        mine = rng.randint(M)
        hit = any(rng.randint(M) == mine for _ in range(k))
        coll += hit
    rows.append(_row("NPRACH collision probability, 60 msg/s, 48 preambles, 1 attempt", p_coll, coll / n, 0.02,
                     "direct Monte Carlo of preamble selection"))
    # NB-IoT table model: anchor and repetition efficiency
    from . import nbiot as NB
    a15 = [x for x in NB.ALLOC if x[0] == "1x15k"][0]
    rows.append(_row("NB-IoT link-level calibration reproduces anchor TBS1000/NRU10/Nrep32 [dB]",
                     NB.required_snr_db(a15, 6, 7, 32, 1000, 1.0), -13.8, 0.01,
                     "Sensors 2020 Table 2 (IMT-2020 164 dB NPUSCH case)"))
    g128 = NB.required_snr_db(a15, 5, 7, 1, 872, 0.5) - NB.required_snr_db(a15, 5, 7, 128, 872, 0.5)
    rows.append(dict(check="NB-IoT hardware calibration (beta 0.5): gain N_rep 1 -> 128 within measured 9.6-11.9 dB",
                     simulated=round(g128, 2), reference="9.6-11.9", tolerance="range", passed=9.6 <= g128 <= 11.9,
                     source="Electronics 2020, 9(11):1947 (hardware measurement)"))
    ltem_ebn0 = -27.0 + 10 * math.log10(360e3) - 10 * math.log10(56 / 0.25)
    rows.append(_row("LTE-M Eb/N0 implied by TR 36.888 anchor (56 b, 250 reps, 2 PRB, -27 dB) [dB]",
                     ltem_ebn0, P.CELLULAR["LTEM"]["ebn0_db"], 0.2, "TR 36.888 Table 9.5.7.1-3 via RAN1#104e summary"))
    # LR-FHSS packet-level receiver agrees with the marginal model in its regime
    for lam in (20, 60):
        n, okp = 6000, 0
        for _ in range(n):
            okp += A.lrfhss_attempt_packet(rng, 30, fr, 1.0, lam, pool, capture_db=99, fade_k_db=False)[0]
        rows.append(_row(f"LR-FHSS packet-level vs closed form, no capture, {lam} pkt/s", okp / n,
                         A.lrfhss_analytic(lam, fr), 0.03, "Ullah et al. 2022 (same marginal statistics)"))
    # event traffic conserves messages
    from .engine import Case
    cz = Case("IO-ISM-LRFHSS", "utility_wells")
    pr = cz.profile()
    tot = sum(pr["m"]) / len(pr["m"])
    rows.append(_row("Event traffic: released + expired + never covered = generated (fraction)",
                     tot + pr["expired_frac"] + pr["lost_frac"], 1.0, 1e-9, "message conservation"))
    # v1.3 checks ------------------------------------------------------------
    # M/G/1 queue: Pollaczek-Khinchine waiting time vs chronological FIFO simulation
    rq = Rng(11)
    lam_q, svc = 0.6, [0.2, 0.5, 3.0]            # mixed service times (deep-coverage tail)
    probs = [0.6, 0.3, 0.1]
    es = sum(p * x for p, x in zip(probs, svc)); es2 = sum(p * x * x for p, x in zip(probs, svc))
    pk = lam_q * es2 / (2 * (1 - lam_q * es))
    t, free, waits = 0.0, 0.0, []
    for _ in range(200000):
        t += rq.exponential(lam_q)
        u = rq.random(); x = svc[0] if u < probs[0] else (svc[1] if u < probs[0] + probs[1] else svc[2])
        start = max(t, free); waits.append(start - t); free = start + x
    rows.append(_row("M/G/1 waiting time: Pollaczek-Khinchine vs chronological FIFO simulation [s]",
                     sum(waits[20000:]) / len(waits[20000:]), pk, 0.05, "queueing theory (N01 validation)", rel=True))
    # angle mode is case-local
    from .engine import Case as _C
    c_a = _C("OP-LB-NBIOT", "utility_wells", g_over=dict(angle_mode="interp"))
    m1 = c_a.margin_at(15, los=False)["margin_db"]
    _C("OP-LB-NBIOT", "utility_wells", g_over=dict(angle_mode="nearest"))
    m2 = c_a.margin_at(15, los=False)["margin_db"]
    rows.append(_row("Angle mode is case-local: interp case unchanged after a nearest case is built [dB]",
                     m2, m1, 1e-9, "N10 regression test"))
    # segmentation above the 1000-bit TBS
    fr2 = NB.frontier((200 + 25) * 8)
    rows.append(dict(check="NB-IoT 200 B payload is segmented into 2 transport blocks (no silent fallback)",
                     simulated=fr2[0]["n_tb"] if fr2 else None, reference=2, tolerance="exact",
                     passed=bool(fr2) and fr2[0]["n_tb"] == 2, source="N11 regression test"))
    # time coverage with no link reports the full window as censored
    from . import analysis as _AN
    tcz = _AN.time_coverage("IO-ISM-LORA-SF12", "disaster_urban")
    rows.append(dict(check="time_coverage with no link: max gap = window, censored",
                     simulated=tcz["max_gap_s"], reference=tcz["window_s"], tolerance="exact",
                     passed=tcz["link_coverage"] > 0 or (tcz["max_gap_s"] == tcz["window_s"] and tcz["n_censored_gaps"] == 1),
                     source="F17 regression test"))
    # S.1528 main-lobe exponent 1.5
    from .antenna import s1528_rel_db
    rows.append(_row("S.1528 rec. 1.2 main lobe at 2 psi_b uses exponent 1.5 [dB]", s1528_rel_db(2.0, 2.0, 40.0),
                     -3 * 2 ** 1.5, 1e-9, "ITU-R S.1528 recommends 1.2 (alpha = 1.5)"))
    # LR-FHSS: full packet enumeration vs element-level branch used above 200 packets (M03):
    # fading, unequal powers, near-threshold SNR, loads with non-zero throughput
    r3 = Rng(31)
    fr8 = P.lrfhss_frame("DR8", 33)
    pool_u = A.Pool([10 ** ((-125 + 6 * r3.normal()) / 10) for _ in range(500)])
    worst_z, worst_d = 0.0, 0.0
    for snr_t in (4.0, 6.0, 10.0):
        for lam_t in (30.0, 80.0):
            n3, kp, ke = 1200, 0, 0
            ra, rb = Rng(int(snr_t * 100 + lam_t)), Rng(int(snr_t * 100 + lam_t))
            for _ in range(n3):
                kp += A.lrfhss_attempt_packet(ra, snr_t, fr8, 10 ** -12.5, lam_t, pool_u, 6.0, 10.0, max_packets=10 ** 9)[0]
                ke += A.lrfhss_attempt_packet(rb, snr_t, fr8, 10 ** -12.5, lam_t, pool_u, 6.0, 10.0, max_packets=-1)[0]
            pa, pb = kp / n3, ke / n3
            se = math.sqrt(max(pa * (1 - pa) + pb * (1 - pb), 1e-6) / n3)
            worst_z = max(worst_z, abs(pa - pb) / se); worst_d = max(worst_d, abs(pa - pb))
    rows.append(dict(check="LR-FHSS packet enumeration vs element-level branch, 6 regimes (SNR 4-10 dB, fading, "
                           "unequal powers): max |difference|",
                     simulated=round(worst_d, 4), reference="<= 0.05 and <= 3 standard errors",
                     tolerance="0.05 / 3 SE", passed=worst_d <= 0.05 and worst_z <= 3.0,
                     source="M03 continuity test (replaces the 0-vs-0 check)"))
    # expired traffic is not charged energy
    from .engine import run_case as _rc
    rz = _rc("IO-ISM-LRFHSS", "utility_wells", g_over=dict(n_mc=600))
    rows.append(dict(check="Expired messages are discarded (counted) and not transmitted",
                     simulated=round(rz["causes"]["expired"], 3), reference="> 0, no delivery",
                     tolerance="logic", passed=rz["causes"]["expired"] > 0, source="N02/N08 regression test"))
    # v1.4 checks ------------------------------------------------------------
    from .engine import Case as _C2, _wait_and_geometry as _wg, run_case as _rc2
    # M04: per-device FIFO backlog never starts a transmission after the deadline or after contact end
    ca = _C2("IO-ISM-LRFHSS", "agri_water")
    rr = Rng(5); bad_dl = bad_ce = n_ok = 0
    for _ in range(4000):
        gq = _wg(ca, rr)
        if gq is None or gq["expired"]:
            continue
        n_ok += 1
        bad_dl += gq["wait"] > ca.sc["deadline_s"]
        bad_ce += gq["left"] < ca.toa - 1e-9
    rows.append(dict(check="FIFO backlog: transmissions starting after deadline / after contact end (agri, LR-FHSS)",
                     simulated=(bad_dl, bad_ce), reference=(0, 0), tolerance="exact", passed=bad_dl == 0 and bad_ce == 0,
                     source="M04 regression test (%d transmitted samples)" % n_ok))
    pr = ca.profile()
    tot = sum(pr["m"]) + (pr["expired_frac"] + pr["lost_frac"]) * len(ca.tl["t"])
    rows.append(_row("Release profile conserves generated messages with FIFO backlog (ratio)", tot / len(ca.tl["t"]),
                     1.0, 1e-9, "M04: profile and targets share one chronology"))
    # M05: beam hopping with 1 % duty never returns time after the contact has ended
    cb = _C2("OP-LB-NBIOT", "utility_wells", stack_over=dict(beams_per_sat=165))
    rr = Rng(6); bad = n_b = 0
    for _ in range(3000):
        gq = _wg(cb, rr)
        if gq is None or gq["expired"]:
            continue
        n_b += 1
        bad += gq["left"] < 0 or gq["j"] > cb.tl["pass_end"][gq["j"]]
    rows.append(dict(check="Beam hopping (duty %.3f): samples with negative remaining contact" % cb.beam_duty,
                     simulated=bad, reference=0, tolerance="exact", passed=bad == 0 and cb.beam_duty < 0.05,
                     source="M05 regression test (%d samples)" % n_b))
    # M06: equal-resource tie broken by airtime
    cfg60 = NB.select(NB.frontier(360), 60.0)
    rows.append(dict(check="NB-IoT 360-bit message at 60 dB-Hz: equal-resource tie broken by airtime [ms]",
                     simulated=round(cfg60["airtime_s"] * 1e3, 3), reference=2.0, tolerance="exact",
                     passed=abs(cfg60["airtime_s"] - 0.002) < 1e-12 and abs(cfg60["res_hz_s"] - 360) < 1e-9,
                     source="M06 regression test"))
    # M07: segmented message runs one HARQ process per transport block
    rs = _rc2("CTRL-NBIOT", "utility_wells", scen_over=dict(payload_b=200), g_over=dict(n_mc=400), keep_samples=True)
    mk = [m for m in rs["sched_marks"] if m["data_ok"]]
    n_bad = sum(1 for m in mk if m["n_tb"] != 2 or m["attempts"] < m["n_tb"])
    rows.append(dict(check="200 B message: delivered samples with 2 TBs and at least one transmission per TB",
                     simulated="%d of %d violate" % (n_bad, len(mk)), reference="0 violate", tolerance="exact",
                     passed=bool(mk) and n_bad == 0, source="M07 regression test"))
    # N03: HARQ retransmissions inside one coherence time get no new fading diversity
    r_short = _rc2("CTRL-NBIOT", "utility_wells", g_over=dict(n_mc=2000, coh_s=0.001))
    r_long = _rc2("CTRL-NBIOT", "utility_wells", g_over=dict(n_mc=2000, coh_s=10.0))
    rows.append(dict(check="HARQ link failures: coherence 10 s >= coherence 1 ms",
                     simulated=(round(r_long["causes"]["snr"], 4), round(r_short["causes"]["snr"], 4)),
                     reference="first >= second", tolerance="logic",
                     passed=r_long["causes"]["snr"] >= r_short["causes"]["snr"], source="N03 regression test"))
    # N06: S.1528 back lobe and full-sphere integration domain
    rows.append(_row("S.1528 back lobe, G_m 40 dBi, L_N -20 dB, z 1 [dBi]", s1528_rel_db(120.0, 2.0, 40.0) + 40.0,
                     5.0, 1e-9, "ITU-R S.1528 recommends 1.2: L_B = max(15 + L_N + 0.25 G_m, 0)"))
    # N08: energy per generated message (no-coverage samples count with zero energy)
    rows.append(dict(check="Energy is averaged over every generated message",
                     simulated=rs.get("energy_basis"), reference="generated", tolerance="exact",
                     passed=rs.get("energy_basis") == "generated", source="N08 regression test"))
    # M01: cheapest-first admission books exactly rho_admit on the admitted population
    rc = _rc2("OP-LB-NBIOT", "disaster_urban", g_over=dict(admission="cheapest_first", nbiot_calibration="link_level", downlink=False))
    rows.append(_row("Cheapest-first: admitted utilisation in the most loaded group (rho_admit 0.9)",
                     rc["rho_admitted_max"], 0.9, 1e-6, "M01: tiered fractional admission, consistent moments"))
    # M02: coverage of the capacity interval procedure on a problem with a known crossing
    import bisect as _bs
    from .analysis import t_interval
    N0, tgt, nmc_t = 5000.0, 0.9, 3000
    true_c = N0 * math.log(1 / tgt)
    rv = Rng(77); cover, trials = 0, 300
    for _ in range(trials):
        reps = []
        for _r in range(10):
            us = sorted(rv.random() for _k in range(nmc_t))
            ok_f = lambda nn: _bs.bisect_left(us, math.exp(-nn / N0)) / nmc_t >= tgt
            lo_, hi_ = 0.0, 7.0
            for _it in range(12):
                mid = (lo_ + hi_) / 2
                lo_, hi_ = (mid, hi_) if ok_f(10 ** mid) else (lo_, mid)
            reps.append(10 ** lo_)
        _, ci_t, _ = t_interval(reps)
        cover += ci_t[0] <= true_c <= ci_t[1]
    rows.append(dict(check="Capacity CI procedure (10 replications x 12-step bisection): coverage on a known crossing",
                     simulated=round(cover / trials, 3), reference="0.90-0.99", tolerance="range",
                     passed=0.90 <= cover / trials <= 0.99, source="M02 coverage test, %d trials" % trials))
    # P01: executed device schedules are FIFO with persistent device busy time across contacts
    viol = n_sched = 0
    for recs in ca.schedule_grid():
        last_start = None
        for gt, stt, st0 in recs:
            if stt != "ok":
                continue
            n_sched += 1
            if st0 < gt - 1e-9 or (last_start is not None and st0 < last_start + ca.per_msg - 1e-9):
                viol += 1
            last_start = st0
    rows.append(dict(check="Executed device schedules (agri, LR-FHSS): FIFO order / device busy-time violations",
                     simulated=viol, reference=0, tolerance="exact", passed=viol == 0,
                     source="P01 regression test over %d scheduled messages" % n_sched))
    # P01: waiting time = start - generation, zero for a message sent at once
    cz = _C2("OP-LB-NBIOT", "utility_wells")
    st_v = cz.next_start(208.0, 0.0, 0.5, 0.5)
    vis_208 = cz.tl["vis"][int(208 // cz.tl["dt"])] and cz.pidx(int(208 // cz.tl["dt"])) == int(208 // cz.tl["dt"])
    rows.append(dict(check="Message generated at 208 s inside an allowed step starts at 208 s (wait 0)",
                     simulated=(round(st_v, 3) if st_v is not None else None, bool(vis_208)),
                     reference="208.0 when allowed", tolerance="exact",
                     passed=(not vis_208) or abs(st_v - 208.0) < 1e-9, source="P01 regression test"))
    # P02: release-profile quadrature convergence (default grid vs 2x phases, 2x release slots)
    pa = ca.profile()["m"]
    pb = ca.profile(grid=ca.schedule_grid(n_phase=4 * int(round(ca.sc["interval_s"] / ca.tl["dt"])), n_jit=12))["m"]
    l1 = sum(abs(x - y) for x, y in zip(pa, pb)) / max(sum(pb), 1e-12)
    rows.append(dict(check="Release-profile quadrature: normalised L1 difference, default vs doubled grid (agri, LR-FHSS)",
                     simulated=round(l1, 4), reference="<= 0.02", tolerance="0.02", passed=l1 <= 0.02,
                     source="P02 convergence check"))
    # P03: one channel clock: duration-weighted, zero-overlap blocks excluded
    fz = {0: 1.0, 1: 3.0, 2: 5.0}
    g1 = A.faded_gain(Rng(1), fz, 0.5, 2.0, 1.0, 10.0)
    g2 = A.faded_gain(Rng(1), fz, 1.0, 2.0, 1.0, 10.0)
    rows.append(dict(check="Channel clock: weighted fading over [0.5, 2.0) s and [1.0, 2.0) s with 1 s blocks (1, 3, 5)",
                     simulated=(round(g1, 6), round(g2, 6)), reference=(round((0.5 * 1 + 1 * 3) / 1.5, 6), 3.0),
                     tolerance="1e-9", passed=abs(g1 - 3.5 / 1.5) < 1e-9 and abs(g2 - 3.0) < 1e-9,
                     source="P03 regression test"))
    # ---- v1.6 downlink checks
    from . import downlink as DLv
    from .antenna import airy_rel_db as _airy
    an = (DLv.anchor_check(0.5), DLv.anchor_check(1.0))
    rows.append(dict(check="Downlink anchor: NPDSCH TBS 680, 8 subframes, 128 repetitions reproduced (beta 0.5 and 1)",
                     simulated=tuple(round(x, 6) for x in an), reference=(-14.7, -14.7), tolerance="1e-9",
                     passed=all(abs(x + 14.7) < 1e-9 for x in an), source="Matz et al., Sensors 2020, Table 2"))
    s0 = DLv.ack_service(0.0, 1.0, 0.1)[0]
    s1, c1 = DLv.ack_service(3.0, 0.5, None, 1)
    s2, c2 = DLv.ack_service(3.0, 0.5, None, 2)
    s3, c3 = DLv.ack_service(30.0, 0.5, 0.1, 1)
    okk = s0 == 1.0 and s2 >= s1 and abs(s1 - 1 / (1 + 1.5)) < 1e-9 and c3 <= 0.1 + 1e-12
    rows.append(dict(check="Acknowledgement service: no load -> 1; one window = Erlang loss 1/(1+A); two windows >= one; duty cap",
                     simulated=(s0, round(s1, 6), round(s2, 6), round(c3, 6)), reference=(1.0, 0.4, ">= 0.4", "<= 0.1"),
                     tolerance="1e-9", passed=okk, source="analytic"))
    cia = DLv.c_over_i_db(0.6, 0.3, _airy, 1.0, 3)
    cib = DLv.c_over_i_db(0.6, 0.3 + math.pi / 3, _airy, 1.0, 3)
    ci0 = DLv.c_over_i_db(0.0, 0.0, _airy, 1.0, 3)
    rows.append(dict(check="Downlink C/I, reuse 3: 60-degree rotational symmetry and positive at beam centre",
                     simulated=(round(cia, 6), round(cib, 6), round(ci0, 2)), reference="equal pair, > 0 dB",
                     tolerance="1e-9", passed=abs(cia - cib) < 1e-9 and ci0 > 0, source="hexagonal geometry"))
    bl = DLv.blank_ok_lrfhss(Rng(3), {"toa_s": 2.0, "nh": 3, "nf": 10, "need": 4}, 0.0, 1.0, 0.233, 0.102)
    rows.append(dict(check="Half-duplex blanking with no gateway transmissions leaves the LR-FHSS packet intact",
                     simulated=bl, reference=True, tolerance="exact", passed=bl is True, source="regression test"))
    off = _rc2("OP-LB-NBIOT", "utility_wells", g_over=dict(downlink=False), cache_dir="out/cache")["pdr_deadline"]
    lr = _rc2("IO-ISM-LRFHSS", "utility_wells", cache_dir="out/cache")["pdr_deadline"]
    rows.append(dict(check="Downlink switched off reproduces v1.5.1 (OP-LB-NBIOT); unconfirmed LR-FHSS unchanged by the downlink",
                     simulated=(off, lr), reference=(0.9856666666666667, 0.29733333333333334), tolerance="exact",
                     passed=off == 0.9856666666666667 and lr == 0.29733333333333334, source="v1.5.1 frozen results"))
    for r in rows:
        log(("PASS " if r["passed"] else "FAIL ") + r["check"] + f"  sim={r['simulated']} ref={r['reference']}")
    return rows
