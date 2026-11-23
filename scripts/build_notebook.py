"""Build the self-contained Colab notebook from the ntnsim package.
Run from the repository root: python3 scripts/build_notebook.py
"""
"""Builds the self-contained Colab notebook from the package sources."""
import json
import os

MODULES = ["rng", "geometry", "antenna", "channel", "phy", "nbiot", "interference", "access", "energy", "downlink",
           "economics", "presets", "engine", "analysis", "refsched", "report", "validate", "figures"]


def md(s):
    return dict(cell_type="markdown", metadata={}, source=s.strip("\n").splitlines(True))


def code(s, hidden=False):
    meta = {"cellView": "form"} if hidden else {}
    return dict(cell_type="code", metadata=meta, execution_count=None, outputs=[],
                source=s.strip("\n").splitlines(True))


cells = [md("""
# Operator 3GPP IoT-NTN vs IoT-only LoRaWAN NTN: LEO simulator (v1.6.0, frozen version used in the paper)

**What it compares.** The same IoT scenarios served by hypothetical architectures representing two business models (infrastructure scale, spectrum and technology are confounded in the main stacks; the control stacks and sensitivity analysis separate them):

* **Operator-led 3GPP IoT-NTN**: NB-IoT / LTE-M NTN with the operator's 800 MHz (B20) spectrum reused from large direct-to-device arrays, or via an MSS partner in L-band.
* **IoT-only / non-operator LoRaWAN NTN**: LR-FHSS or LoRa on small LEO satellites, in ISM 868 MHz (licence-exempt devices, non-protected satellite assignments) or licensed S-band.
* **Same-band control**: NB-IoT, LR-FHSS and LoRa on the same satellite, band and transmit power, so only the air interface differs.

**Comparison dimensions.** Path loss, itemised link budget, link margin, coverage probability, cell and service radius, time coverage at the site, interference (ISM noise rise, co-channel terrestrial UEs), per-device throughput, goodput versus load, capacity per cell and per km², delivery within deadline, latency, energy per message and battery life, plus a sensitivity analysis.

**Two delivery metrics.** `pdr_deadline` is uplink reception at the satellite (transparent payload: at the gateway); for 3GPP stacks the random-access response, every uplink grant and the final message are downlink messages that gate it. `pdr_confirmed_deadline` also requires the acknowledgement before the deadline (LoRaWAN: confirmed mode with RX1/RX2 windows, duty cycle and half-duplex gateway). Ground-segment availability is not modelled.

**Read before using results.** Satellite and constellation presets are *illustrative classes*, not a specific operator's design. ISM activity levels, Doppler tolerances, LR-FHSS SNR thresholds and device current profiles are *assumptions* exposed as parameters. NB-IoT/LTE-M Eb/N0 and floor rates are *back-solved* to the 3GPP MCL targets. TR 38.811 clutter tables are S-band values applied at sub-GHz (extrapolation). Economic prices are left empty on purpose. Nothing here is a measurement.

Run the cells top to bottom. The first cell writes the `ntnsim` package (pure Python standard library; matplotlib only for figures).
""")]

src = ""
for m in MODULES:
    src += f"%%writefile ntnsim/{m}.py\n" if False else ""
cells.append(code("import os\nos.makedirs('ntnsim', exist_ok=True)\nopen('ntnsim/__init__.py','w').close()\nprint('package folder ready')"))
for m in MODULES:
    body = open(os.path.join("ntnsim", m + ".py")).read()
    cells.append(code(f"%%writefile ntnsim/{m}.py\n" + body, hidden=True))

cells += [
    md("## 1. Validation against independent references"),
    code("""
import pandas as pd
from ntnsim import validate
v = pd.DataFrame(validate.run(log=lambda *a: None))
print(f"{v.passed.sum()} of {len(v)} checks pass")
v
"""),
    md("## 2. One case: pick a stack and scenario, change any assumption"),
    code("""
#@title Case configuration { run: "auto" }
stack = "IO-ISM-LRFHSS" #@param ["OP-LB-NBIOT","OP-LB-LTEM","OP-MSS-NBIOT","IO-ISM-LRFHSS","IO-ISM-LORA-SF10","IO-ISM-LORA-SF12","IO-SBAND-LRFHSS","IO-SBAND-LRFHSS-HP","CTRL-NBIOT","CTRL-LRFHSS","CTRL-LORA-SF12","CTRL-SS-NBIOT","CTRL-SS-LRFHSS","CTRL-SS-LORA-SF12"]
scenario = "utility_wells" #@param ["utility_wells","agri_water","logistics","disaster_urban"]
satellite = "(preset)" #@param ["(preset)","smallsat_patch","smallsat_deployable","d2d_array_64m2","d2d_array_223m2"]
constellation = "(preset)" #@param ["(preset)","iot_sparse","iot_dense","mss_mid","d2d_60","d2d_120"]
device_tx_dbm = -1 #@param {type:"slider", min:-1, max:23, step:1}
ism_activity = "(preset)" #@param ["(preset)","off","low","medium","high"]
tn_coexistence = "(preset)" #@param ["(preset)","dedicated","cochannel"]
pol_loss_db = 3.0 #@param {type:"slider", min:0, max:3, step:0.5}
tx_policy = "elev_threshold" #@param ["first_visible","elev_threshold","best_in_pass"]
tx_min_elev_deg = 30 #@param {type:"slider", min:10, max:60, step:5}
sidelobe_model = "airy" #@param ["airy","s1528"]
serving = "sticky" #@param ["sticky","best"]
traffic_model = "event" #@param ["event","fluid"]
nbiot_model = "tables" #@param ["tables","continuous"]
nbiot_calibration = "hardware" #@param ["hardware","link_level"]
nbiot_objective = "resource" #@param ["resource","airtime"]
lrfhss_model = "packet" #@param ["packet","marginal"]
angle_mode = "interp" #@param ["interp","nearest"]
beams_per_sat = 0 #@param {type:"integer"}
load_scale = 1.0 #@param {type:"number"}
n_mc = 3000 #@param {type:"integer"}

so = {}
if satellite != "(preset)": so["sat"] = satellite
if constellation != "(preset)": so["const"] = constellation
if device_tx_dbm >= 0: so["ptx_dbm"] = float(device_tx_dbm)
if ism_activity != "(preset)": so["ism"] = ism_activity
if tn_coexistence != "(preset)": so["coexistence"] = tn_coexistence
go = dict(pol_loss_db=pol_loss_db, tx_min_elev_deg=tx_min_elev_deg, n_mc=n_mc,
          sidelobe_model=sidelobe_model, serving=serving, traffic_model=traffic_model, nbiot_model=nbiot_model,
          nbiot_calibration=nbiot_calibration, nbiot_objective=nbiot_objective, lrfhss_model=lrfhss_model,
          angle_mode=angle_mode)
so["tx_policy"] = tx_policy
if beams_per_sat > 0: so["beams_per_sat"] = beams_per_sat
sco = dict(load_scale=load_scale)

from ntnsim import engine, analysis as AN
r = engine.run_case(stack, scenario, stack_over=so, scen_over=sco, g_over=go)
keys = ["label","f_mhz","payload","delivery_basis","pdr","pdr_ci95","pdr_deadline","pdr_deadline_ci95",
        "latency_p50_s","latency_p95_s","energy_per_msg_j","energy_per_on_time_j","battery_years","battery_limited_by",
        "devices_in_cell_at_45","noise_rise_db_at_45","mean_tx_elev_deg","median_cn0_dbhz"]
display(pd.Series({k: r[k] for k in keys}, name=stack).to_frame())
print("Loss causes:", {k: round(v,3) for k,v in r["causes"].items() if v})
print("Coverage:", {k: round(v,3) for k,v in r["coverage"].items()})
print("Antenna:", r["antenna"])
"""),
    code("""
#@title Itemised link budget at one elevation
elevation_deg = 30 #@param {type:"slider", min:10, max:90, step:5}
lb = AN.link_budget(stack, scenario, elevation_deg, stack_over=so, scen_over=sco, g_over=go)
display(pd.DataFrame(lb["rows"], columns=["item","value","unit"]).round(2))
print(f"MAPL {lb['mapl_db']:.1f} dB   MCL {lb['mcl_db']:.1f} dB   margin {lb['margin_db']:.1f} dB")
print(AN.cell_radius(stack, scenario, stack_over=so, scen_over=sco, g_over=go))
print(AN.time_coverage(stack, scenario, stack_over=so, scen_over=sco, g_over=go))
"""),
    md("## 3. All stacks, one scenario"),
    code("""
#@title Comparison table
scenario_cmp = "utility_wells" #@param ["utility_wells","agri_water","logistics","disaster_urban"]
from ntnsim import report
rows = []
for s in report.ALL:
    r = engine.run_case(s, scenario_cmp, g_over=dict(n_mc=1500))
    cr = AN.cell_radius(s, scenario_cmp)
    rows.append(dict(stack=s, model=r["model"], f_MHz=r["f_mhz"], coverage=r["coverage"]["coverage_fraction"],
                     cell_radius_km=cr["cell_radius_km"], devices_in_cell=r["devices_in_cell_at_45"],
                     pdr_deadline=r["pdr_deadline"], latency_p50_s=r["latency_p50_s"],
                     energy_J=r["energy_per_msg_j"], battery_y=r["battery_years"], noise_rise_dB=r["noise_rise_db_at_45"]))
pd.DataFrame(rows).round(3)
"""),
    md("## 4. Full batch run\nRuns every comparison dimension for every stack and scenario (n_mc = 3000). Service capacity in the reference scenario uses 10 independent replications of the whole estimation (mean and Student-t 95 % interval, on-time re-estimated at that load, monotonicity check); other scenarios use 3 replications (min-max only). The technology x policy matrix uses 10 replications with seed-paired ratios, and the chronological reference scheduler is compared with the engine queue. A full recomputation takes about 2 hours and about 3 GB of memory, with checkpoints in out/ckpt so an interrupted run resumes. By default (`use_frozen = True`) the notebook loads the frozen paper results produced by this exact code; set it to False to recompute. Set `quick=True` for a 1-minute smoke run."),
    code("""
quick = False #@param {type:"boolean"}
use_frozen = True #@param {type:"boolean"}
import time, os, json, shutil
t0 = time.time()
if use_frozen and os.path.exists("frozen/results.json"):
    # paper version: load the frozen batch results produced by exactly this code (run_v15.py);
    # set use_frozen = False to recompute everything (about 2 hours, about 3 GB memory)
    os.makedirs("out", exist_ok=True)
    shutil.copy("frozen/results.json", "out/results.json")
    R = json.load(open("out/results.json"))
    report._csv(R, "out")
    print("loaded frozen results, model version", R["scenario_matrix"]["utility_wells"]["OP-LB-NBIOT"]["model_version"])
else:
    report.CKPT_DIR = "out/ckpt"
    R = report.run_all(out_dir="out", cache_dir="out/cache", n_mc=800 if quick else 3000, quick=quick,
                       log=lambda *a: None)
if os.path.exists("results_v1/results.json"):
    report.compare_with_v1(R, "results_v1/results.json", "out", "change_vs_v1.csv")
if os.path.exists("results_v1_2/results.json"):
    report.compare_with_v1(R, "results_v1_2/results.json", "out", "change_vs_v1_2.csv")
if os.path.exists("results_v1_3/results.json"):
    report.compare_with_v1(R, "results_v1_3/results.json", "out", "change_vs_v1_3.csv")
if os.path.exists("results_v1_4/results.json"):
    report.compare_with_v1(R, "results_v1_4/results.json", "out", "change_vs_v1_4.csv")
from ntnsim import figures
made = figures.make_all("out/results.json", "out/figs")
print(f"batch finished in {time.time()-t0:.0f} s; {len(made)} figures written to out/figs")
"""),
    md("""## 5. Results
All numbers below are simulated outputs of the model and its stated assumptions, for a device site at Abu Dhabi. They are not measurements."""),
    md("### 5.1 Delivered within deadline, latency and battery: all stacks x all scenarios"),
    code("""
import json, pandas as pd
R = json.load(open("out/results.json"))
SM = R["scenario_matrix"]
scens = list(SM)
def mat(key, fmt=None):
    df = pd.DataFrame({sc: {s: SM[sc][s][key] for s in SM[sc]} for sc in scens})
    return df
print("Uplink reception within deadline (fraction)"); display(mat("pdr_deadline").round(3))
print("95 % Wilson interval, on-time fraction")
display(pd.DataFrame({sc: {s: "[%.3f, %.3f]" % tuple(SM[sc][s]["pdr_deadline_ci95"]) for s in SM[sc]} for sc in scens}))
print("Uplink reception at any time (fraction)"); display(mat("pdr").round(3))
print("Median latency (s)"); display(mat("latency_p50_s").round(0))
print("95th percentile latency (s)"); display(mat("latency_p95_s").round(0))
print("Energy per message (J)"); display(mat("energy_per_msg_j").round(3))
print("Battery life, 5.2 Ah, capped at 15-year calendar life (years)"); display(mat("battery_years").round(1))
print("Battery limited by"); display(mat("battery_limited_by"))
print("Devices competing in one cell at 45 deg"); display(mat("devices_in_cell_at_45").round(1))
"""),
    md("### 5.2 Loss causes per case (fraction of messages)"),
    code("""
rows = []
for sc in scens:
    for s, r in SM[sc].items():
        rows.append(dict(scenario=sc, stack=s, **{k: round(v, 3) for k, v in r["causes"].items()}))
pd.DataFrame(rows)
"""),
    md("### 5.3 Link budgets (median, LOS, utility wells) at 10, 30, 60 and 90 degrees"),
    code("""
LB = {s: {int(k): v for k, v in d.items()} for s, d in R["link_budget"].items()}
for el in (10, 30, 60, 90):
    names = [r[0] + " [" + r[2] + "]" for r in LB["OP-LB-NBIOT"][el]["rows"]]
    df = pd.DataFrame({s: [r[1] for r in LB[s][el]["rows"]] for s in LB}, index=names)
    df.loc["MAPL [dB]"] = [LB[s][el]["mapl_db"] for s in LB]
    df.loc["MCL [dB]"] = [LB[s][el]["mcl_db"] for s in LB]
    print(f"Elevation {el} deg"); display(df.round(2))
"""),
    md("### 5.4 Coverage: cell radius, service radius and time coverage (all scenarios)"),
    code("""
rows = []
for sc in scens:
    for s in SM[sc]:
        cr, tc = R["cell_radius"][sc][s], R["time_coverage"][sc][s]
        rows.append(dict(scenario=sc, stack=s, cell_radius_km=cr.get("cell_radius_km"),
                         service_radius_km=cr.get("service_radius_km"), min_link_elev_deg=cr.get("el_min_link_deg"),
                         satellite_in_view=tc["geometric_coverage"], link_closes_90pct=tc["link_coverage"],
                         mean_gap_s=tc["mean_gap_s"], max_gap_s=tc["max_gap_s"]))
pd.DataFrame(rows).round(3)
"""),
    md("### 5.5 Capacity (reference scenario: mean of 10 replications with 95 % CI; others: mean of 3 with min-max)\n**Service capacity**: largest devices per cell with >= 90 % uplink reception within deadline, counting every failure; 0 = infeasible. **Contention capacity**: largest devices per cell with collision + blocking <= 10 % among link-feasible messages (conditional)."),
    code("""
rows = []
for sc, d in R["capacity"].items():
    for s, c in d.items():
        sv, ct = c["service"], c.get("contention", {})
        rows.append(dict(scenario=sc, stack=s, cell_area_km2=sv.get("cell_area_km2"),
                         service_per_km2=sv.get("devices_per_km2"), service_seed_min=sv.get("devices_per_km2_min"),
                         service_seed_max=sv.get("devices_per_km2_max"), service_ci95=sv.get("devices_per_km2_ci95"),
                         on_time_at_capacity=sv.get("on_time_at_capacity"),
                         monotone=(sv.get("monotonicity_check") or {}).get("monotone"), service_note=sv.get("note"),
                         contention_per_km2=ct.get("devices_per_km2"), contention_note=ct.get("note")))
pd.DataFrame(rows)
"""),
    md("### 5.6 Throughput: per-device information rate versus elevation (bit/s, 0 = link does not close)"),
    code("""
T = R["throughput_vs_elevation"]
pd.DataFrame({s: {r["el"]: r["rate_bps"] for r in rows} for s, rows in T.items()}).round(0)
"""),
    md("### 5.7 Goodput versus load (utility wells)"),
    code("""
rows = []
for s, lst in R["goodput"].items():
    for g in lst:
        rows.append(dict(stack=s, devices_per_cell=g["devices_per_cell"], pdr=g["pdr"],
                         goodput_bps=g["goodput_bps"], contention_loss=g["contention_loss"]))
gp = pd.DataFrame(rows)
display(gp.pivot_table(index="devices_per_cell", columns="stack", values="pdr").round(3))
"""),
    md("### 5.8 Interference"),
    code("""
I = R["interference"]
print("ISM noise rise (dB) by satellite antenna vs active ISM transmitters per km2")
display(pd.DataFrame({sat: {r["density_km2"]: r["noise_rise_db"] for r in rows} for sat, rows in R["ism_by_satellite"].items()}).round(2))
print("Co-channel terrestrial UE noise rise (dB) vs active UEs per km2")
display(pd.DataFrame({s: {r["density_km2"]: r["noise_rise_db"] for r in rows} for s, rows in I["tn_cochannel"].items()}).round(2))
print("Delivery ratio vs ISM activity level (utility wells)")
display(pd.DataFrame(I["ism_pdr"]).round(3))
print("Operator NB-IoT delivery: dedicated carrier vs co-channel with terrestrial network")
display(pd.DataFrame(I["tn_coexistence_pdr"]).round(3))
"""),
    md("### 5.9 Sensitivity (utility wells, one assumption changed at a time)"),
    code("""
for s, rows in R["sensitivity"].items():
    print(s); display(pd.DataFrame(rows).round(3))
"""),
    md("### 5.10 Figures"),
]
caps = [("fig01_path_loss", "Path loss versus elevation per band and altitude."),
        ("fig02_link_margin", "Uplink margin versus elevation (LOS median)."),
        ("fig03_coverage_probability", "Probability the link closes versus elevation."),
        ("fig04_cell_radius", "Cell radius and satellite service radius."),
        ("fig05_time_coverage", "Fraction of the day a satellite is in view and the link closes."),
        ("fig06_interference", "Noise rise from ISM devices and from co-channel terrestrial UEs."),
        ("fig07_throughput", "Per-device information rate versus elevation."),
        ("fig08_goodput", "Delivered goodput per cell versus load."),
        ("fig09_capacity", "Service capacity (mean of 10 replications, 95 % CI) and contention capacity."),
        ("fig10_pdr_matrix", "Delivered within deadline, stack x scenario."),
        ("fig11_battery_matrix", "Battery life, stack x scenario."),
        ("fig12_latency_cdf", "Latency distribution."),
        ("fig13_control_air_interface", "Same satellite, band and power: air interface only."),
        ("fig14_sensitivity", "Sensitivity of delivery to assumptions."),
        ("fig15_spectral_efficiency", "Delivered on-time messages per second per allocated MHz at service capacity."),
        ("fig16_policy_matrix", "Service capacity of the controls under both transmit policies (10 replications, 95 % CI).")]
for name, cap in caps:
    cells.append(md(f"**{name}.** {cap}"))
    cells.append(code(f'from IPython.display import Image\nImage("out/figs/{name}.png", width=900)'))
cells += [
    md("### 5.11 Spectral efficiency and equal-infrastructure controls"),
    code("""
rows = []
for s in SM["utility_wells"]:
    r = SM["utility_wells"][s]; sv = R["capacity"]["utility_wells"][s]["service"]
    a = r.get("alloc_hz")
    rows.append(dict(stack=s, alloc_kHz=(a or 0) / 1e3, on_time=r["pdr_deadline"],
                     service_capacity_per_cell=sv.get("devices_per_cell"),
                     on_time_at_capacity=sv.get("on_time_at_capacity"),
                     on_time_msgs_per_s_per_MHz_at_capacity=(sv.get("devices_per_cell") or 0) * (sv.get("on_time_at_capacity") or 0) / 3600 / (a / 1e6) if a else None))
pd.DataFrame(rows).round(4)
"""),
    md("### 5.12 Technology x transmit policy (controls) and orbital phase"),
    code("""
display(pd.DataFrame(R["policy_matrix"]).round(4))
print("Seed-paired capacity ratios (NB-IoT / LR-FHSS) under matched transmit policy")
display(pd.DataFrame(R["policy_ratios"]))
print("On-time fraction by arrival window (orbital phase; overlapping windows, a sensitivity), utility wells")
display(pd.DataFrame(R["orbital_phase"]).round(3))
"""),
    md("### 5.13 Exploratory chronological scheduler comparison (operator NB-IoT)\nNot a validation of the engine queue: the reference runs deadline-aware FIFO or smallest-cost priority without the engine's admission, and counts scheduling completions only (PHY failures excluded). Reported as a policy comparison; matched validation is an open item. The LR-FHSS approximation check near the 200-packet switch follows."),
    code("""
rows = []
for x in R["reference_scheduler"]:
    rows.append(dict(scenario=x["scenario"], load_scale=round(x["load_scale"], 1), admission=x["admission"],
                     calibration=x["calibration"], reference_policy=x["reference_policy"], requests=x["requests"],
                     ref_served=x["reference"]["served_fraction"],
                     ref_served_device_weighted=x["reference"]["served_fraction_device_weighted"],
                     engine_served=x["engine"]["served_fraction"], ref_mean_wait_s=x["reference"]["mean_wait_s"],
                     engine_mean_wait_s=x["engine"]["mean_wait_s"], ref_utilisation=x["reference"]["utilisation"],
                     engine_rho_max=x["engine"]["rho_max"]))
display(pd.DataFrame(rows).round(4))
print("LR-FHSS element-level approximation vs enumeration near the 200-packet switch")
pd.DataFrame(R["lrfhss_branch_boundary"]).round(4)
"""),
    md("### 5.13b Monte Carlo convergence of service capacity"),
    code("""
pd.DataFrame({s: {c["n_mc"]: c["devices_per_km2"] for c in rows} for s, rows in R["convergence"].items()}).round(3)
"""),
    md("### 5.14 Change against previous versions"),
    code("""
import os
for f in ("out/change_vs_v1.csv", "out/change_vs_v1_2.csv", "out/change_vs_v1_3.csv", "out/change_vs_v1_4.csv"):
    if os.path.exists(f):
        print(f); display(pd.read_csv(f))
    else:
        print(f, "not available in this runtime (previous results ship in the package)")
"""),
    md("### 5.15 Parameter provenance"),
    code("""
pd.DataFrame(list(R["meta"]["param_sources"].items()), columns=["parameter", "source or status"])
"""),
    code("""
#@title Download results (JSON, CSV, figures)
import shutil
shutil.make_archive("ntnsim_results", "zip", "out")
try:
    from google.colab import files
    files.download("ntnsim_results.zip")
except ImportError:
    print("ntnsim_results.zip written")
"""),
]

nb = dict(cells=cells, metadata=dict(kernelspec=dict(name="python3", display_name="Python 3"),
                                     language_info=dict(name="python"), colab=dict(provenance=[])),
          nbformat=4, nbformat_minor=5)
os.makedirs("dist", exist_ok=True)
with open("NTN_IoT_Operator_vs_LoRaWAN_Simulator_unexecuted.ipynb", "w") as f:
    json.dump(nb, f, indent=1)
print("notebook cells:", len(cells))
