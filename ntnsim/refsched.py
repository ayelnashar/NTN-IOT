"""Chronological comparison scheduler for the scheduled 3GPP uplink.

STATUS (P05): this is an exploratory POLICY COMPARISON, not a validation of
the engine's queue. The reference runs deadline-aware FIFO or smallest-cost
priority WITHOUT the engine's rho admission, rejects requests using their
realised HARQ airtime, resamples marks by elevation only and uses a shorter
window. Its served fraction counts scheduling completions only (PHY failures
excluded) and must not be read as delivery probability. A matched
chronological validation of the engine's admission + queue model is listed
as an open item.

Arrivals: for every visible time step of the arrival window, data requests
reach the cell as a Poisson process with rate msg_rate(el, j) times the
fraction of generated messages that pass access with a feasible configuration
in that elevation bin (taken from the engine's own samples). Each request
draws its marks (pre-scheduling time, service demand on the carrier including
every HARQ attempt, air-interface transaction time, wait already spent) from
engine samples of the same 5-degree elevation bin.

Server: one server per beam whose service time is the request's resource /
usable carrier bandwidth (the same fluid capacity the engine uses). A request
is served only if it can finish inside its remaining contact and within its
deadline; otherwise it is dropped at service start without consuming capacity.
Two causal service orders:
  policy='fifo'      deadline-aware first-come first-served (reference for the
                     engine's uniform admission);
  policy='cost'      non-preemptive priority to the smallest granted first-pass
                     resource (reference for the engine's cheapest_first).

Compared quantities: fraction of scheduled requests served in time and mean
queue wait of served requests, engine versus reference, on the same marks.
The reference reports the served fraction per request (network view: low-
elevation cells hold more devices) and per device (each request weighted by
1/devices in its cell), which is the basis of the engine's KPI.
"""
import heapq
import math

from . import engine as E
from .rng import Rng


def reference_scheduler(stack, scen, load_scale=1.0, g_over=None, cache_dir=None, hours=6.0, seed=7,
                        policy=None):
    go = dict(g_over or {})
    r = E.run_case(stack, scen, scen_over=dict(load_scale=load_scale), g_over=go, cache_dir=cache_dir,
                   keep_samples=True)
    case = E.Case(stack, scen, scen_over=dict(load_scale=load_scale), g_over=go, cache_dir=cache_dir)
    marks = r["sched_marks"]
    if not marks:
        return dict(stack=stack, scenario=scen, load_scale=load_scale, note="no scheduled requests")
    tl, dt, dl = case.tl, case.tl["dt"], case.sc["deadline_s"]
    # fraction of generated (non-expired, covered) messages that reach the scheduler, per elevation bin
    n_gen = r["n_mc"] * (1 - r["causes"]["no_coverage"] - r["causes"]["expired"])
    by_bin = {}
    for m in marks:
        by_bin.setdefault(int(m["el"] // 5) * 5, []).append(m)
    els = [x for x in r["elevations"]]
    gen_bin = {}
    for e in els:
        b = int(e // 5) * 5
        gen_bin[b] = gen_bin.get(b, 0) + 1
    bins = sorted(by_bin)
    rng = Rng(seed)
    arr = []
    j0, j1 = case.a0, min(case.a0 + int(hours * 3600 / dt), len(tl["t"]))
    for j in range(j0, j1):
        if not tl["vis"][j]:
            continue
        el = tl["el"][j]
        b = int(el // 5) * 5
        if b not in by_bin:
            b = min(bins, key=lambda x: abs(x - b))
        frac = len(by_bin[b]) / max(gen_bin.get(b, len(by_bin[b])), 1)
        lam = case.msg_rate(el, j) * frac
        for _ in range(rng.poisson(lam * dt)):
            t = (j + rng.random()) * dt
            mk = by_bin[b][rng.randint(len(by_bin[b]))]
            end_t = (tl["pass_end"][j] + 1) * dt
            wdev = 1.0 / case.devices_in_cell(el)[0]       # per-device weight (engine KPI is per device)
            arr.append((t + mk["pre"], mk, end_t, wdev))
    arr.sort(key=lambda x: x[0])
    policy = policy or ("cost" if go.get("admission") == "cheapest_first" else "fifo")
    feasible = lambda start, t_a, mk, end_t: (start + mk["air"] <= end_t and
                                              mk["wait"] + mk["pre"] + (start - t_a) + mk["air"] <= dl)
    t_free, served, waits, busy, w_srv = -1e30, 0, [], 0.0, 0.0
    w_all = sum(x[3] for x in arr)
    if policy == "fifo":
        for t_a, mk, end_t, wd in arr:
            start = max(t_a, t_free)
            if feasible(start, t_a, mk, end_t):
                t_free = start + mk["svc"]; busy += mk["svc"]; served += 1; waits.append(start - t_a); w_srv += wd
    else:
        heap, i, n_a, tie = [], 0, len(arr), 0
        t = arr[0][0] if arr else 0.0
        while i < n_a or heap:
            if not heap and i < n_a and arr[i][0] > t:
                t = arr[i][0]
            while i < n_a and arr[i][0] <= t:
                t_a, mk, end_t, wd = arr[i]
                heapq.heappush(heap, (mk["svc0"], tie, t_a, mk, end_t, wd)); tie += 1; i += 1
            while heap:
                _, _, t_a, mk, end_t, wd = heapq.heappop(heap)
                if feasible(t, t_a, mk, end_t):
                    busy += mk["svc"]; served += 1; waits.append(t - t_a); t += mk["svc"]; w_srv += wd
                    break
    n = len(arr)
    vis_t = sum(1 for j in range(j0, j1) if tl["vis"][j]) * dt
    eng_served = [m for m in marks if m["sched"] == "served"]
    eng_w = [m["qw"] for m in eng_served if m["qw"] is not None]
    ws = sorted(waits)
    return dict(stack=stack, scenario=scen, load_scale=load_scale, admission=go.get("admission", "uniform"),
                reference_policy=policy,
                calibration=go.get("nbiot_calibration", "hardware"), hours=hours, requests=n,
                reference=dict(served_fraction=served / n if n else None,
                               served_fraction_device_weighted=w_srv / w_all if w_all else None,
                               mean_wait_s=(sum(waits) / len(waits)) if waits else None,
                               p95_wait_s=ws[int(0.95 * (len(ws) - 1))] if ws else None,
                               utilisation=busy / vis_t if vis_t else None),
                engine=dict(served_fraction=len(eng_served) / len(marks),
                            mean_wait_s=(sum(eng_w) / len(eng_w)) if eng_w else None,
                            rho_max=r.get("rho_max"), admitted_fraction_min=r.get("admitted_fraction_min")))
