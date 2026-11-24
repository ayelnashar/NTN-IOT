"""Journal-format figures of the paper (IEEE two-column), drawn from frozen/results.json.
Run from the repository root: python3 scripts/paper_figures.py

Single-column figures are 3.4 in wide (IEEE two-column layout), multi-panel
figures are stacked vertically, and every axes is a closed box.
"""
import json
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, os.getcwd())
from ntnsim.figures import COL, MAIN, CONTROL, _ls  # noqa: E402

R = json.load(open(os.environ.get("NTN_RESULTS", "frozen/results.json")))
OUT = "frozen/paper_figs"
os.makedirs(OUT, exist_ok=True)
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
W1 = 3.4
STACKS = MAIN + CONTROL
SCEN = {"utility_wells": "Wells", "agri_water": "Agri/water", "logistics": "Logistics", "disaster_urban": "Disaster"}

plt.rcParams.update({
    "font.size": 7, "axes.titlesize": 7, "axes.labelsize": 7, "xtick.labelsize": 6.5, "ytick.labelsize": 6.5,
    "axes.edgecolor": INK, "axes.linewidth": 0.7, "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK,
    "axes.spines.top": True, "axes.spines.right": True, "xtick.direction": "in", "ytick.direction": "in",
    "xtick.top": True, "ytick.right": True, "xtick.major.width": 0.6, "ytick.major.width": 0.6,
    "xtick.minor.width": 0.4, "ytick.minor.width": 0.4,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "legend.frameon": True, "legend.edgecolor": INK2, "legend.fancybox": False, "legend.framealpha": 1.0,
    "legend.fontsize": 5.8, "legend.borderpad": 0.4, "legend.handlelength": 2.2, "legend.columnspacing": 1.0,
    "lines.linewidth": 1.2, "figure.dpi": 150, "savefig.bbox": "tight", "savefig.pad_inches": 0.02})


def save(fig, name):
    fig.savefig(os.path.join(OUT, name + ".png"), dpi=400)
    fig.savefig(os.path.join(OUT, name + ".pdf"))
    plt.close(fig)


def legend_below(ax, ncol=2, y=-0.22):
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, y), ncol=ncol)


def legend_under(fig, ax, ncol=2, handles=None, labels=None):
    """One-line legend centered under the whole figure, outside every axes box."""
    h, l = (handles, labels) if handles is not None else ax.get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=ncol, borderaxespad=0.2,
               handlelength=1.6, columnspacing=1.2)


def legend_above(ax, ncol=2):
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.02), ncol=ncol, borderaxespad=0)


# margin -------------------------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(W1, 2.2))
for s in MAIN:
    cc = R["coverage_curve"]["utility_wells"][s]
    ax.plot([c["el"] for c in cc], [c["margin_los_db"] for c in cc], color=COL[s], ls=_ls(s), label=s)
ax.axhline(0, color=INK2, lw=0.7)
ax.set_xlim(10, 90)
ax.set_xlabel("Elevation angle (deg)"); ax.set_ylabel("Uplink margin, LOS median (dB)")
legend_below(ax, y=-0.24)
save(fig, "p_margin")

# time coverage -------------------------------------------------------------------------------------
y = list(range(len(STACKS)))
fig, ax = plt.subplots(figsize=(W1, 3.0))
geo = [R["time_coverage"]["utility_wells"][s]["geometric_coverage"] for s in STACKS]
lnk = [R["time_coverage"]["utility_wells"][s]["link_coverage"] for s in STACKS]
ax.barh([v - 0.2 for v in y], geo, height=0.38, color="#b9b8b2", label="Satellite in view")
ax.barh([v + 0.2 for v in y], lnk, height=0.38, color=[COL[s] for s in STACKS], label="Link closes (90%)")
for v, r in zip(y, lnk):
    ax.text(r + 0.012, v + 0.2, f"{100 * r:.0f}%", va="center", fontsize=5.5)
ax.set_yticks(y); ax.set_yticklabels(STACKS, fontsize=5.8); ax.invert_yaxis()
ax.set_xlim(0, 1.12); ax.set_xlabel("Fraction of the day"); ax.grid(axis="y", visible=False)
ax.tick_params(axis="y", which="both", right=False)
fig.tight_layout()
legend_under(fig, ax)
save(fig, "p_tcov")


# heatmaps ------------------------------------------------------------------------------------------
def heat(key, fmt, vmax, name, cbar):
    scens = list(R["scenario_matrix"].keys())
    M = [[R["scenario_matrix"][sc][s][key] for sc in scens] for s in STACKS]
    vm = vmax or max(max(r) for r in M)
    fig, ax = plt.subplots(figsize=(W1, 3.1))
    im = ax.imshow(M, cmap="Blues", vmin=0, vmax=vm, aspect="auto")
    for i, row in enumerate(M):
        for j, v in enumerate(row):
            ax.text(j, i, fmt(v), ha="center", va="center", fontsize=5.6, color="white" if v > 0.6 * vm else INK)
    ax.set_xticks(range(len(scens))); ax.set_xticklabels([SCEN[s] for s in scens], fontsize=6.2)
    ax.set_yticks(range(len(STACKS))); ax.set_yticklabels(STACKS, fontsize=5.8)
    ax.tick_params(which="both", length=0, top=False, right=False)
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax, fraction=0.05, pad=0.03)
    cb.ax.tick_params(labelsize=5.8, direction="in"); cb.set_label(cbar, fontsize=6.2); cb.outline.set_linewidth(0.7)
    save(fig, name)


heat("pdr_deadline", lambda v: f"{100 * v:.0f}%", 1.0, "p_pdr", "Delivered within deadline")
heat("battery_years", lambda v: f"{v:.1f}", None, "p_battery", "Battery life (years)")

# latency ---------------------------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(W1, 2.2))
for s in MAIN:
    L = R["scenario_matrix"]["utility_wells"][s]["latencies"]
    lat = sorted(x for x in L if x is not None)
    if lat:
        ax.step([x / 60 for x in lat], [(i + 1) / len(L) for i in range(len(lat))], color=COL[s], ls=_ls(s),
                where="post", label=s)
ax.set_xscale("log"); ax.set_ylim(0, 1.02)
ax.set_xlabel("Latency from generation to delivery (min)"); ax.set_ylabel("Fraction of messages delivered")
legend_below(ax, y=-0.24)
save(fig, "p_latency")

# interference, stacked -------------------------------------------------------------------------------
fig, axs = plt.subplots(2, 1, figsize=(W1, 4.0))
satlab = {"smallsat_patch": ("5 dBi patch (baseline)", "#eb6834", "o"),
          "smallsat_deployable": ("12 dBi deployable", "#6250d6", "s"),
          "d2d_array_64m2": ("64 m² array", "#52514e", "^")}
src = R.get("ism_by_satellite") or {"smallsat_patch": R["interference"]["ism"]["IO-ISM-LRFHSS"]}
for sat, rows in src.items():
    lab, c, m = satlab[sat]
    axs[0].plot([r["density_km2"] for r in rows], [r["noise_rise_db"] for r in rows], color=c, marker=m, ms=2.8,
                mfc="white" if m != "o" else c, label=lab)
axs[0].set_xscale("log"); axs[0].set_xlabel("Active ISM transmitters per km²")
axs[0].set_ylabel("Noise rise at satellite (dB)")
yt = axs[0].get_ylim()[1]
for x, t in ((1e-4, "low"), (1e-3, "medium"), (1e-2, "high")):
    axs[0].axvline(x, color=INK2, lw=0.6, ls=":", zorder=0)
    axs[0].text(x * 1.12, yt * 0.97, t, fontsize=5.6, color=INK2, ha="left", va="top")
axs[0].legend(loc="lower right")
axs[0].set_title("(a) ISM 862–870 MHz", loc="left")
for s, rows in R["interference"]["tn_cochannel"].items():
    axs[1].plot([r["density_km2"] for r in rows], [r["noise_rise_db"] for r in rows], color=COL[s], marker="o",
                ms=2.8, label=s + (" (223 m² array)" if s == "OP-LB-NBIOT" else " (L-band smallsat, hypothetical)"))
axs[1].set_xscale("log"); axs[1].set_xlabel("Active co-channel terrestrial UEs per km²")
axs[1].set_ylabel("Noise rise at satellite (dB)"); axs[1].legend(loc="upper left")
axs[1].set_title("(b) Operator band, co-channel terrestrial network", loc="left")
fig.tight_layout(h_pad=1.0)
save(fig, "p_noise")

# capacity ----------------------------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(W1, 3.3))
cap = R["capacity"]["utility_wells"]
for off, key, hatch, lab in ((-0.2, "service", None, "Service capacity (≥ 90 % on time)"),
                             (0.2, "contention", "/////", "Contention capacity (≤ 10 % collision or blocking)")):
    first = True
    for v, s_ in zip(y, STACKS):
        c = cap[s_][key]
        val = c.get("devices_per_km2") or 0
        if val > 0:
            if c.get("devices_per_km2_ci95"):
                lo, hi = c["devices_per_km2_ci95"]
            else:
                lo, hi = c.get("devices_per_km2_min") or val, c.get("devices_per_km2_max") or val
            ax.barh(v + off, val, height=0.38, color=COL[s_], hatch=hatch, edgecolor="white", lw=0,
                    label=lab if first else None)
            first = False
            ax.errorbar(val, v + off, xerr=[[val - lo], [hi - val]], fmt="none", ecolor=INK, lw=0.6, capsize=1.5)
            txt = f"{val:,.1f}" if val >= 1 else f"{val:.2g}"
            if key == "contention" and not (cap[s_]["service"].get("devices_per_km2") or 0):
                txt += "  (service capacity 0)"
            ax.text(hi * 1.35, v + off, txt, va="center", fontsize=5.3)
ax.set_xscale("log"); ax.set_xlim(1e-6, 2e3)
ax.set_yticks(y); ax.set_yticklabels(STACKS, fontsize=5.8); ax.invert_yaxis()
ax.tick_params(axis="y", which="both", right=False); ax.grid(axis="y", visible=False)
ax.set_xlabel("Devices per km²")
legend_above(ax, ncol=1)
save(fig, "p_cap")

# cell radius ----------------------------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(W1, 3.0))
vals = [R["cell_radius"]["utility_wells"][s].get("cell_radius_km") or 0 for s in STACKS]
svc = [R["cell_radius"]["utility_wells"][s].get("service_radius_km") or 0 for s in STACKS]
ax.barh([v + 0.2 for v in y], vals, height=0.38, color=[COL[s] for s in STACKS], label="Cell radius (beam or footprint)")
ax.barh([v - 0.2 for v in y], svc, height=0.38, color="#b9b8b2", label="Service radius (link closes, 90%)")
for v, r in zip(y, vals):
    if r:
        ax.text(r * 1.1, v + 0.2, f"{r:.0f}" if r >= 10 else f"{r:.1f}", va="center", fontsize=5.3)
ax.set_xscale("log"); ax.set_xlim(2, 8e3)
ax.set_yticks(y); ax.set_yticklabels(STACKS, fontsize=5.8); ax.invert_yaxis()
ax.tick_params(axis="y", which="both", right=False); ax.grid(axis="y", visible=False)
ax.set_xlabel("Radius (km)")
fig.tight_layout()
h_, l_ = ax.get_legend_handles_labels()
legend_under(fig, ax, handles=h_[::-1], labels=l_[::-1])
save(fig, "p_radius")

# goodput ------------------------------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(W1, 2.4))
GP_MIN_DELIVERED = 10        # a point is plotted only if the Monte Carlo sample delivered at least this many messages
GP_N = R.get("goodput_n_mc", 1000)
fig, ax = plt.subplots(figsize=(W1, 2.4))
def gp_rows(s):
    """Points of one goodput curve up to the last load whose Monte Carlo sample still delivered at least
    GP_MIN_DELIVERED messages (or, for stacks that never do, at least one)."""
    rows = sorted((r for r in R["goodput"][s] if r["devices_per_cell"] > 0), key=lambda r: r["devices_per_cell"])
    cnt = [r["pdr"] * GP_N for r in rows]
    idx = [i for i, c in enumerate(cnt) if c >= GP_MIN_DELIVERED - 1e-9] or [i for i, c in enumerate(cnt) if c >= 1 - 1e-9]
    return [r for r in rows[:max(idx) + 1] if r["goodput_bps"] > 0] if idx else []


for s in STACKS:
    keep = gp_rows(s)
    ax.plot([r["devices_per_cell"] for r in keep], [r["goodput_bps"] for r in keep], color=COL[s],
            ls=_ls(s), lw=1.0, label=s)
    if keep and keep[-1]["devices_per_cell"] < max(r["devices_per_cell"] for r in R["goodput"][s]):
        # delivery falls below the resolution limit at the next load step
        ax.plot(keep[-1]["devices_per_cell"], keep[-1]["goodput_bps"], marker="v", ms=2.0, color=COL[s], ls="none")
xs = [r["devices_per_cell"] for st in STACKS for r in gp_rows(st)]
ax.set_xscale("log"); ax.set_yscale("log"); ax.set_ylim(1e-2, 3e4); ax.set_xlim(0.2, max(xs) * 2)
ax.set_xlabel("Devices per cell"); ax.set_ylabel("Delivered goodput per cell (bit/s)")
fig.tight_layout()
legend_under(fig, ax, ncol=3)
save(fig, "p_goodput")

# policy matrix --------------------------------------------------------------------------------------------
pm = R["policy_matrix"]
stk = []
for row in pm:
    if row["stack"] not in stk:
        stk.append(row["stack"])
yy = list(range(len(stk)))
fig, ax = plt.subplots(figsize=(W1, 2.0))
for off, pol, hatch, lab in ((-0.2, "first_visible", None, "Transmit at first visibility"),
                             (0.2, "elev_threshold", "/////", "Wait for 30° elevation")):
    first = True
    for v, s_ in zip(yy, stk):
        row = next(r for r in pm if r["stack"] == s_ and r["policy"] == pol)
        val = row["service_per_km2"] or 0
        if val > 0:
            ax.barh(v + off, val, height=0.38, color=COL[s_], hatch=hatch, edgecolor="white", lw=0,
                    label=lab if first else None)
            first = False
            ci = row.get("service_ci95"); hi = val
            if ci:
                ax.errorbar(val, v + off, xerr=[[val - ci[0]], [ci[1] - val]], fmt="none", ecolor=INK, lw=0.6, capsize=1.5)
                hi = ci[1]
            ax.text(hi * 1.3, v + off, f"{val:,.2f}" if val >= 0.1 else f"{val:.2g}", va="center", fontsize=5.3)
        elif pol == "first_visible":
            ax.text(1.3e-3, v, "0 under both policies (below 90% on time unloaded)", va="center", fontsize=5.3, color=INK2)
ax.set_xscale("log"); ax.set_xlim(1e-3, 1e2)
ax.set_yticks(yy); ax.set_yticklabels(stk, fontsize=5.8); ax.set_ylim(len(stk) - 0.5, -0.5)
ax.tick_params(axis="y", which="both", right=False); ax.grid(axis="y", visible=False)
ax.set_xlabel("Service capacity (devices per km²)")
fig.tight_layout()
legend_under(fig, ax)
save(fig, "p_policy")

# sensitivity, stacked ---------------------------------------------------------------------------------------
sens = R["sensitivity"]
n1, n2 = len(sens["IO-ISM-LRFHSS"]), len(sens["OP-MSS-NBIOT"])
fig, axs = plt.subplots(2, 1, figsize=(W1, 4.4), gridspec_kw=dict(height_ratios=[n1, n2]))
for ax, st, tag in zip(axs, ("IO-ISM-LRFHSS", "OP-MSS-NBIOT"), ("(a)", "(b)")):
    rows = sens[st]
    base = rows[0]["pdr_deadline"]
    ys = list(range(len(rows)))
    ax.barh(ys, [r["pdr_deadline"] for r in rows], color=[COL[st] if i else INK2 for i in range(len(rows))], height=0.6)
    ax.axvline(base, color=INK2, lw=0.7, ls=":")
    for i, r in enumerate(rows):
        ax.text(r["pdr_deadline"] + 0.012, i, f"{100 * r['pdr_deadline']:.0f}%", va="center", fontsize=5.3)
    ax.set_yticks(ys); ax.set_yticklabels([r["case"] for r in rows], fontsize=5.6); ax.invert_yaxis()
    ax.tick_params(axis="y", which="both", right=False); ax.grid(axis="y", visible=False)
    ax.set_xlim(0, 1.12); ax.set_title(f"{tag} {st}", loc="left")
axs[1].set_xlabel("Delivered within deadline")
fig.tight_layout(h_pad=0.8)
save(fig, "p_sens")
# downlink: uplink vs confirmed delivery, stacked panels --------------------------------------------
if "pdr_confirmed_deadline" in R["scenario_matrix"]["utility_wells"]["OP-LB-NBIOT"]:
    fig, axs = plt.subplots(2, 1, figsize=(W1, 5.4))
    for ax, sc, tag in zip(axs, ("utility_wells", "disaster_urban"), ("(a) Utility wells", "(b) Urban disaster")):
        M = R["scenario_matrix"][sc]
        ul = [M[s]["pdr_deadline"] for s in STACKS]
        cf = [M[s]["pdr_confirmed_deadline"] for s in STACKS]
        ax.barh([v - 0.2 for v in y], ul, height=0.38, color="#b9b8b2", label="Uplink delivery")
        ax.barh([v + 0.2 for v in y], cf, height=0.38, color=[COL[s] for s in STACKS],
                label="Confirmed delivery (acknowledgment received)")
        for v, a, b in zip(y, ul, cf):
            ax.text(max(a, b) + 0.015, v, f"{100 * a:.0f} / {100 * b:.0f}%", va="center", fontsize=5.2)
        ax.set_yticks(y); ax.set_yticklabels(STACKS, fontsize=5.8); ax.invert_yaxis()
        ax.tick_params(axis="y", which="both", right=False); ax.grid(axis="y", visible=False)
        ax.set_xlim(0, 1.25); ax.set_title(tag, loc="left")
    axs[1].set_xlabel("Messages delivered within the deadline")
    fig.tight_layout(h_pad=0.8)
    legend_under(fig, axs[0])
    save(fig, "p_dl")
print("done")
