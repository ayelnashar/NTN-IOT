"""Static figures (PNG + PDF) from results.json. matplotlib only; not part of the
portable core."""
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

COL = {"OP-LB-NBIOT": "#2a78d6", "IO-ISM-LRFHSS": "#eb6834", "OP-MSS-NBIOT": "#1baf7a",
       "IO-ISM-LORA-SF12": "#eda100", "IO-SBAND-LRFHSS": "#e87ba4", "OP-LB-LTEM": "#008300",
       "IO-ISM-LORA-SF10": "#6250d6", "IO-SBAND-LRFHSS-HP": "#e34948",
       "CTRL-NBIOT": "#2a78d6", "CTRL-LRFHSS": "#eb6834", "CTRL-LORA-SF12": "#eda100",
       "CTRL-SS-NBIOT": "#2a78d6", "CTRL-SS-LRFHSS": "#eb6834", "CTRL-SS-LORA-SF12": "#eda100"}
SHORT = {"OP-LB-NBIOT": "Operator NB-IoT, 847 MHz, 223 m² array",
         "OP-LB-LTEM": "Operator LTE-M, 847 MHz, 223 m² array",
         "OP-MSS-NBIOT": "NB-IoT via MSS partner, L-band smallsat",
         "IO-ISM-LRFHSS": "IoT-only LR-FHSS, ISM 868 MHz smallsat",
         "IO-ISM-LORA-SF10": "IoT-only LoRa SF10, ISM 868 MHz",
         "IO-ISM-LORA-SF12": "IoT-only LoRa SF12, ISM 868 MHz",
         "IO-SBAND-LRFHSS": "IoT-only LR-FHSS, S-band, LR1120 +11.5 dBm",
         "IO-SBAND-LRFHSS-HP": "IoT-only LR-FHSS, S-band, +27 dBm module",
         "CTRL-NBIOT": "Control NB-IoT (223 m² array)", "CTRL-LRFHSS": "Control LR-FHSS (223 m² array)",
         "CTRL-LORA-SF12": "Control LoRa SF12 (223 m² array)",
         "CTRL-SS-NBIOT": "Control NB-IoT (smallsat)", "CTRL-SS-LRFHSS": "Control LR-FHSS (smallsat)",
         "CTRL-SS-LORA-SF12": "Control LoRa SF12 (smallsat)"}
MAIN = ["OP-LB-NBIOT", "OP-LB-LTEM", "OP-MSS-NBIOT", "IO-ISM-LRFHSS", "IO-ISM-LORA-SF10",
        "IO-ISM-LORA-SF12", "IO-SBAND-LRFHSS", "IO-SBAND-LRFHSS-HP"]
CONTROL = ["CTRL-NBIOT", "CTRL-LRFHSS", "CTRL-LORA-SF12", "CTRL-SS-NBIOT", "CTRL-SS-LRFHSS", "CTRL-SS-LORA-SF12"]
SCEN_SHORT = {"utility_wells": "Utility wells", "agri_water": "Agri / water",
              "logistics": "Logistics", "disaster_urban": "Disaster, urban"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def _style():
    plt.rcParams.update({
        "font.size": 9, "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2,
        "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "legend.frameon": False, "legend.fontsize": 7.5, "lines.linewidth": 1.6,
        "figure.dpi": 110, "savefig.bbox": "tight"})


def _save(fig, out, name):
    for ext in ("png", "pdf"):
        fig.savefig(os.path.join(out, f"{name}.{ext}"), dpi=200)
    plt.close(fig)


def _ls(s):
    if s.startswith("CTRL-SS"):
        return "-."
    if s.startswith("CTRL"):
        return "--"
    if "LORA" in s:
        return (0, (1.2, 1.4))      # dotted: LoRa sits on top of LR-FHSS in several plots
    return "-"


def make_all(results_path="out/results.json", out="out/figs"):
    _style()
    os.makedirs(out, exist_ok=True)
    R = json.load(open(results_path))
    made = []

    # 1 path loss -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s, lab in (("OP-LB-NBIOT", "847 MHz, 520 km"), ("IO-ISM-LRFHSS", "868 MHz, 550 km"),
                   ("OP-MSS-NBIOT", "1643.5 MHz, 500 km"), ("IO-SBAND-LRFHSS", "1995 MHz, 550 km")):
        pl = R["path_loss"][s]
        el = [p["el"] for p in pl]
        ax.plot(el, [p["fspl_db"] for p in pl], color=COL[s], label=f"{lab}: free space")
        ax.plot(el, [p["pl_nlos_db"] for p in pl], color=COL[s], ls=":", label=f"{lab}: + rural NLOS clutter")
    ax.set_xlabel("Elevation angle (deg)"); ax.set_ylabel("Path loss (dB)")
    ax.set_title("Path loss versus elevation (TR 38.811, rural)", loc="left", fontsize=10)
    ax.legend(ncol=2, fontsize=6.8)
    _save(fig, out, "fig01_path_loss"); made.append("fig01_path_loss")

    # 2 link margin ------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s in MAIN:
        cc = R["coverage_curve"]["utility_wells"][s]
        ax.plot([c["el"] for c in cc], [c["margin_los_db"] for c in cc], color=COL[s], ls=_ls(s), label=SHORT[s])
    ax.axhline(0, color=INK2, lw=0.9)
    ax.set_xlabel("Elevation angle (deg)"); ax.set_ylabel("Uplink margin, LOS median (dB)")
    ax.set_title("Link budget margin versus elevation (utility wells, outdoor)", loc="left", fontsize=10)
    ax.legend(fontsize=6.6, loc="center left", bbox_to_anchor=(1.01, 0.5))
    _save(fig, out, "fig02_link_margin"); made.append("fig02_link_margin")

    # 3 coverage probability ---------------------------------------------------
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.3), sharey=True)
    for ax, sc in zip(axs, ("utility_wells", "disaster_urban")):
        for s in MAIN:
            cc = R["coverage_curve"][sc][s]
            ax.plot([c["el"] for c in cc], [c["p_cov"] for c in cc], color=COL[s], ls=_ls(s), label=SHORT[s])
        ax.set_title(SCEN_SHORT[sc], loc="left", fontsize=9.5)
        ax.set_xlabel("Elevation angle (deg)")
    axs[0].set_ylabel("P(link closes)")
    axs[1].legend(fontsize=6.3, loc="lower right")
    fig.suptitle("Coverage probability versus elevation (TR 38.811 LOS/NLOS mixture)", x=0.01, y=1.03, ha="left", fontsize=10)
    _save(fig, out, "fig03_coverage_probability"); made.append("fig03_coverage_probability")

    # 4 cell radius --------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    stacks = MAIN + CONTROL
    vals = [R["cell_radius"]["utility_wells"][s].get("cell_radius_km") or 0 for s in stacks]
    svc = [R["cell_radius"]["utility_wells"][s].get("service_radius_km") or 0 for s in stacks]
    y = list(range(len(stacks)))
    ax.barh([v + 0.18 for v in y], vals, height=0.34, color=[COL[s] for s in stacks], label="Cell radius (beam spot or footprint)")
    ax.barh([v - 0.18 for v in y], svc, height=0.34, color="#b9b8b2", label="Satellite service radius (link closes, 90 %)")
    ax.set_xscale("log"); ax.set_yticks(y); ax.set_yticklabels([SHORT[s] for s in stacks], fontsize=7)
    ax.invert_yaxis(); ax.set_xlabel("Radius (km, log scale)")
    for v, r in zip(y, vals):
        if r:
            ax.text(r * 1.08, v + 0.18, f"{r:,.0f}" if r >= 10 else f"{r:.1f}", va="center", fontsize=6.5, color=INK)
    ax.set_title("Cell radius and service radius (utility wells)", loc="left", fontsize=10, pad=22)
    ax.legend(fontsize=6.8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    _save(fig, out, "fig04_cell_radius"); made.append("fig04_cell_radius")

    # 5 time coverage --------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    geo = [R["time_coverage"]["utility_wells"][s]["geometric_coverage"] for s in stacks]
    lnk = [R["time_coverage"]["utility_wells"][s]["link_coverage"] for s in stacks]
    ax.barh([v - 0.18 for v in y], geo, height=0.34, color="#b9b8b2", label="Satellite in view")
    ax.barh([v + 0.18 for v in y], lnk, height=0.34, color=[COL[s] for s in stacks], label="Link closes with 90 % probability")
    for v, r in zip(y, lnk):
        ax.text(r + 0.01, v + 0.18, f"{100 * r:.0f} %", va="center", fontsize=6.5)
    ax.set_yticks(y); ax.set_yticklabels([SHORT[s] for s in stacks], fontsize=7); ax.invert_yaxis()
    ax.set_xlim(0, 1.12); ax.set_xlabel("Fraction of the day, Abu Dhabi")
    ax.set_title("Time coverage at the site (utility wells, outdoor)", loc="left", fontsize=10, pad=22)
    ax.legend(fontsize=6.8, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
    _save(fig, out, "fig05_time_coverage"); made.append("fig05_time_coverage")

    # 6 interference ---------------------------------------------------------------
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 3.3))
    satlab = {"smallsat_patch": ("5 dBi patch (IoT-only baseline)", "#eb6834"),
              "smallsat_deployable": ("12 dBi deployable", "#6250d6"),
              "d2d_array_64m2": ("64 m² array (if it listened in ISM)", "#52514e")}
    src = R.get("ism_by_satellite") or {"smallsat_patch": R["interference"]["ism"]["IO-ISM-LRFHSS"]}
    for sat, rows in src.items():
        lab, c = satlab[sat]
        axs[0].plot([r["density_km2"] for r in rows], [r["noise_rise_db"] for r in rows], color=c,
                    marker="o", ms=3, label=lab)
    for x, t in ((1e-4, "low"), (1e-3, "medium"), (1e-2, "high")):
        axs[0].axvline(x, color=GRID, lw=1.0, zorder=0)
        axs[0].text(x, axs[0].get_ylim()[1] * 0.97, t, fontsize=6.5, color=INK2, ha="center", va="top")
    axs[0].set_xscale("log"); axs[0].set_xlabel("Active ISM transmitters per km² (footprint mean)")
    axs[0].set_ylabel("Noise rise at satellite (dB)"); axs[0].set_title("ISM 862-870 MHz, by satellite antenna", loc="left", fontsize=9)
    axs[0].legend(fontsize=6.3, loc="upper left", bbox_to_anchor=(0.0, 0.9))
    for s, rows in R["interference"]["tn_cochannel"].items():
        axs[1].plot([r["density_km2"] for r in rows], [r["noise_rise_db"] for r in rows], color=COL[s],
                    marker="o", ms=3, label=SHORT[s])
    axs[1].set_xscale("log"); axs[1].set_xlabel("Active co-channel terrestrial UEs per km²")
    axs[1].set_title("Operator band, co-channel TN", loc="left", fontsize=9.5); axs[1].legend(fontsize=6.5)
    axs[1].set_ylabel("Noise rise at satellite (dB)")
    fig.suptitle("Uplink interference: noise rise versus emitter density", x=0.01, y=1.03, ha="left", fontsize=10)
    _save(fig, out, "fig06_interference"); made.append("fig06_interference")

    # 7 throughput -------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s in MAIN:
        rows = R["throughput_vs_elevation"][s]
        ax.plot([r["el"] for r in rows], [max(r["rate_bps"], 1) for r in rows], color=COL[s], ls=_ls(s), label=SHORT[s])
    ax.set_yscale("log"); ax.set_ylim(80, 1e6)
    ax.set_xlabel("Elevation angle (deg)"); ax.set_ylabel("Per-device information rate (bit/s, log)")
    ax.set_title("Per-device throughput versus elevation (0 = link does not close)", loc="left", fontsize=10)
    ax.legend(fontsize=6.6, loc="center left", bbox_to_anchor=(1.01, 0.5))
    _save(fig, out, "fig07_throughput"); made.append("fig07_throughput")

    # 8 goodput vs load ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s in MAIN + CONTROL:
        rows = [r for r in R["goodput"][s] if r["devices_per_cell"] > 0]
        ax.plot([r["devices_per_cell"] for r in rows], [max(r["goodput_bps"], 1e-3) for r in rows],
                color=COL[s], ls=_ls(s), label=SHORT[s])
    ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(1e-2, None)
    ax.set_xlabel("Devices per cell (log)"); ax.set_ylabel("Delivered goodput per cell (bit/s, log)")
    xs = [r["devices_per_cell"] for st in MAIN + CONTROL for r in R["goodput"][st] if r["goodput_bps"] > 1e-2]
    ax.set_xlim(min(xs) / 2, max(xs) * 3)
    ax.set_title("Goodput versus load (utility wells traffic, 20 B per hour)", loc="left", fontsize=10)
    ax.legend(fontsize=6.6, loc="center left", bbox_to_anchor=(1.01, 0.5))
    _save(fig, out, "fig08_goodput"); made.append("fig08_goodput")

    # 9 capacity ---------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    cap = R["capacity"]["utility_wells"]
    for off, key, hatch, lab in ((-0.18, "service", None, "Service capacity: >= 90 % delivered within deadline"),
                                 (0.18, "contention", "////", "Contention capacity: <= 10 % collision/blocking (conditional)")):
        for v, s_ in zip(y, stacks):
            c = cap[s_][key]
            val = c.get("devices_per_km2") or 0
            if val > 0:
                if c.get("devices_per_km2_ci95"):
                    lo, hi = c["devices_per_km2_ci95"]
                else:
                    lo, hi = c.get("devices_per_km2_min") or val, c.get("devices_per_km2_max") or val
                ax.barh(v + off, val, height=0.34, color=COL[s_], hatch=hatch, edgecolor="white", lw=0,
                        label=lab if v == 0 else None)
                ax.errorbar(val, v + off, xerr=[[val - lo], [hi - val]], fmt="none", ecolor=INK, lw=0.8, capsize=2)
                txt = f"{val:,.0f}" if val >= 10 else f"{val:.2g}"
                ax.text(hi * 1.2, v + off, txt + (" (>=)" if "not reached" in c.get("note", "") else ""),
                        va="center", fontsize=6)
            elif key == "service":
                ct = cap[s_]["contention"]
                xr = (ct.get("devices_per_km2_max") or ct.get("devices_per_km2") or 1e-6) * 25
                ax.text(xr, v, "service: infeasible (< 90 % on time unloaded)", va="center", fontsize=5.8, color=INK2)
    ax.set_xscale("log"); ax.set_xlim(1e-6, None)
    ax.set_yticks(y); ax.set_yticklabels([SHORT[s] for s in stacks], fontsize=7); ax.invert_yaxis()
    ax.set_xlabel("Devices per km² (log; service: mean of 10 replications, whisker 95 % CI; contention: 3, min-max)")
    ax.set_title("Area capacity (utility wells traffic)", loc="left", fontsize=10, pad=34)
    ax.legend(fontsize=6.5, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=1)
    _save(fig, out, "fig09_capacity"); made.append("fig09_capacity")

    # 10/11 scenario heatmaps ---------------------------------------------------------------
    scens = list(R["scenario_matrix"].keys())
    for key, title, name, fmt, vmax in (("pdr_deadline", "Delivered within deadline", "fig10_pdr_matrix", "{:.0%}", 1.0),
                                         ("battery_years", "Battery life (years, 5.2 Ah)", "fig11_battery_matrix", "{:.1f}", None)):
        M = [[R["scenario_matrix"][sc][s][key] for sc in scens] for s in stacks]
        vm = vmax or max(max(r) for r in M)
        fig, ax = plt.subplots(figsize=(6.4, 3.8))
        im = ax.imshow(M, cmap="Blues", vmin=0, vmax=vm, aspect="auto")
        for i, row in enumerate(M):
            for j, v in enumerate(row):
                ax.text(j, i, fmt.format(v), ha="center", va="center", fontsize=7,
                        color="white" if v > 0.6 * vm else INK)
        ax.set_xticks(range(len(scens))); ax.set_xticklabels([SCEN_SHORT[s] for s in scens], fontsize=7.5)
        ax.set_yticks(range(len(stacks))); ax.set_yticklabels([SHORT[s] for s in stacks], fontsize=7)
        ax.grid(False); ax.set_title(title + " by stack and scenario", loc="left", fontsize=10)
        fig.colorbar(im, ax=ax, shrink=0.8)
        _save(fig, out, name); made.append(name)

    # 12 latency CDF -----------------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s in MAIN:
        lat = sorted(x for x in R["scenario_matrix"]["utility_wells"][s]["latencies"] if x is not None)
        n = len(R["scenario_matrix"]["utility_wells"][s]["latencies"])
        if lat:
            ax.step([x / 60 for x in lat], [(i + 1) / n for i in range(len(lat))], color=COL[s], ls=_ls(s), where="post", label=SHORT[s])
    ax.set_xscale("log"); ax.set_xlabel("Latency from generation to delivery (min, log)")
    ax.set_ylabel("Fraction of messages delivered"); ax.set_ylim(0, 1.02)
    ax.set_title("Latency distribution (utility wells; undelivered messages cap the curve)", loc="left", fontsize=10)
    ax.legend(fontsize=6.6, loc="center left", bbox_to_anchor=(1.01, 0.5))
    _save(fig, out, "fig12_latency_cdf"); made.append("fig12_latency_cdf")

    # 13 control: same satellite, same band -------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    for s in CONTROL:
        rows = [r for r in R["goodput"][s] if r["devices_per_cell"] > 0]
        ax.plot([r["devices_per_cell"] for r in rows], [r["pdr"] for r in rows], color=COL[s], ls=_ls(s),
                marker="o", ms=2.5, label=SHORT[s])
    ax.set_xscale("log"); ax.set_ylim(0, 1.02)
    ax.set_xlabel("Devices per cell (log)"); ax.set_ylabel("Uplink reception ratio")
    ax.set_title("Same band (847 MHz), same satellite, 22 dBm: two infrastructures", loc="left", fontsize=10)
    ax.legend(fontsize=6.5, loc="center left", bbox_to_anchor=(1.01, 0.5))
    _save(fig, out, "fig13_control_air_interface"); made.append("fig13_control_air_interface")
    # 15 spectral efficiency at service capacity --------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    cap = R["capacity"]["utility_wells"]
    sc_int = 3600.0
    names, vals, cols = [], [], []
    for s_ in stacks:
        sv = cap[s_]["service"]
        alloc = R["meta"]["presets"]["stacks"][s_].get("alloc_hz")
        n = (sv.get("devices_per_cell") or 0) * (sv.get("on_time_at_capacity") or 0)   # delivered, not offered (N12)
        names.append(SHORT[s_]); cols.append(COL[s_])
        vals.append(n / sc_int / (alloc / 1e6) if alloc else 0)
    yy = list(range(len(names)))
    ax.barh(yy, [max(v, 1e-6) for v in vals], color=cols, height=0.6)
    for v, x in zip(yy, vals):
        ax.text(max(x, 1e-6) * 1.15, v, (f"{x:,.2f}" if x >= 0.1 else (f"{x:.2g}" if x > 0 else "infeasible")),
                va="center", fontsize=6.5)
    ax.set_xscale("log"); ax.set_xlim(1e-6, None)
    ax.set_yticks(yy); ax.set_yticklabels(names, fontsize=7); ax.invert_yaxis()
    ax.set_xlabel("On-time messages per second per allocated MHz, per cell, at service capacity (log)")
    ax.set_title("Spectral efficiency at >= 90 % on-time delivery (utility wells)", loc="left", fontsize=10)
    _save(fig, out, "fig15_spectral_efficiency"); made.append("fig15_spectral_efficiency")

    # 16 technology x policy matrix --------------------------------------------------------------
    if "policy_matrix" in R:
        pm = R["policy_matrix"]
        fig, ax = plt.subplots(figsize=(6.4, 3.4))
        stk = []
        for row in pm:
            if row["stack"] not in stk:
                stk.append(row["stack"])
        yy = list(range(len(stk)))
        for off, pol, hatch in ((-0.18, "first_visible", None), (0.18, "elev_threshold", "////")):
            for v, s_ in zip(yy, stk):
                row = next(r for r in pm if r["stack"] == s_ and r["policy"] == pol)
                val = row["service_per_km2"] or 0
                lab = ("transmit when in coverage" if pol == "first_visible" else "wait for 30 deg") if v == 0 else None
                if val > 0:
                    ax.barh(v + off, val, height=0.34, color=COL[s_], hatch=hatch, edgecolor="white", lw=0, label=lab)
                    ci = row.get("service_ci95")
                    hi = val
                    if ci:
                        ax.errorbar(val, v + off, xerr=[[val - ci[0]], [ci[1] - val]], fmt="none", ecolor=INK,
                                    lw=0.8, capsize=2)
                        hi = ci[1]
                    ax.text(hi * 1.15, v + off, f"{val:,.2f}" if val >= 0.1 else f"{val:.2g}", va="center", fontsize=6)
                else:
                    ax.barh(v + off, 0, height=0.34, color=COL[s_], label=lab)
                    ax.text(0.02, v + off, "0: < 90 % on time even unloaded", va="center", fontsize=5.8, color=INK2,
                            transform=ax.get_yaxis_transform())
        ax.set_xscale("log"); ax.set_yticks(yy); ax.set_yticklabels([SHORT[s] for s in stk], fontsize=7)
        ax.invert_yaxis(); ax.set_xlabel("Service capacity, devices per km² (log; mean of 10 replications, 95 % CI)")
        ax.set_title("Controls under both transmit policies (utility wells)", loc="left", fontsize=10, pad=22)
        ax.legend(fontsize=6.5, loc="lower left", bbox_to_anchor=(0, 1.0), ncol=2)
        _save(fig, out, "fig16_policy_matrix"); made.append("fig16_policy_matrix")

    # 14 sensitivity -------------------------------------------------------------------------------
    if "sensitivity" in R:
        sens = R["sensitivity"]
        fig, axs = plt.subplots(1, 2, figsize=(7.6, 3.6), gridspec_kw=dict(width_ratios=[1.6, 1]))
        for ax, st in zip(axs, ("IO-ISM-LRFHSS", "OP-MSS-NBIOT")):
            if st not in sens:
                continue
            rows = sens[st]
            base = rows[0]["pdr_deadline"]
            yy = list(range(len(rows)))
            ax.barh(yy, [r["pdr_deadline"] for r in rows], color=[COL[st] if i else INK2 for i in range(len(rows))], height=0.6)
            ax.axvline(base, color=INK2, lw=0.8, ls=":")
            for i, r in enumerate(rows):
                ax.text(r["pdr_deadline"] + 0.01, i, f"{100 * r['pdr_deadline']:.0f} %", va="center", fontsize=6.5)
            ax.set_yticks(yy); ax.set_yticklabels([r["case"] for r in rows], fontsize=6.8); ax.invert_yaxis()
            ax.set_xlim(0, 1.1); ax.set_xlabel("Delivered within deadline")
            ax.set_title(SHORT[st], loc="left", fontsize=8.5)
        fig.suptitle("Sensitivity of delivery to modelling assumptions (utility wells; one change at a time)",
                     x=0.01, y=1.03, ha="left", fontsize=10)
        fig.tight_layout()
        _save(fig, out, "fig14_sensitivity"); made.append("fig14_sensitivity")
    return made
