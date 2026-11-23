"""3GPP NB-IoT / LTE-M transaction with the downlink (v1.7).

Replaces the v1.6 downlink transaction model. Changes (review D01-D08):

Access and coverage level (D03)
    A device that cannot acquire the cell sends no preamble and does not enter
    the access demand. The initial coverage level is chosen from the downlink
    measurement against the level thresholds ('measured', default) or, as a
    labelled oracle-assisted approximation, as max(uplink need, downlink level)
    ('max_ul_dl'). A preamble is detectable at a level when its repetitions meet
    the uplink need. After ce_attempts failed attempts at a level (any cause)
    the device moves to the next level: NPRACH repetitions, period, collision
    class and RAR configuration move together. preambleTransMax is rach_max.

Random-access response (D01)
    One MAC PDU per non-empty occasion and level, one RAR per distinct detected
    preamble (Binomial occupancy), split at the maximum TBS. The RAR carries the
    grant of the first Msg3 transmission, so explicit grants are sent only for
    later HARQ attempts and transport blocks.

Load, re-sends and admission (D02)
    Per (elevation, load) group a fixed point couples: per-level attempt rates
    from each device's coverage-level chain (collision, RAR drop and RAR miss
    probabilities), preamble collisions, RAR load from the occupancy
    distribution, uplink admission, and downlink transaction load with the
    expected number of grant and final-message transmissions (re-sends
    included) from a pre-simulation of each device's decoding on the same
    fading process. Final messages are counted only for planned uplink
    successes. Downlink admission policy: 'uniform' (primary: every downlink
    message is admitted with the same probability), 'ce_barring' (access of the
    deepest initial levels is barred first until the downlink fits;
    transactions of admitted devices are preserved) or 'rar_priority' (the v1.6
    stress policy). The downlink wait is M/G/1 over every carried transmission.

Timeline and energy (D04, D08)
    Every device runs one absolute event timeline from the start of access:
    occasion wait, preamble, round trip, RAR monitoring, backoff, uplink queue,
    grant waits and receptions, uplink attempts evaluated on the uplink fading
    process at their executed times, feedback spacing, and the final message.
    Downlink decoding averages fading only over the occupied transmission time.
    Energy is the sum of mutually exclusive TX / RX / idle intervals, clipped at
    contact end or message expiry. The RAR window is the containing monitoring
    interval, extended when the queued response needs longer. With RAI the
    release is carried by the final message, so no separate release tail.
"""
import math

from . import access as A
from . import downlink as DL
from . import energy as E
from . import nbiot as NB
from . import phy as P
from .rng import Rng

N_PRESIM = 8        # replicas per device for expected downlink transmissions
N_FZ = 16           # fading draws per device for the RAR miss probability


def presim_message(tech, cfg, beta, snr, k_f, coh, rng, retx, spacing, n=N_PRESIM):
    """Expected transmissions, sum of service times and sum of squared service
    times (s) of one downlink message with up to `retx` re-sends."""
    av = DL.TECH[tech]["avail"]
    jobs = s1 = s2 = fail = 0.0
    for _ in range(n):
        fades, ph, t, ok = {}, rng.random() * coh, 0.0, False
        for k in range(retx + 1):
            sf, req = DL.escalate(tech, cfg, k, beta)
            dur = sf * 1e-3 / av
            fad = A.faded_gain(rng, fades, ph + t, ph + t + dur, coh, k_f)
            jobs += 1; s1 += dur; s2 += dur * dur
            if snr + 10 * math.log10(max(fad, 1e-12)) >= req:
                ok = True; break
            t += dur + DL.CTRL_GAP_S + spacing
        fail += 0 if ok else 1
    return dict(jobs=jobs / n, s1=s1 / n, s2=s2 / n, p_fail=fail / n)


def access_chain(l0, det, pc, pd, pm, n_lvl, n_max):
    """Coverage-level chain: returns (P success, expected attempts per level,
    expected detectable attempts per level)."""
    L = len(det)
    e_att, e_det = [0.0] * L, [0.0] * L
    succ = 0.0
    states = {(l0, 0): 1.0}
    for _ in range(n_max):
        new = {}
        for (l, a), p in states.items():
            e_att[l] += p
            if det[l]:
                e_det[l] += p
                q = (1 - pc[l]) * (1 - pd) * (1 - pm[l])
            else:
                q = 0.0
            succ += p * q
            pf = p * (1 - q)
            if pf <= 1e-15:
                continue
            nxt = (l + 1, 0) if (a + 1 >= n_lvl and l < L - 1) else (l, a + 1)
            new[nxt] = new.get(nxt, 0.0) + pf
        states = new
    return succ, e_att, e_det


def ul_admission(dreq, scale, g):
    """Uplink admission (as v1.6): dreq = [(weight, service, first-pass cost)].
    Returns the admission state and a per-device factor function."""
    w_tot = sum(w for w, _, _ in dreq)
    lam_d = scale * w_tot
    es = sum(w * sv for w, sv, _ in dreq) / w_tot if w_tot > 0 else 0.0
    es2 = sum(w * sv * sv for w, sv, _ in dreq) / w_tot if w_tot > 0 else 0.0
    rho = lam_d * es
    f_cut, c_cut, f_all = 1.0, float("inf"), 1.0
    lam_e, e2_e = lam_d, es2
    if rho > g["rho_admit"] and w_tot > 0:
        if g.get("admission", "uniform") == "cheapest_first":
            tiers = {}
            for w, sv, c0 in dreq:
                t = tiers.setdefault(round(c0, 12), [0.0, 0.0, 0.0])
                t[0] += w; t[1] += w * sv; t[2] += w * sv * sv
            acc_r, adm_w, adm_s, adm_s2 = 0.0, 0.0, 0.0, 0.0
            for c0 in sorted(tiers):
                W, S1, S2 = tiers[c0]
                load = scale * S1
                f = 1.0 if acc_r + load <= g["rho_admit"] else (g["rho_admit"] - acc_r) / load
                acc_r += f * load; adm_w += f * W; adm_s += f * S1; adm_s2 += f * S2
                if f < 1.0:
                    f_cut, c_cut = f, c0
                    break
            lam_e, rho_q = scale * adm_w, acc_r
            e2_e = adm_s2 / adm_w if adm_w > 0 else 0.0
            admit = adm_w / w_tot
        else:
            f_all = g["rho_admit"] / rho
            admit, lam_e = f_all, lam_d * f_all
            rho_q = lam_e * es
    else:
        admit, rho_q = 1.0, rho
    st = dict(rho=rho, rho_q=rho_q, admit=admit, f_all=f_all, f_cut=f_cut, c_cut=c_cut, lam_e=lam_e, e2_e=e2_e)

    def factor(c0):
        c0 = round(c0, 12)
        return f_all if c0 < c_cut else (f_cut if c0 == c_cut else 0.0)
    return st, factor


def _pm(lk, level, req):
    key = (level, round(req, 6))
    c = lk["pm_cache"]
    if key not in c:
        c[key] = sum(1 for z in lk["fz"] if lk["snr_dl"] + z < req) / len(lk["fz"])
    return c[key]


def solve_group(case, items, lam, g, st, tech, u_bar=0.0, policy="uniform", init=None, cls_cache=None):
    """Fixed point of access, uplink admission and downlink load for one group.
    items: link records of every device of the group (acquired or not).
    Devices with the same initial level, detectability and RAR-miss vector form
    one class for the coverage-level chain."""
    rach = case.rach
    L = len(rach["ce"])
    M = st["rach_max"]
    n_lvl = g["ce_attempts"]
    per = [lv["period_s"] for lv in rach["ce"]]
    n_p = [lv["preambles"] for lv in rach["ce"]]
    scale = lam / len(items)
    cap_hz = case._cap_hz
    acq = [x for x in items if x.get("acq")]
    al = [1.0 - min(1.0, max(0.0, u_bar - (L - 1 - l))) for l in range(L)]
    pc, pd, fdl = [0.0] * L, 0.0, 1.0
    d_typ = [1] * L
    if init is not None:
        pc, pd, fdl, d_typ = list(init["pc"]), init["pd"], init["fdl"], list(init["d_typ"])
    if cls_cache is None:
        cls_cache = {}
    ulx = [x for x in acq if x["ul_ok"]]
    for x in ulx:
        ng = max(x["att_plan"] - 1, 0)
        x["_t1"] = ng * x["dci_exp"]["s1"] + (x["fin_exp"]["s1"] if x["data_ok_plan"] else 0.0)
        x["_t2"] = ng * x["dci_exp"]["s2"] + (x["fin_exp"]["s2"] if x["data_ok_plan"] else 0.0)
    out = None
    for it in range(80):
        req_l = tuple(case.rar_tab[l][d_typ[l]]["req"] for l in range(L))
        if req_l not in cls_cache:
            cl, idx = {}, []
            for x in acq:
                pm = tuple(round(_pm(x, l, req_l[l]), 3) for l in range(L))
                k_ = (x["l0"], x["det"], pm)
                if k_ not in cl:
                    cl[k_] = len(cl)
                idx.append(cl[k_])
            cnt = [0] * len(cl)
            for i_ in idx:
                cnt[i_] += 1
            cls_cache[req_l] = (list(cl.keys()), idx, cnt)
        keys, idx, cnt = cls_cache[req_l]
        chains = [access_chain(l0, det, pc, pd, pm, n_lvl, M) for (l0, det, pm) in keys]
        lam_det = [0.0] * L
        for (l0, _, _), chn, n_ in zip(keys, chains, cnt):
            a = al[l0] * scale * n_
            for l in range(L):
                lam_det[l] += a * chn[2][l]
        for x, i_ in zip(acq, idx):
            x["_pa"] = al[x["l0"]] * chains[i_][0]
        pc_new = [1 - math.exp(-lam_det[l] * per[l] / n_p[l]) for l in range(L)]
        rho_r = s2_r = rate_r = 0.0
        q_l = [0.0] * L
        for l in range(L):
            m = lam_det[l] * per[l]
            p_ne, e1, e2 = DL.rar_occasion_moments(tech, case.rar_tab[l], n_p[l], m)
            rho_r += p_ne / per[l] * e1; s2_r += p_ne / per[l] * e2; rate_r += p_ne / per[l]
            q_l[l] = 1 - math.exp(-m / n_p[l]) if m > 0 else 0.0
            d_typ[l] = max(1, min(len(case.rar_tab[l]) - 1, int(round(1 + (n_p[l] - 1) * q_l[l]))))
        dreq = [(x["_pa"], x["res"] / cap_hz, x["res0"] / cap_hz) for x in ulx]
        ust, fac = ul_admission(dreq, scale, g)
        rho_t = s2_t = 0.0
        for x in ulx:
            w = scale * x["_pa"] * fac(x["res0"] / cap_hz)
            rho_t += w * x["_t1"]; s2_t += w * x["_t2"]
        ra = g["rho_admit"]
        if policy == "uniform":
            tot = rho_r + rho_t
            f = min(1.0, ra / tot) if tot > 0 else 1.0
            pd_new, fdl_new = 1 - f, f
        elif policy == "rar_priority":
            pd_new = max(0.0, 1 - ra / rho_r) if rho_r > 0 else 0.0
            room = ra - min(rho_r, ra)
            fdl_new = min(1.0, room / rho_t) if rho_t > 0 else 1.0
        else:                                   # ce_barring: barring handled outside, no dropping
            pd_new, fdl_new = 0.0, 1.0
        diff = max([abs(a - b) for a, b in zip(pc, pc_new)] + [abs(pd - pd_new), abs(fdl - fdl_new)])
        pc = [0.5 * a + 0.5 * b for a, b in zip(pc, pc_new)]
        pd, fdl = 0.5 * pd + 0.5 * pd_new, 0.5 * fdl + 0.5 * fdl_new
        out = dict(pc=pc, pd=pd, fdl=fdl, rho_r=rho_r, rho_t=rho_t, s2_r=s2_r, s2_t=s2_t, rate_r=rate_r,
                   q=q_l, d_typ=list(d_typ), ust=ust, fac=fac, al=al, lam_det=lam_det, scale=scale)
        if diff < 1e-7 and it > 2:
            break
    rho_c = out["rho_r"] * (1 - out["pd"]) + out["fdl"] * out["rho_t"]
    s2_c = out["s2_r"] * (1 - out["pd"]) + out["fdl"] * out["s2_t"]
    out["rho_dl"] = out["rho_r"] + out["rho_t"]
    out["rho_dl_c"] = rho_c
    out["w_dl"] = s2_c / (2 * (1 - rho_c)) if rho_c < 1 else float("inf")
    ust = out["ust"]
    rho_q = ust["rho_q"] * out["fdl"]
    lam_u = ust["lam_e"] * out["fdl"]
    out["rho_q"] = rho_q
    out["qwait"] = lam_u * ust["e2_e"] / (2 * (1 - rho_q)) if rho_q < 1 else float("inf")
    return out


def solve_group_policy(case, items, lam, g, st, tech):
    pol = g.get("dl_policy", "ce_barring")
    cc = {}
    if pol != "ce_barring":
        return solve_group(case, items, lam, g, st, tech, 0.0, pol, cls_cache=cc)
    L = len(case.rach["ce"])
    r0 = solve_group(case, items, lam, g, st, tech, 0.0, pol, cls_cache=cc)
    if r0["rho_dl"] <= g["rho_admit"]:
        return r0
    lo, hi, best, last = 0.0, float(L), None, r0
    for _ in range(16):                         # barring depth u to 3/2^16
        mid = 0.5 * (lo + hi)
        r = solve_group(case, items, lam, g, st, tech, mid, pol, init=last, cls_cache=cc)
        last = r
        if r["rho_dl"] <= g["rho_admit"]:
            hi, best = mid, r
        else:
            lo = mid
    return best or solve_group(case, items, lam, g, st, tech, float(L), pol, cls_cache=cc)


def run_cellular_dl(case, samples, rng, rng_dl, keep_samples, helpers):
    """Pass 2 for NB-IoT / LTE-M with the downlink (v1.7)."""
    _prach_reps, _gnss_s = helpers
    st, sc, g, tech = case.st, case.sc, case.g, case.tech
    K = g["n_mc"]
    c = P.CELLULAR[tech]
    rach = case.rach
    L = len(rach["ce"])
    gnss = _gnss_s(case, "nbiot_ntn")
    req_floor = case.required_cn0()
    dev = E.DEVICES[st["device"]]
    i_tx = E.tx_ma(dev, st["ptx_dbm"])
    v = dev["v"] / 1000.0
    harq_proc = g["harq_proc_s"]
    dl = sc["deadline_s"]
    discard = g["discard_expired"]
    bm, mg = case.dl_beta, g["la_margin_db"]
    av = DL.TECH[tech]["avail"]
    retx = g["dl_retx_max"]
    coh = max(g["coh_s"], 1e-3)
    rng_ul2 = Rng(g["seed"] + 202)            # executed uplink fading on the absolute timeline
    rng_fz = Rng(g["seed"] + 303)             # pre-simulation of downlink decoding (demand)
    cap_hz = st["carriers_per_beam"] * c["carrier_ul_hz"] * (1 - st["ctrl_overhead"])
    case._cap_hz = cap_hz
    causes = {"ok": 0, "snr": 0, "doppler": 0, "collision": 0, "no_coverage": 0, "blocked": 0, "expired": 0, "dl": 0}
    energies, lat, lat_conf, cn0s, rates, dl_snrs, marks = [], [], [], [], [], [], []
    link = []
    # ---------------------------------------------------------------- pass 2a: link and plan
    for s in samples:
        if s is None:
            link.append(None); continue
        if s["expired"] or (discard and s["wait"] > dl):
            link.append(dict(acq=False, why="expired")); continue
        cn0_lt = s["p"] - case.n0_eff(s["el"])
        k = g["fade_k_los_db"] if s["los"] else g["fade_k_nlos_db"]
        snr_dl = case.dl_snr_lt(s, rng_dl.random() * 2 * math.pi)
        dl_snrs.append(snr_dl)
        l_dl = DL.dl_level(snr_dl, bm, case.dl_floor)
        if l_dl is None:
            link.append(dict(acq=False, why="dl")); continue
        ul_ok, ul_why = True, None
        t_tb, n_tb, req, b_hz, t_air = 0.0, 1, 0.0, 0.0, 0.0
        if case.front:
            cfg = NB.select(case.front, cn0_lt - g["la_margin_db"])
            if cfg is None:
                ul_ok, ul_why = False, "snr"
            else:
                scs = 3750.0 if cfg["alloc"] == "1x3.75k" else 15000.0
                t_air, b_hz, req = cfg["airtime_s"], cfg["b_hz"], cfg["cn0_req_dbhz"]
                t_tb, n_tb = cfg["tb_airtime_s"], cfg["n_tb"]
        else:
            r = P.cellular_rate_bps(tech, cn0_lt)
            if r is None:
                ul_ok, ul_why = False, "snr"
            else:
                _, t_air, b_hz = P.cellular_resource_hz_s(tech, r, case.bits)
                req, scs = c["ebn0_db"] + 10 * math.log10(r), 15000.0
                t_tb, n_tb = t_air, 1
        if ul_ok:
            fo = g["nbiot_residual_ppm"] * 1e-6 * case.f + abs(s["fdr"]) * g["precomp_update_s"]
            if fo > g["nbiot_max_fo_frac"] * scs:
                ul_ok, ul_why = False, "doppler"
        rtt = case.rtt_s(s["el"])
        spacing = rtt + harq_proc
        att_h, ok_h = 0, True
        if ul_ok:                                # planned HARQ draws (demand only; same stream as v1.6)
            fades, t_c = {}, 0.0
            ph0 = rng.random() * coh
            for _tb in range(n_tb):
                acc, a_tb, ok_tb = 0.0, 0, False
                while a_tb < g["harq_max"]:
                    a_tb += 1
                    fad = A.faded_gain(rng, fades, ph0 + t_c, ph0 + t_c + t_tb, coh, k)
                    acc += 10 ** ((cn0_lt + 10 * math.log10(max(fad, 1e-12))) / 10)
                    t_c += t_tb + spacing
                    if 10 * math.log10(acc) >= req:
                        ok_tb = True; break
                att_h += a_tb
                if not ok_tb:
                    ok_h = False; break
            cn0s.append(cn0_lt)
            if ok_h:
                rates.append(case.bits / t_air)
        need = _prach_reps(cn0_lt - req_floor)
        ce_ul = next(i for i, lv in enumerate(rach["ce"]) if lv["reps"] >= need or i == L - 1)
        l0 = l_dl if g.get("ce_select", "measured") == "measured" else max(l_dl, ce_ul)
        l0 = min(l0, L - 1)
        det = tuple(rach["ce"][l]["reps"] >= need for l in range(L))
        dci = DL.message_config(tech, 0, snr_dl, bm, mg, case.dl_floor, l0)
        fin = (DL.message_config(tech, DL.FINAL_BITS, snr_dl, bm, mg, case.dl_floor, l0)
               or DL.message_config(tech, DL.FINAL_BITS, snr_dl, bm, mg, case.dl_floor, L - 1))
        if dci is None or fin is None:
            link.append(dict(acq=False, why="dl")); continue
        kf = g["fade_k_los_db"] if s["los"] else g["fade_k_nlos_db"]
        fz = [10 * math.log10(max(rng_fz.rician_power(kf), 1e-12)) for _ in range(N_FZ)]
        link.append(dict(acq=True, why=None, ul_ok=ul_ok, ul_why=ul_why, cn0=cn0_lt, k=k, req=req,
                         t_tb=t_tb, n_tb=n_tb, t_air=t_air, b_hz=b_hz,
                         res=b_hz * t_tb * att_h, res0=b_hz * t_tb * n_tb, att_plan=att_h, data_ok_plan=ok_h,
                         l0=l0, ce_ul=ce_ul, det=det, snr_dl=snr_dl, fz=fz, pm_cache={}, dci=dci, fin=fin,
                         dci_exp=presim_message(tech, dci, bm, snr_dl, kf, coh, rng_fz, retx, spacing),
                         fin_exp=presim_message(tech, fin, bm, snr_dl, kf, coh, rng_fz, retx, spacing),
                         rtt=rtt, spacing=spacing))
    # ---------------------------------------------------------------- pass 2b: group fixed points
    groups = {}
    for s, lk in zip(samples, link):
        if s is None or lk["why"] == "expired":
            continue
        lam = case.msg_rate(s["el"], s["j"])
        key = (int(s["el"] // 5) * 5, round(math.log10(max(lam, 1e-9)) * 10))
        s["gkey"] = key
        groups.setdefault(key, []).append((lk, lam))
    state = {}
    for key, items in groups.items():
        lam = sum(x[1] for x in items) / len(items)
        state[key] = solve_group_policy(case, [x[0] for x in items], lam, g, st, tech)
    # ---------------------------------------------------------------- pass 2c: executed timelines
    by_ce = {}
    n_grants = n_grant_tx = 0
    for s, lk in zip(samples, link):
        if s is None:
            energies.append(0.0); causes["no_coverage"] += 1; lat.append(None); lat_conf.append(None); continue
        if lk["why"] == "expired":
            energies.append(0.0); causes["expired"] += 1; lat.append(None); lat_conf.append(None); continue
        stt = state[s["gkey"]]
        q0 = dev["rx_ma"] * dev["sync_s"] + dev["gnss_ma"] * gnss
        if not lk["acq"]:
            energies.append(v * q0); causes["dl"] += 1; lat.append(None); lat_conf.append(None); continue
        cec = by_ce.setdefault(lk["l0"], dict(n=0, ok=0, blocked=0))
        cec["n"] += 1
        pre_s = dev["sync_s"] + gnss
        avail_c = s["left"] - pre_s
        avail_d = (dl - s["wait"] - pre_s) if discard else float("inf")
        lim = min(avail_c, avail_d)
        led = [q0]

        def ch(i_ma, t0, t1):
            a, b = max(t0, 0.0), min(t1, lim)
            if b > a:
                led[0] += i_ma * (b - a)
        a_bar = stt["al"][lk["l0"]]
        if a_bar < 1.0 and rng_dl.random() >= a_bar:            # CE-aware access barring
            energies.append(v * led[0]); causes["blocked"] += 1; cec["blocked"] += 1
            lat.append(None); lat_conf.append(None); continue
        W = stt["w_dl"] if stt["w_dl"] != float("inf") else s["left"]
        rtt, spacing = lk["rtt"], lk["spacing"]
        fades_dl, ph_dl = {}, rng_dl.random() * coh

        def dl_ok(t0, dur, req):
            fad = A.faded_gain(rng_dl, fades_dl, ph_dl + t0, ph_dl + t0 + dur, coh, lk["k"])
            return lk["snr_dl"] + 10 * math.log10(max(fad, 1e-12)) >= req
        # ---- access with coverage-level transitions
        t, l, a_l, ok, why = 0.0, lk["l0"], 0, False, "collision"
        for _att in range(st["rach_max"]):
            if t >= lim:
                break
            lv = rach["ce"][l]
            w0 = rng.random() * lv["period_s"]
            ch(dev["idle_ma"], t, t + w0); t += w0
            pre = lv["reps"] * rach["preamble_s"]
            ch(i_tx, t, t + pre); t += pre
            ch(dev["idle_ma"], t, t + rtt); t += rtt
            det = lk["det"][l]
            coll = det and rng.random() < stt["pc"][l]
            sent = det and rng_dl.random() >= stt["pd"]
            if sent:
                q, n_p = stt["q"][l], lv["preambles"]
                D = 1 + sum(1 for _ in range(n_p - 1) if rng_dl.random() < q)
                sizes = DL.rar_batch_pdus(tech, D, len(case.rar_tab[l]) - 1)
                pos, idx = rng_dl.randint(D), 0
                while pos >= sizes[idx]:
                    pos -= sizes[idx]; idx += 1
                off = sum(DL.msg_time_s(tech, case.rar_tab[l][sz]["sf"]) for sz in sizes[:idx])
                cp = case.rar_tab[l][sizes[idx]]
                dur = cp["sf"] * 1e-3 / av
                t_dec = t + W + off
                got = dl_ok(t_dec, dur, cp["req"])
                mon = max(rach["rar_window_s"], W + off + dur + DL.CTRL_GAP_S)
                if got and not coll:
                    ch(dev["rx_ma"], t, t_dec + dur + DL.CTRL_GAP_S); t = t_dec + dur + DL.CTRL_GAP_S
                    ok = True; break
                why = "collision" if coll else "dl"
            else:
                cp = case.rar_tab[l][stt["d_typ"][l]]
                mon = max(rach["rar_window_s"], W + DL.msg_time_s(tech, cp["sf"]))
                why = "snr" if not det else "dl"
            ch(dev["rx_ma"], t, t + mon); t += mon
            bo = rng.random() * rach["backoff_s"]
            ch(dev["idle_ma"], t, t + bo); t += bo
            a_l += 1
            if a_l >= g["ce_attempts"] and l < L - 1:
                l, a_l = l + 1, 0
        if not ok:
            energies.append(v * led[0]); causes[why] += 1; lat.append(None); lat_conf.append(None); continue
        if t > lim:
            energies.append(v * led[0]); causes["no_coverage" if avail_c <= avail_d else "expired"] += 1
            lat.append(None); lat_conf.append(None); continue
        if not lk["ul_ok"]:
            energies.append(v * led[0]); causes[lk["ul_why"]] += 1; lat.append(None); lat_conf.append(None); continue
        t_acc_end = t
        f_adm = stt["fac"](lk["res0"] / cap_hz) * stt["fdl"]
        mk = None
        if keep_samples:
            mk = dict(el=s["el"], j=s["j"], wait=s["wait"], pre=pre_s + t_acc_end, air=None,
                      svc=lk["res"] / cap_hz, svc0=lk["res0"] / cap_hz, attempts=lk["att_plan"], n_tb=lk["n_tb"],
                      left=s["left"], data_ok=lk["data_ok_plan"])
        if f_adm < 1.0 and rng.random() >= f_adm:
            if mk is not None:
                mk.update(sched="blocked", qw=None); marks.append(mk)
            energies.append(v * led[0]); causes["blocked"] += 1; cec["blocked"] += 1
            lat.append(None); lat_conf.append(None); continue
        if not st["edt"]:
            led[0] += dev["rx_ma"] * dev["setup_extra_rx_s"] + i_tx * dev["setup_extra_tx_s"]
        qw = stt["qwait"] if stt["qwait"] != float("inf") else s["left"]
        ch(dev["idle_ma"], t, t + qw); t += qw
        # ---- data on the absolute clock: grants (after the first attempt), attempts, feedback
        fades_ul, ph_ul = {}, rng_ul2.random() * coh
        first, dci_fail, incomplete, data_ok, t_last = True, False, False, True, None
        t_data0 = t
        for _tb in range(lk["n_tb"]):
            acc, ok_tb = 0.0, False
            for _a in range(g["harq_max"]):
                if not first:
                    n_grants += 1
                    got = False
                    for kk in range(retx + 1):
                        sfk, rqk = DL.escalate(tech, lk["dci"], kk, bm)
                        dur = sfk * 1e-3 / av
                        ch(dev["idle_ma"], t, t + W); t += W
                        ch(dev["rx_ma"], t, t + dur + DL.CTRL_GAP_S)
                        n_grant_tx += 1
                        okg = dl_ok(t, dur, rqk); t += dur + DL.CTRL_GAP_S
                        if okg:
                            got = True; break
                        ch(dev["idle_ma"], t, t + spacing); t += spacing
                    if not got:
                        dci_fail = True; break
                first = False
                if t + lk["t_tb"] > lim:
                    ch(i_tx, t, t + lk["t_tb"]); t += lk["t_tb"]
                    incomplete = True; break
                fad = A.faded_gain(rng_ul2, fades_ul, ph_ul + t, ph_ul + t + lk["t_tb"], coh, lk["k"])
                acc += 10 ** ((lk["cn0"] + 10 * math.log10(max(fad, 1e-12))) / 10)
                ch(i_tx, t, t + lk["t_tb"]); t += lk["t_tb"]; t_last = t
                ch(dev["idle_ma"], t, t + spacing); t += spacing
                if 10 * math.log10(acc) >= lk["req"]:
                    ok_tb = True; break
            if dci_fail or incomplete:
                break
            if not ok_tb:
                data_ok = False; break
        conf, t_fin = False, None
        if not (dci_fail or incomplete) and data_ok:
            for kk in range(retx + 1):
                sfk, rqk = DL.escalate(tech, lk["fin"], kk, bm)
                dur = sfk * 1e-3 / av
                ch(dev["idle_ma"], t, t + W); t += W
                ch(dev["rx_ma"], t, t + dur + DL.CTRL_GAP_S)
                okf = dl_ok(t, dur, rqk); t += dur + DL.CTRL_GAP_S
                if okf:
                    conf, t_fin = True, t; break
                ch(dev["idle_ma"], t, t + spacing); t += spacing
        if t_last is not None and not st["rai"]:
            ch(dev["idle_ma"], t, t + dev["inactivity_s"])
        energies.append(v * led[0])
        if mk is not None:
            fit = t_last is not None and t_last + rtt <= avail_c
            mk.update(qw=qw, air=(t_last - t_data0 + rtt) if t_last else 0.0,
                      sched=("late_contact" if not fit else
                             ("late_deadline" if s["wait"] + pre_s + t_last + rtt > dl else "served")))
            marks.append(mk)
        if dci_fail:
            causes["dl"] += 1; lat.append(None); lat_conf.append(None); continue
        if incomplete:
            causes["no_coverage" if avail_c <= avail_d else "expired"] += 1
            lat.append(None); lat_conf.append(None); continue
        if not data_ok:
            causes["snr"] += 1; lat.append(None); lat_conf.append(None); continue
        gd = 0.0 if st.get("payload") == "transparent" else g["ground_delay_s"]
        d = s["wait"] + pre_s + t_last + rtt + gd
        causes["ok"] += 1; lat.append(d)
        lat_conf.append((s["wait"] + pre_s + t_fin + gd) if (conf and t_fin <= avail_c) else None)
        if d <= dl:
            cec["ok"] += 1
    allst = list(state.values())
    extra = dict(rho_max=max((x["ust"]["rho"] for x in allst), default=0.0),
                 rho_dl_max=max((x["rho_dl"] for x in allst), default=0.0),
                 rho_dl_carried_max=max((x["rho_dl_c"] for x in allst), default=0.0),
                 rar_load_max=max((x["rho_r"] for x in allst), default=0.0),
                 rar_drop_max=max((x["pd"] for x in allst), default=0.0),
                 dl_admission_min=min((x["fdl"] for x in allst), default=1.0),
                 dl_wait_max_s=max((x["w_dl"] for x in allst), default=0.0),
                 barred_max=max((1 - min(x["al"]) for x in allst), default=0.0),
                 rar_batch_max=max((max(x["d_typ"]) for x in allst), default=1),
                 admitted_fraction_min=min((x["ust"]["admit"] * x["fdl"] for x in allst), default=1.0),
                 rho_admitted_max=max((x["rho_q"] for x in allst), default=0.0),
                 admission=g.get("admission", "uniform"), dl_policy=g.get("dl_policy", "ce_barring"),
                 ce_select=g.get("ce_select", "measured"),
                 grant_tx_per_grant=(n_grant_tx / n_grants) if n_grants else None,
                 on_time_by_ce={str(kk): dict(share=vv["n"] / K, on_time=vv["ok"] / max(vv["n"], 1),
                                              blocked=vv["blocked"] / max(vv["n"], 1))
                                for kk, vv in sorted(by_ce.items())},
                 p_preamble_collision_max=max((max(x["pc"]) for x in allst), default=0.0),
                 burst_rate_bps=(sum(rates) / len(rates)) if rates else None,
                 nbiot_model=g["nbiot_model"] if tech == "NBIOT" else None,
                 nbiot_calibration=g["nbiot_calibration"] if tech == "NBIOT" else None,
                 nbiot_objective=g.get("nbiot_objective", "resource") if tech == "NBIOT" else None)
    if getattr(case, "dl_rf_budget", None):
        extra["dl_rf_budget"] = case.dl_rf_budget
    return dict(energies=energies, causes=causes, lat=lat, lat_conf=lat_conf, cn0s=cn0s, rates=rates,
                dl_snrs=dl_snrs, marks=marks, extra=extra, cap_hz=cap_hz)


# ====================================================================== LoRaWAN confirmed mode (v1.7)
def run_lora_confirmed(case, info, lat, energies, rng_dl, iters=6):
    """Class A acknowledgements from one half-duplex satellite transmitter.

    D05/D06: the gateway's acknowledgement transmissions form one stationary,
    non-overlapping on-off calendar (single-server loss system, no queue,
    window-specific duty budgets thinning admissions). For every delivered
    uplink the same sampled calendar decides (a) which uplink elements are
    blanked (half-duplex gateways), jointly with the decode flags of the
    receiver, and (b) whether RX1 (regional-parameter rate, when its link
    closes) or RX2 (configured rate) finds the transmitter idle. The
    acknowledgement must end inside the contact. Acknowledgement demand is
    recomputed from the uplinks that survive blanking (fixed point with common
    random numbers)."""
    st, g, tech = case.st, case.g, case.tech
    copies = st.get("copies", 1)
    own = 1.0 / (copies * (1.0 + st.get("other_networks_load", 0.0)))
    wins = case.ack_win
    dev_l = E.DEVICES[st["device"]]
    rx_j = dev_l["v"] * dev_l["rx_ma"] / 1000.0
    th, tf = P.LRFHSS_TH_S, P.LRFHSS_TF_S
    coh = max(g["coh_s"], 1e-3)
    seeds = [rng_dl.randint(2 ** 31 - 1) if it is not None else None for it in info]
    grp = {}
    for it in info:
        if it is not None:
            grp.setdefault(it["gkey"], []).append(it)
    lam_g = {k_: sum(x["lam"] for x in v_) / len(v_) for k_, v_ in grp.items()}
    p_surv = {k_: sum(1 for x in v_ if x["ok"]) / len(v_) for k_, v_ in grp.items()}
    span_lo = -max(w["t"] for w in wins)

    def evaluate(cals, final):
        res = []
        for it, sd in zip(info, seeds):
            if it is None or not it["ok"]:
                res.append(None); continue
            rr = Rng(sd)
            cal = cals[it["gkey"]]
            iv = DL.sample_calendar(rr, cal, it["t0"] + span_lo, it["t_end"] + DL.RX2_DELAY_S + 1e-6, wins)
            ok_c = True
            if case.half_duplex and iv:
                if tech == "LRFHSS":
                    fl = it["flags"] or [True] * (case.frame["nh"] + case.frame["nf"])
                    ok_c = DL.joint_lrfhss_ok(fl, case.frame, it["t0"], iv, th, tf)
                else:
                    ok_c = not DL.overlaps(iv, it["t0"], it["t_end"])
            if not final:
                res.append(dict(ok_c=ok_c)); continue
            chosen = None
            for w in (0, 1):
                if not wins[w]["used"]:
                    continue
                tw = it["t_end"] + wins[w]["delay"]
                if DL.busy_at(iv, tw):
                    continue
                if rr.random() >= cal["a"][w]:
                    continue
                chosen = w; break
            res.append(dict(ok_c=ok_c, w=chosen, rr=rr))
        return res

    cals = {}
    for _ in range(iters):
        cals = {k_: DL.ack_calendar_params(lam_g[k_] * own * p_surv[k_], wins) for k_ in grp}
        if not case.half_duplex:
            break
        res = evaluate(cals, False)
        cnt = {}
        for it, r in zip(info, res):
            if it is not None:
                c_ = cnt.setdefault(it["gkey"], [0, 0])
                c_[0] += 1; c_[1] += 1 if (r is not None and r["ok_c"]) else 0
        p_new = {k_: v_[1] / v_[0] for k_, v_ in cnt.items()}
        if max(abs(p_new[k_] - p_surv[k_]) for k_ in p_new) < 1e-4:
            p_surv = p_new
            break
        p_surv = p_new
    cals = {k_: DL.ack_calendar_params(lam_g[k_] * own * p_surv[k_], wins) for k_ in grp}
    res = evaluate(cals, True)
    lat_conf, e_conf, lat_cmode, dl_snrs = [], [], [], []
    n_rx1 = n_ack = 0
    for it, r, d0, e0 in zip(info, res, lat, energies):
        if it is None:
            lat_conf.append(None); lat_cmode.append(None); e_conf.append(e0); continue
        n_cp = it["n_cp"]
        if r is None or not r["ok_c"]:
            lat_cmode.append(None); lat_conf.append(None)
            e_w = (rx_j * g["rx_window_symbols"] * sum(P.lora_symbol_s(w["sf"]) for w in wins if w["used"]) * n_cp
                   if not st.get("class_a_rx") else 0.0)
            e_conf.append(e0 + e_w); continue
        lat_cmode.append(d0)
        s = it["s"]
        rr = r["rr"]
        snr2 = case.dl_snr_lt(s, rr.random() * 2 * math.pi, wins[1]["eirp"], wins[1]["f"])
        dl_snrs.append(snr2)
        w = r["w"]
        in_rx1 = w == 0
        e_w = (rx_j * g["rx_window_symbols"] * ((P.lora_symbol_s(wins[0]["sf"]) if wins[0]["used"] else 0.0)
                                                + (0.0 if in_rx1 else P.lora_symbol_s(wins[1]["sf"]))) * n_cp
               if not st.get("class_a_rx") else 0.0)
        if w is None:
            lat_conf.append(None); e_conf.append(e0 + e_w); continue
        n_ack += 1; n_rx1 += 1 if in_rx1 else 0
        win = wins[w]
        snr_w = snr2 if w == 1 else case.dl_snr_lt(s, rr.random() * 2 * math.pi, win["eirp"], win["f"])
        k_ = g["fade_k_los_db"] if s["los"] else g["fade_k_nlos_db"]
        ph = rr.random() * coh
        fad = A.faded_gain(rr, {}, ph, ph + win["t"], coh, k_)
        t_ack_end = it["t_end"] + win["delay"] + win["t"]
        got = (snr_w + 10 * math.log10(max(fad, 1e-12)) >= P.LORA_SNR_DB[win["sf"]] and t_ack_end <= s["left"]
               and d0 is not None)
        e_conf.append(e0 + e_w + rx_j * win["t"])
        lat_conf.append((d0 + win["delay"] + win["t"]) if got else None)
    extra = dict(ack_service_min=min((c_["served"] for c_ in cals.values()), default=1.0),
                 dl_tx_occupancy_max=max((c_["occ"] for c_ in cals.values()), default=0.0),
                 rx1_used=wins[0]["used"], rx1_sf=wins[0]["sf"], rx1_snr_edge_db=wins[0]["snr_edge"],
                 rx2_snr_edge_db=wins[1]["snr_edge"], rx1_share=(n_rx1 / n_ack) if n_ack else None)
    return dict(lat_conf=lat_conf, e_conf=e_conf, lat_cmode=lat_cmode, dl_snrs=dl_snrs, extra=extra)
