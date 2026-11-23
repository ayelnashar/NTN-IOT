"""Simulation engine: one (stack, scenario) case -> KPI dictionary (v1.5).

Per Monte Carlo sample
  1. a message is generated at a random time in the arrival window (12-36 h of
     a 48 h orbit run, so earlier backlog and later contacts both exist); the
     device waits for the next contact and, by policy, for a minimum elevation;
  2. executed per-device schedules (Case.device_schedule, P01/P02): every
     device generates messages at its own phase; one persistent FIFO and
     next-free time per device carry across contacts (LoRa family: each
     message occupies the device for its copies and duty-cycle off-time);
     a transmission starts only at a policy-allowed step, inside a dwell of
     the cell's fixed beam calendar, and only if it fits in the contact,
     looping over opportunities until it fits or expires. A stratified grid
     of device schedules is computed once per configuration; the release
     profile (background traffic) and the Monte Carlo targets are drawn
     from the SAME executed schedules;
  3. path loss, allowances, satellite gain; noise plus aggregate interference;
  4. traffic seen by the cell at that time step comes from the event-driven
     release profile: every generation instant is mapped through the same
     transmit policy, expired messages are discarded, and the resulting
     transmissions are counted per time step (F08);
  5. access and link: LoRa ALOHA with capture; LR-FHSS packet-level hopping
     grids; NB-IoT NPUSCH from TS 36.213 TBS/RU/repetition tables with link
     adaptation, fading looks from airtime and HARQ (F07); RACH per CE level;
     scheduled capacity with admission control; symmetric frequency-offset and
     drift limits for all technologies (F15);
  6. latency and energy from one timeline; the transaction must fit inside the
     remaining contact; deadline check.

Reported delivery is UPLINK RECEPTION at the satellite (transparent payload:
at the gateway). Downlink, acknowledgements and ground-segment availability are
not modelled (ground_delay_s can add a store-and-forward wait).
"""
import hashlib
import json
import math
import os

from . import geometry as G
from . import channel as CH
from . import phy as P
from . import access as A
from . import energy as E
from . import interference as I
from . import nbiot as NB
from .antenna import SatAntenna
from .rng import Rng
from . import presets as PR

MODEL_VERSION = "1.5.1"
_TL_CACHE = {}
_PROF_CACHE = {}


def _merge(base, over):
    d = dict(base)
    if over:
        d.update(over)
    return d


def wilson(k, n, z=1.96):
    """95 % Wilson score interval for a binomial proportion."""
    if n == 0:
        return (None, None)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def timeline(const_key, g, cache_dir=None, const_over=None):
    c = _merge(PR.CONSTELLATIONS[const_key], const_over)
    ident = json.dumps(dict(c=c, site=g["site"], mask=g["elev_mask_deg"], t=g["t_end_s"],
                            dt=g["dt_s"], serving=g.get("serving", "sticky"), v="tl-1"), sort_keys=True)
    key = const_key + "_" + hashlib.sha1(ident.encode()).hexdigest()[:12]
    if key in _TL_CACHE:
        return _TL_CACHE[key]
    path = os.path.join(cache_dir, key + ".json") if cache_dir else None
    if path and os.path.exists(path):
        with open(path) as f:
            tl = json.load(f)
    else:
        sats = G.walker(c["n"], c["planes"], c["inc"], c["h"], c.get("phasing", 1))
        tl = G.visibility_timeline(sats, g["site"]["lat"], g["site"]["lon"], g["t_end_s"],
                                   g["dt_s"], g["elev_mask_deg"], g.get("serving", "sticky"))
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "w") as f:
                json.dump(tl, f)
    _TL_CACHE[key] = tl
    return tl


class Case:
    """Resolved configuration and cached link quantities for one case."""

    def __init__(self, stack, scen, stack_over=None, scen_over=None, g_over=None, cache_dir=None):
        self.st = _merge(PR.STACKS[stack], stack_over)
        self.sc = _merge(PR.SCENARIOS[scen], scen_over)
        self.g = _merge(PR.GLOBAL, g_over)
        self.amode = self.g.get("angle_mode", "interp")           # case-local propagation setting (N10)
        self.stack_key, self.scen_key = stack, scen
        self.const = PR.CONSTELLATIONS[self.st["const"]]
        self.h = self.const["h"]
        self.f = self.st["f_hz"]
        sat_cfg = dict(PR.SATELLITES[self.st["sat"]])
        sat_cfg.setdefault("sidelobe_model", self.g.get("sidelobe_model", "airy"))
        if "beams_per_sat" in self.st:
            sat_cfg["beams_per_sat"] = self.st["beams_per_sat"]
        self.ant = SatAntenna(sat_cfg, self.f)
        self.mask = self.g["elev_mask_deg"]
        if self.ant.kind == "broad":          # served region limited by the nadir beam
            a = math.radians(self.ant.bw / 2)
            c = (G.RE_KM + self.h) * math.sin(a) / G.RE_KM
            if c < 1:
                self.mask = max(self.mask, math.degrees(math.acos(c)))
        self.g = dict(self.g, elev_mask_deg=round(self.mask, 1))
        self.tl = timeline(self.st["const"], self.g, cache_dir)
        self.a0 = int(self.g["arrival_start_s"] / self.tl["dt"])
        self.n_arr = int(self.g["arrival_window_s"] / self.tl["dt"])
        self.cov = G.coverage_stats(self.tl, self.g["arrival_window_s"], self.g["arrival_start_s"])
        self.tech = self.st["tech"]
        self.eirp_dev = self.st["ptx_dbm"] + self.st["g_dev_dbi"] - self.sc["device_loss_db"]
        self.allow = self.g["pol_loss_db"] + self.g["scint_margin_db"] + self.g["gas_loss_db"]
        self.eirp = self.eirp_dev - self.allow
        self.n0 = P.K_DBM + 10 * math.log10(self.ant.t_sys_k())
        self._i0, self._pool, self._prof = {}, {}, None
        self.payload_phy = self.sc["payload_b"] + P.LORAWAN_OVERHEAD_B
        if self.tech == "LORA":
            self.toa = P.lora_toa_s(self.st["sf"], self.payload_phy)
            self.snr_req = P.LORA_SNR_DB[self.st["sf"]]
            self.rx_bw = 125e3
        elif self.tech == "LRFHSS":
            self.frame = P.lrfhss_frame(self.st["dr"], self.payload_phy)
            self.toa = self.frame["toa_s"]
            self.snr_req = self.frame["snr_req_db"]
            self.rx_bw = P.LRFHSS_OBW_HZ
        else:
            self.bits = (self.sc["payload_b"] + P.CELLULAR[self.tech]["overhead_b"]) * 8
            self.rach = self.st.get("rach") or PR.RACH[self.tech]
            for lvl in self.rach["ce"]:
                if lvl["period_s"] < lvl["reps"] * self.rach["preamble_s"]:
                    raise ValueError(f"RACH period {lvl['period_s']} s shorter than {lvl['reps']} x preamble")
            self.front = None
            if self.tech == "NBIOT" and self.g["nbiot_model"] == "tables":
                self.front = NB.frontier(self.bits, calibration=self.g["nbiot_calibration"],
                                         objective=self.g.get("nbiot_objective", "resource"))
                if not self.front:
                    raise ValueError("no NB-IoT configuration can carry this message")
        # device busy time per message (LoRa family): drives the per-device FIFO backlog (M04)
        self.per_msg = 0.0
        if self.tech in ("LORA", "LRFHSS"):
            copies, dcl = self.st.get("copies", 1), self.st.get("duty_cycle_limit")
            gap = self.toa * (1 / dcl - 1) if dcl else self.toa
            self.gap = gap
            self.per_msg = copies * self.toa + (copies - 1) * gap + (gap if dcl else 0.0)
        self._pidx = None
        self._nxt_allowed = None
        self._grid = None
        self.feeder_km = G.slant_range_km(self.h, self.g["feeder_el_deg"]) if self.st.get("payload") == "transparent" else 0.0
        # finite active beams (F10): beam-hopping duty when cells outnumber beams
        self.beam_duty = 1.0
        nb = self.ant.cfg.get("beams_per_sat")
        if self.ant.kind == "multibeam" and nb:
            svc = G.footprint_area_km2(self.h, self.g["elev_mask_deg"])
            cells = svc / self.cell_area(45.0)
            self.beam_duty = min(1.0, nb / cells)

    # ------------------------------------------------------------ interference
    def i0(self, el):
        b = int(round(max(10, min(90, el)) / 10.0) * 10)
        if b in self._i0:
            return self._i0[b]
        tot = 0.0
        pol = self.g["pol_loss_db"]
        if self.st.get("spectrum") == "ism":
            dens = PR.ISM_ACTIVITY[self.st.get("ism", "low")]
            v = I.aggregate_i0_dbm_hz(self.ant, self.h, self.f, dens, self.g["ism_eirp_dbm"],
                                      self.g["ism_band_hz"], "suburban", extra_loss_db=pol, serving_el_deg=b,
                                      angle_mode=self.amode)
            tot += 10 ** (v / 10) if v > -900 else 0.0
        if self.st.get("coexistence") == "cochannel" and not self.sc["tn_down"]:
            loss = I.indoor_mix_loss_db(self.g["tn_indoor_frac"], self.g["tn_bpl_db"]) + pol
            v = I.aggregate_i0_dbm_hz(self.ant, self.h, self.f, self.sc["tn_active_km2"],
                                      self.g["tn_ue_eirp_dbm"], self.g["tn_carrier_hz"],
                                      self.sc["env"], extra_loss_db=loss, serving_el_deg=b, angle_mode=self.amode)
            tot += 10 ** (v / 10) if v > -900 else 0.0
        val = 10 * math.log10(tot) if tot > 0 else -999.0
        self._i0[b] = val
        return val

    def n0_eff(self, el):
        return I.effective_n0(self.n0, self.i0(el))

    # ------------------------------------------------------------ population and traffic
    def cell_area(self, el):
        if self.ant.kind == "multibeam":
            return self.ant.beam_spot_area_km2(self.h, el, G.slant_range_km(self.h, el))
        return G.footprint_area_km2(self.h, self.g["elev_mask_deg"])

    def devices_in_cell(self, el):
        sc = self.sc
        a = self.cell_area(el)
        n = sc["local_density_km2"] * min(sc["local_area_km2"], a) + sc["background_density_km2"] * a
        return sc.get("load_scale", 1.0) * n, a

    def policy_index(self, i):
        """Deterministic transmit step for a message generated at step i, or None."""
        tl = self.tl
        j = tl["next_vis"][i] if i < len(tl["next_vis"]) else None
        if j is None:
            return None
        pol = self.st.get("tx_policy", self.g["tx_policy"])
        if pol == "elev_threshold":
            end = tl["pass_end"][j]
            k = j
            while k <= end and tl["el"][k] < self.g["tx_min_elev_deg"]:
                k += 1
            if k <= end:
                return k
            pol = "best_in_pass"
        if pol == "best_in_pass":
            end = tl["pass_end"][j]
            best = j
            for k in range(j, end + 1):
                if tl["el"][k] > tl["el"][best]:
                    best = k
            return best
        return j

    def pidx(self, i):
        if self._pidx is None:
            self._pidx = [self.policy_index(k) for k in range(len(self.tl["t"]))]
        return self._pidx[i] if 0 <= i < len(self._pidx) else None

    def jitter_span(self, jb):
        end = self.tl["pass_end"][jb]
        return max(1, min(int(round(self.g["release_jitter_s"] / self.tl["dt"])), end - jb + 1))

    def _allowed(self):
        """next_allowed[s]: first step >= s at which the transmit policy lets a
        message start (pidx(s) == s), or None."""
        if self._nxt_allowed is None:
            n = len(self.tl["t"])
            nxt = [None] * (n + 1)
            for k in range(n - 1, -1, -1):
                nxt[k] = k if self.pidx(k) == k else nxt[k + 1]
            self._nxt_allowed = nxt
        return self._nxt_allowed

    def next_start(self, t, need, u_jit, u_hop):
        """Earliest start >= t that is policy-allowed, inside a dwell of the
        cell's beam calendar (period hop_frame/duty, dwell hop_frame, cell
        offset u_hop) and leaves `need` seconds before the contact ends.
        Opening a new allowed window applies the device's release slot
        (u_jit x jitter span). Loops over opportunities (P02)."""
        tl, dt = self.tl, self.tl["dt"]
        n = len(tl["t"])
        nxt = self._allowed()
        duty = self.beam_duty
        per = self.g["hop_frame_s"] / duty if duty < 1.0 else None
        s_ = int(t // dt)
        while 0 <= s_ < n:
            sa = nxt[s_]
            if sa is None:
                return None
            t_c = t if (sa == s_ and t >= sa * dt) else sa * dt + u_jit * self.jitter_span(sa) * dt
            if per is not None:                                   # fixed beam calendar for this cell
                ph = (t_c - u_hop * per) % per
                if ph >= self.g["hop_frame_s"]:
                    t_c += per - ph
            sc = int(t_c // dt)
            if sc >= n:
                return None
            if not tl["vis"][sc] or nxt[sc] != sc:
                s_ = max(sc, s_ + 1); t = s_ * dt; continue
            end = tl["pass_end"][sc]
            if t_c + need <= (end + 1) * dt:
                return t_c
            s_ = end + 1; t = s_ * dt
        return None

    def device_schedule(self, phase, u_jit, u_hop):
        """Executed schedule of one device over the horizon (P01): messages at
        phase + k*interval, served first-in first-out with a persistent
        next-free time; expired messages are dropped without airtime.
        Returns a list of (generation time, status, start time)."""
        T, dl, disc = self.sc["interval_s"], self.sc["deadline_s"], self.g["discard_expired"]
        t_end = len(self.tl["t"]) * self.tl["dt"]
        if self.tech in ("LORA", "LRFHSS"):
            need = self.toa            # pass prediction from ephemeris: the packet must fit
        else:                          # Rel-17 NTN cell stop time (t-Service): sync + GNSS fix must fit
            need = E.DEVICES[self.st["device"]]["sync_s"] + _gnss_s(self, self.st["device"])
        recs, t_free, gt = [], -1e30, phase
        while gt < t_end:
            st0 = self.next_start(max(gt, t_free), need, u_jit, u_hop)
            if st0 is None:
                recs.append((gt, "lost", None))
            elif disc and st0 - gt > dl:
                recs.append((gt, "expired", st0))
            else:
                recs.append((gt, "ok", st0))
                if self.per_msg > 0:
                    t_free = st0 + self.per_msg
            gt += T
        return recs

    def schedule_grid(self, n_phase=None, n_jit=6, n_hop=4):
        """Stratified grid of device schedules (phase x release slot x beam
        phase), independent of load and seed and cached per configuration."""
        if self._grid is not None and n_phase is None:
            return self._grid
        dt, T = self.tl["dt"], self.sc["interval_s"]
        np_ = n_phase or max(16, int(round(2 * T / dt)))
        nh = n_hop if self.beam_duty < 1.0 else 1
        gkey = json.dumps([self.st, {k: v for k, v in self.sc.items() if k != "load_scale"},
                           {k: v for k, v in self.g.items() if k not in ("seed", "n_mc")}, self.beam_duty,
                           self.per_msg, self.toa if self.tech in ("LORA", "LRFHSS") else 0.0,
                           len(self.tl["t"]), np_, n_jit, nh], sort_keys=True, default=str)
        if gkey not in _PROF_CACHE:
            grid = [self.device_schedule((i + 0.5) / np_ * T, (q + 0.5) / n_jit, (h + 0.5) / nh)
                    for i in range(np_) for q in range(n_jit) for h in range(nh)]
            _PROF_CACHE[gkey] = grid
        if n_phase is None:
            self._grid = _PROF_CACHE[gkey]
        return _PROF_CACHE[gkey]

    def profile(self, grid=None):
        """Release profile from the executed schedules: m[j] = number of
        generation steps' worth of messages starting at step j, i.e.
        (interval/dt) x starts per device in step j (F08, P01)."""
        if self._prof is not None and grid is None:
            return self._prof
        grid = grid or self.schedule_grid()
        n, dt, T = len(self.tl["t"]), self.tl["dt"], self.sc["interval_s"]
        m = [0.0] * n
        w = (T / dt) / len(grid)
        cnt = {"ok": 0, "expired": 0, "lost": 0}
        for recs in grid:
            for gt, stt, st0 in recs:
                cnt[stt] += 1
                if stt == "ok":
                    m[int(st0 // dt)] += w
        tot = max(1, sum(cnt.values()))
        vis = sum(1 for v in self.tl["vis"] if v)
        prof = dict(m=m, expired_frac=cnt["expired"] / tot, lost_frac=cnt["lost"] / tot,
                    m_bar=n * cnt["ok"] / tot / max(vis, 1))
        if grid is self._grid:
            self._prof = prof
        return prof

    def msg_rate(self, el, j=None):
        """Packets/s offered to one cell at transmit step j (event model) or
        averaged over contacts (fluid model / broad footprints)."""
        n, _ = self.devices_in_cell(el)
        base = n / self.sc["interval_s"]
        if self.g["traffic_model"] == "event":
            pr = self.profile()
            if self.ant.kind == "multibeam" and j is not None:
                mj = pr["m"][j]                         # exact release count, no smoothing (N02)
            else:                                        # broad footprint: devices' contacts are smeared
                mj = pr["m_bar"]
            lam = base * mj
        else:
            lam = base / max(self.cov["coverage_fraction"], 1e-6)
        lam /= self.beam_duty
        lam *= 1.0 + self.st.get("other_networks_load", 0.0)
        return lam * self.st.get("copies", 1)

    # ------------------------------------------------------------ received power
    def rx_power_dbm(self, el, rng, offset=None, fading=False):
        d = G.slant_range_km(self.h, el)
        los, extra = CH.sample_loss_db(self.sc["env"], max(el, 10.0), rng, self.amode)
        a = G.off_nadir_deg(self.h, el)
        if offset is None:
            offset = math.sqrt(rng.random()) if self.ant.kind == "multibeam" else 0.0
        g = self.ant.gain_toward(a, offset)
        p = self.eirp - CH.fspl_db(d, self.f) - extra + g
        if fading:
            k = self.g["fade_k_los_db"] if los else self.g["fade_k_nlos_db"]
            p += 10 * math.log10(max(rng.rician_power(k), 1e-12))
        return p, los

    def pool(self, el):
        b = int(round(max(10, min(90, el)) / 10.0) * 10) if self.ant.kind == "multibeam" else 0
        if b in self._pool:
            return self._pool[b]
        rng = Rng(self.g["seed"] + 7 + b)
        out = []
        psi_max = G.central_angle_rad(self.h, self.g["elev_mask_deg"])
        for _ in range(self.g["pool_size"]):
            if self.ant.kind == "multibeam":
                e = b
            else:
                cpsi = 1 - rng.random() * (1 - math.cos(psi_max))
                e = G.elev_from_central_angle_deg(self.h, math.acos(cpsi))
            p, _ = self.rx_power_dbm(max(e, self.g["elev_mask_deg"]), rng, fading=True)
            out.append(10 ** (p / 10))
        out = A.Pool(out)
        self._pool[b] = out
        return out

    # ------------------------------------------------------------ deterministic margin
    def required_cn0(self):
        if self.tech == "LORA":
            return self.snr_req + 10 * math.log10(125e3)
        if self.tech == "LRFHSS":
            return self.snr_req + 10 * math.log10(P.LRFHSS_OBW_HZ)
        if self.front:
            return self.front[0]["cn0_req_dbhz"]
        c = P.CELLULAR[self.tech]
        return c["ebn0_db"] + 10 * math.log10(c["floor_bps"])

    def margin_at(self, el, los=True):
        d = G.slant_range_km(self.h, el)
        extra = CH.median_loss_db(self.sc["env"], max(el, 10.0), los, self.amode)
        g = self.ant.gain_toward(G.off_nadir_deg(self.h, el), 0.0)
        p = self.eirp - CH.fspl_db(d, self.f) - extra + g
        cn0 = p - self.n0_eff(el)
        out = dict(el=el, cn0_dbhz=cn0, margin_db=cn0 - self.required_cn0())
        if self.tech in ("LORA", "LRFHSS"):
            out["snr_db"] = cn0 - 10 * math.log10(self.rx_bw)
        elif self.front:
            cfg = NB.select(self.front, cn0 - self.g["la_margin_db"])
            out["rate_bps"] = None if cfg is None else self.bits / cfg["airtime_s"]
            out["config"] = None if cfg is None else f"{cfg['alloc']} ITBS{cfg['itbs']} NRU{cfg['nru']} x{cfg['nrep']}"
        else:
            out["rate_bps"] = P.cellular_rate_bps(self.tech, cn0)
        return out

    def rtt_s(self, el):
        return 2 * (G.slant_range_km(self.h, el) + self.feeder_km) / G.C_KMS


def _wait_and_geometry(case, rng):
    """Monte Carlo target: a random device of the schedule grid and a random
    message of it generated inside the arrival window. wait = start time -
    generation time (P01)."""
    tl, dt = case.tl, case.tl["dt"]
    grid = case.schedule_grid()
    lo, hi = case.a0 * dt, (case.a0 + case.n_arr) * dt
    for _ in range(64):
        recs = grid[rng.randint(len(grid))]
        idx = [k for k, r in enumerate(recs) if lo <= r[0] < hi]
        if idx:
            break
    gt, stt, st0 = recs[idx[rng.randint(len(idx))]]
    if stt == "lost":
        return None
    j = int(st0 // dt)
    if stt == "expired":
        return dict(wait=st0 - gt, j=j, expired=True)
    end = tl["pass_end"][j]
    return dict(wait=st0 - gt, j=j, el=tl["el"][j], fd=-case.f * tl["rr_kms"][j] / G.C_KMS,
                fdr=-case.f * tl["rra"][j] / G.C_KMS, left=(end + 1) * dt - st0, expired=False)


def _prach_reps(margin_db):
    need = max(0.0, 21.0 - margin_db)
    reps = 2 ** math.ceil(math.log2(max(1.0, 10 ** (need / 10))))
    return int(min(128, max(1, reps)))


def _gnss_s(case, dev):
    d = E.DEVICES[dev]
    if case.sc["gnss_per_msg"]:
        return d["gnss_hot_s"] if case.sc["interval_s"] < 7200 else d["gnss_warm_s"]
    return d["gnss_warm_s"] * min(1.0, case.sc["interval_s"] / case.g["gnss_validity_s"])


def _looks(airtime, coh):
    return int(min(8, max(1, round(airtime / max(coh, 1e-3)))))


def run_case(stack, scen, stack_over=None, scen_over=None, g_over=None, cache_dir=None,
             keep_samples=False):
    case = Case(stack, scen, stack_over, scen_over, g_over, cache_dir)
    st, sc, g = case.st, case.sc, case.g
    rng = Rng(g["seed"] + 1)
    K = g["n_mc"]
    cap = g["capture_db"]
    tech = case.tech
    causes = {"ok": 0, "snr": 0, "doppler": 0, "collision": 0, "no_coverage": 0, "blocked": 0, "expired": 0}
    lat, energies, els, cn0s, rates = [], [], [], [], []
    samples = []
    for _ in range(K):                                       # pass 1: geometry and link
        geo = _wait_and_geometry(case, rng)
        if geo is None:
            samples.append(None); continue
        if geo["expired"]:
            samples.append(geo); continue
        geo["p"], geo["los"] = case.rx_power_dbm(geo["el"], rng)
        samples.append(geo)
        els.append(geo["el"])
    extra = {}
    dl = sc["deadline_s"]
    discard = g["discard_expired"]
    fallback = 0
    if tech in ("NBIOT", "LTEM"):                            # pass 2: 3GPP access
        c = P.CELLULAR[tech]
        rach = case.rach
        gnss = _gnss_s(case, "nbiot_ntn")
        req_floor = case.required_cn0()
        dev = E.DEVICES[st["device"]]
        i_tx = E.tx_ma(dev, st["ptx_dbm"])
        v = dev["v"] / 1000.0
        harq_proc = g["harq_proc_s"]
        link = []
        for s in samples:
            if s is None:
                link.append(None); continue
            if s["expired"] or (discard and s["wait"] > dl):            # one expiry rule (N02)
                link.append(dict(ok=False, why="expired")); continue
            cn0_lt = s["p"] - case.n0_eff(s["el"])
            k = g["fade_k_los_db"] if s["los"] else g["fade_k_nlos_db"]
            if case.front:
                cfg = NB.select(case.front, cn0_lt - g["la_margin_db"])
                if cfg is None:
                    link.append(dict(ok=False, why="snr", ce=len(rach["ce"]) - 1)); continue
                scs = 3750.0 if cfg["alloc"] == "1x3.75k" else 15000.0
                t_air, b_hz, req = cfg["airtime_s"], cfg["b_hz"], cfg["cn0_req_dbhz"]
                t_tb, n_tb = cfg["tb_airtime_s"], cfg["n_tb"]
            else:
                r = P.cellular_rate_bps(tech, cn0_lt)
                if r is None:
                    link.append(dict(ok=False, why="snr", ce=len(rach["ce"]) - 1)); continue
                _, t_air, b_hz = P.cellular_resource_hz_s(tech, r, case.bits)
                req, scs = c["ebn0_db"] + 10 * math.log10(r), 15000.0
                t_tb, n_tb = t_air, 1
            fo = g["nbiot_residual_ppm"] * 1e-6 * case.f + abs(s["fdr"]) * g["precomp_update_s"]
            if fo > g["nbiot_max_fo_frac"] * scs:
                link.append(dict(ok=False, why="doppler", ce=len(rach["ce"]) - 1)); continue
            # per-TB HARQ with chase combining (M07, N03): every transport block has its own
            # attempts and feedback; fading is indexed by absolute time in coherence blocks, so
            # retransmissions inside one coherence time see the same channel.
            # one channel clock with random block phase (P03); att_end = end time of every attempt
            # measured from the start of the data phase, used by the executed-state clock (P04)
            spacing = case.rtt_s(s["el"]) + harq_proc
            coh = max(g["coh_s"], 1e-3)
            fades, att_h, ok_h, att_end = {}, 0, True, []
            ph0 = rng.random() * coh
            t_c = 0.0
            for _tb in range(n_tb):
                acc, a_tb, ok_tb = 0.0, 0, False
                while a_tb < g["harq_max"]:
                    a_tb += 1
                    fad = A.faded_gain(rng, fades, ph0 + t_c, ph0 + t_c + t_tb, coh, k)
                    acc += 10 ** ((cn0_lt + 10 * math.log10(max(fad, 1e-12))) / 10)
                    att_end.append(t_c + t_tb)
                    t_c += t_tb + spacing
                    if 10 * math.log10(acc) >= req:
                        ok_tb = True; break
                att_h += a_tb
                if not ok_tb:
                    ok_h = False; break               # message fails; later TBs are not sent
            need = _prach_reps(cn0_lt - req_floor)
            ce = next(i for i, lv in enumerate(rach["ce"]) if lv["reps"] >= need or i == len(rach["ce"]) - 1)
            link.append(dict(ok=True, data_ok=ok_h, attempts=att_h, t_air=t_tb, n_tb=n_tb, res=b_hz * t_tb * att_h,
                             res0=b_hz * t_tb * n_tb, ce=ce, cn0=cn0_lt, att_end=att_end, b_hz=b_hz))
            cn0s.append(cn0_lt)
            if ok_h:
                rates.append(case.bits / t_air)
        # per (elevation bin, offered-load level): access first, then scheduled demand (N01)
        groups = {}
        for s, lk in zip(samples, link):
            if s is None or (not lk["ok"] and lk["why"] == "expired"):
                continue
            lam = case.msg_rate(s["el"], s["j"])
            key = (int(s["el"] // 5) * 5, round(math.log10(max(lam, 1e-9)) * 10))
            s["gkey"] = key
            groups.setdefault(key, []).append((lk, lam))
        cap_hz = st["carriers_per_beam"] * c["carrier_ul_hz"] * (1 - st["ctrl_overhead"])
        state, by_ce, marks = {}, {}, []
        for key, items in groups.items():
            lam = sum(x[1] for x in items) / len(items)
            lks = [x[0] for x in items]
            nce = len(rach["ce"])
            frac = [sum(1 for x in lks if x.get("ce") == i) / len(lks) for i in range(nce)]
            pc = [A.nprach_success(lam * frac[i], rach["ce"][i]["period_s"], rach["ce"][i]["preambles"],
                                   st["rach_max"])[1] for i in range(nce)]
            pacc = [1 - p ** st["rach_max"] for p in pc]
            # data requests come only from devices that pass access and have a feasible configuration;
            # sv = realised service demand (all HARQ attempts) for queue moments, c0 = first-pass
            # resource of the granted configuration, the only cost known when admission happens (M01)
            dreq = [(pacc[x["ce"]], x["res"] / cap_hz, x["res0"] / cap_hz) for x in lks if x["ok"]]
            w_tot = sum(w for w, _, _ in dreq)
            scale = lam / len(lks)
            lam_d = scale * w_tot
            es = sum(w * sv for w, sv, _ in dreq) / w_tot if w_tot > 0 else 0.0
            es2 = sum(w * sv * sv for w, sv, _ in dreq) / w_tot if w_tot > 0 else 0.0
            rho = lam_d * es
            f_cut, c_cut, f_all = 1.0, float("inf"), 1.0
            if rho > g["rho_admit"] and w_tot > 0:
                if g.get("admission", "uniform") == "cheapest_first":
                    # cost tiers by causal grant cost; whole tiers admitted in increasing cost until
                    # rho_admit, the boundary tier admitted with probability f_cut; queue moments use
                    # exactly the admitted population (same f_cut) (M01)
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
                    lam_a, rho_q = scale * adm_w, acc_r
                    es2_a = adm_s2 / adm_w if adm_w > 0 else 0.0
                    admit = adm_w / w_tot
                    qwait = lam_a * es2_a / (2 * (1 - rho_q)) if rho_q < 1 else float("inf")
                else:                                   # uniform random admission (primary baseline)
                    f_all = g["rho_admit"] / rho
                    admit, lam_a = f_all, lam_d * f_all
                    rho_q = lam_a * es
                    qwait = lam_a * es2 / (2 * (1 - rho_q)) if rho_q < 1 else float("inf")
            else:
                admit, rho_q = 1.0, rho
                qwait = lam_d * es2 / (2 * (1 - rho_q)) if rho_q < 1 else float("inf")   # M/G/1 (Pollaczek-Khinchine)
            state[key] = dict(rho=rho, rho_admitted=rho_q, admit=admit, qwait=qwait, p_coll=pc,
                              f_all=f_all, f_cut=f_cut, c_cut=c_cut)
        for s, lk in zip(samples, link):
            if s is None:
                energies.append(0.0); causes["no_coverage"] += 1; lat.append(None); continue   # per generated message (N08)
            if not lk["ok"] and lk["why"] == "expired":
                energies.append(0.0); causes["expired"] += 1; lat.append(None); continue
            stt = state[s["gkey"]]
            cec = by_ce.setdefault(lk.get("ce", -1), dict(n=0, ok=0, blocked=0))
            cec["n"] += 1
            lv = rach["ce"][lk["ce"]]
            pre = lv["reps"] * rach["preamble_s"]
            rtt = case.rtt_s(s["el"])
            q_e = dev["rx_ma"] * dev["sync_s"] + dev["gnss_ma"] * gnss       # executed-state energy (N08)
            # v1.5.1 causal energy clock: access, queue, data and release are charged only while the
            # contact lasts and the message is not expired (time measured from transaction start)
            lim = min(s["left"], (dl - s["wait"]) if discard else float("inf")) - dev["sync_s"] - gnss
            if not lk["ok"]:                                                  # below floor or frequency limit
                d_att = 0.5 * lv["period_s"] + pre + rtt + rach["rar_window_s"] + 0.5 * rach["backoff_s"]
                n_exec = min(st["rach_max"], math.ceil(lim / d_att)) if lim > 0 else 0
                q_e += n_exec * (i_tx * pre + dev["rx_ma"] * rach["rar_window_s"])
                energies.append(v * q_e); causes[lk["why"]] += 1; lat.append(None); continue
            t_acc, att, ok, n_exec = 0.0, 0, False, 0
            while att < st["rach_max"]:                # random draws unchanged from v1.5.0
                att += 1
                if t_acc < lim:
                    n_exec += 1
                t_acc += rng.random() * lv["period_s"] + pre + rtt + rach["rar_window_s"]
                if rng.random() >= stt["p_coll"][lk["ce"]]:
                    ok = True; break
                t_acc += rng.random() * rach["backoff_s"]
            q_e += n_exec * (i_tx * pre + dev["rx_ma"] * rach["rar_window_s"])
            access_late = t_acc > lim
            if not ok:
                energies.append(v * q_e); causes["collision"] += 1; lat.append(None); continue
            c0 = round(lk["res0"] / cap_hz, 12)
            f_adm = stt["f_all"] if c0 < stt["c_cut"] else (stt["f_cut"] if c0 == stt["c_cut"] else 0.0)
            pre_t = dev["sync_s"] + gnss + t_acc
            air_t = lk["attempts"] * lk["t_air"] + (lk["attempts"] - 1) * (rtt + harq_proc) + rtt
            mk = dict(el=s["el"], j=s["j"], wait=s["wait"], pre=pre_t, air=air_t, svc=lk["res"] / cap_hz,
                      svc0=lk["res0"] / cap_hz,
                      attempts=lk["attempts"], n_tb=lk["n_tb"],
                      left=s["left"], data_ok=lk["data_ok"]) if keep_samples else None
            if f_adm < 1.0 and rng.random() >= f_adm:
                if mk is not None:
                    mk.update(sched="blocked", qw=None); marks.append(mk)
                energies.append(v * q_e); causes["blocked"] += 1; cec["blocked"] += 1; lat.append(None); continue
            qw = stt["qwait"] if stt["qwait"] != float("inf") else s["left"]
            # executed-state clock (P04): data attempts run only while the contact lasts and the
            # message is not expired; only executed attempts are charged (energy) and counted
            t_pre = dev["sync_s"] + gnss + t_acc + qw
            avail_c = s["left"] - t_pre
            avail_d = (dl - s["wait"] - t_pre) if discard else float("inf")
            avail = min(avail_c, avail_d)
            n_a = sum(1 for te in lk["att_end"] if te <= avail)
            if not access_late:
                if not st["edt"]:
                    q_e += dev["rx_ma"] * dev["setup_extra_rx_s"] + i_tx * dev["setup_extra_tx_s"]
                q_e += dev["idle_ma"] * min(qw, max(lim - t_acc, 0.0))
                q_e += n_a * (i_tx * lk["t_air"] + dev["rx_ma"] * (rtt + harq_proc))
                if n_a < len(lk["att_end"]):                         # attempt cut by contact end or expiry
                    t0 = lk["att_end"][n_a] - lk["t_air"]
                    if avail > t0:
                        q_e += i_tx * (min(avail, lk["att_end"][n_a]) - t0)
                if n_a > 0:                                          # release only after data was sent
                    q_e += dev["rx_ma"] * dev["release_rai_s"] if st["rai"] else dev["idle_ma"] * dev["inactivity_s"]
            energies.append(v * q_e)
            t_data = (lk["att_end"][-1] + rtt) if lk["att_end"] else 0.0
            transaction = t_pre + t_data
            complete = n_a == lk["attempts"] and t_data <= avail
            if mk is not None:
                fit = transaction <= s["left"]
                mk.update(qw=qw, sched=("late_contact" if not fit else
                                        ("late_deadline" if s["wait"] + transaction > dl else "served")))
                marks.append(mk)
            if not complete:
                why = "no_coverage" if avail_c <= avail_d else "expired"
                causes[why] += 1; lat.append(None); continue
            if not lk["data_ok"]:
                causes["snr"] += 1; lat.append(None); continue
            d = s["wait"] + transaction + (0.0 if st.get("payload") == "transparent" else g["ground_delay_s"])
            causes["ok"] += 1; lat.append(d)
            if d <= dl:
                cec["ok"] += 1
        allst = list(state.values())
        extra = dict(rho_max=max((x["rho"] for x in allst), default=0.0),
                     admitted_fraction_min=min((x["admit"] for x in allst), default=1.0),
                     rho_admitted_max=max((x["rho_admitted"] for x in allst), default=0.0),
                     admission=g.get("admission", "uniform"),
                     on_time_by_ce={str(kk): dict(share=vv["n"] / K, on_time=vv["ok"] / max(vv["n"], 1),
                                                  blocked=vv["blocked"] / max(vv["n"], 1))
                                    for kk, vv in sorted(by_ce.items())},
                     p_preamble_collision_max=max((max(x["p_coll"]) for x in allst), default=0.0),
                     burst_rate_bps=(sum(rates) / len(rates)) if rates else None,
                     nbiot_model=g["nbiot_model"] if tech == "NBIOT" else None,
                     nbiot_calibration=g["nbiot_calibration"] if tech == "NBIOT" else None,
                     nbiot_objective=g.get("nbiot_objective", "resource") if tech == "NBIOT" else None)
    else:                                                    # pass 2: LoRa / LR-FHSS
        copies = st.get("copies", 1)
        dcl = st.get("duty_cycle_limit")
        gap = case.gap
        rxw = 2 * g["rx_window_symbols"] * P.lora_symbol_s(12) if st.get("class_a_rx") else 0.0
        e_cp = [0.0] + [E.lora_msg_energy_j(st["device"], st["ptx_dbm"], case.toa, c_, sc["gnss_per_msg"], rxw)
                        for c_ in range(1, copies + 1)]
        for s in samples:
            if s is None:
                energies.append(0.0); causes["no_coverage"] += 1; lat.append(None); continue   # per generated message (N08)
            if s["expired"] or (discard and s["wait"] > dl):                 # expiry after every deferral (M04)
                energies.append(0.0); causes["expired"] += 1; lat.append(None); continue
            el = s["el"]
            n0e = case.n0_eff(el)
            lam = case.msg_rate(el, s["j"])
            pool = case.pool(el)
            p_mw = 10 ** (s["p"] / 10)
            # executed copies (P04): copies start only inside the contact and before expiry
            lim = min(s["left"], (dl - s["wait"]) if discard else float("inf"))
            n_cp = max(1, min(copies, 1 + int(max(lim - case.toa, 0.0) // (case.toa + gap))))
            energies.append(e_cp[n_cp])
            fades, coh = {}, max(g["coh_s"], 1e-3)
            ph0 = rng.random() * coh
            offset = abs(s["fd"]) + g["osc_ppm"] * 1e-6 * case.f
            if tech == "LORA":
                dop_ok = P.lora_doppler_ok(st["sf"], 125e3, offset, s["fdr"])
            else:
                dop_ok = P.lrfhss_doppler_ok(s["fdr"]) and (g["lrfhss_acq_hz"] is None or offset <= g["lrfhss_acq_hz"])
            if not dop_ok:
                causes["doppler"] += 1; lat.append(None); continue
            ok, cause, k_ok = False, "snr", 0
            k = g["fade_k_los_db"] if s["los"] else g["fade_k_nlos_db"]
            for kcp in range(n_cp):
                t_k = ph0 + kcp * (case.toa + gap)              # one channel clock for all copies (P03)
                if tech == "LORA":
                    fad = 10 * math.log10(max(A.faded_gain(rng, fades, t_k, t_k + case.toa, coh, k), 1e-12))
                    snr = s["p"] + fad - n0e - 10 * math.log10(125e3)
                    ok, cause = A.lora_attempt(rng, snr, case.snr_req, p_mw * 10 ** (fad / 10),
                                               lam / st["channels"] * 2 * case.toa, pool, cap)
                else:
                    snr = s["p"] - n0e - 10 * math.log10(P.LRFHSS_OBW_HZ)
                    if g["lrfhss_model"] == "packet":
                        ok, cause, fb = A.lrfhss_attempt_packet(rng, snr, case.frame, p_mw, lam, pool, cap, k,
                                                                n_grids=case.frame["C"] // case.frame["grid"],
                                                                coh_s=g["coh_s"], fades=fades, t_start=t_k)
                        fallback += fb
                    else:
                        a_h, a_f = A.lrfhss_overlap_means(lam, case.frame)
                        ok, cause = A.lrfhss_attempt(rng, snr, case.frame, p_mw, a_h, a_f, pool, cap, k)
                cn0s.append(snr + 10 * math.log10(case.rx_bw))
                if ok:
                    k_ok = kcp; break
            t_tx = k_ok * (case.toa + gap) + case.toa             # backlog already inside s["wait"] (M04)
            if ok and t_tx > s["left"]:
                ok, cause = False, "no_coverage"
            if ok and discard and s["wait"] + t_tx > dl:
                ok, cause = False, "expired"
            if ok:
                causes["ok"] += 1
                lat.append(s["wait"] + t_tx + (g["ground_delay_s"] if st.get("payload") == "regenerative" else case.rtt_s(el) / 2))
            else:
                causes[cause] += 1; lat.append(None)
        extra = dict(toa_s=case.toa, device_duty_cycle=case.toa * copies / sc["interval_s"],
                     duty_cycle_compliant=(case.toa * copies / sc["interval_s"] <= dcl) if dcl else None,
                     duty_cycle_note=("1 % applies within 868.0-868.6 MHz (TDRA SRD table); channels outside "
                                      "that sub-band need their own limit") if dcl else None,
                     lrfhss_model=g["lrfhss_model"] if tech == "LRFHSS" else None,
                     lrfhss_marginal_fallback_fraction=(fallback / max(1, K)) if tech == "LRFHSS" else None)
        if tech == "LRFHSS":
            extra["frame"] = case.frame
    # ---------------------------------------------------------------- KPIs
    assert len(energies) == K and len(lat) == K, "energy and latency ledgers must cover every generated message"
    delivered = [x for x in lat if x is not None]
    in_deadline = [x for x in delivered if x <= sc["deadline_s"]]
    srt = sorted(delivered)
    q = lambda p: srt[min(len(srt) - 1, int(p * len(srt)))] if srt else None
    e_mean = sum(energies) / len(energies) if energies else 0.0
    pdr = len(delivered) / K
    msgs_day = 86400.0 / sc["interval_s"]
    n_cell, a_cell = case.devices_in_cell(45.0)
    bat, lim = E.battery_years(st["device"], e_mean, msgs_day, g["battery_mah"], g["battery_v"],
                               calendar_years=g["calendar_life_years"])
    on_time = len(in_deadline) / K
    alloc = st.get("alloc_hz")
    lam45 = case.msg_rate(45.0)
    out = dict(
        stack=case.stack_key, scenario=case.scen_key, model=st["model"], label=st["label"],
        tech=tech, f_mhz=case.f / 1e6, antenna=case.ant.summary(), payload=st.get("payload"),
        constellation=dict(case.const, key=st["const"]), coverage=case.cov,
        device_eirp_dbm=case.eirp_dev, propagation_allowances_db=case.allow,
        eirp_dbm=case.eirp, n0_dbm_hz=case.n0,
        noise_rise_db_at_45=I.noise_rise_db(case.i0(45.0), case.n0),
        devices_in_cell_at_45=n_cell, cell_area_km2_at_45=a_cell, beam_duty=case.beam_duty,
        traffic_model=g["traffic_model"], expired_fraction=case.profile()["expired_frac"],
        msgs_per_s_per_beam=lam45,
        delivery_basis="uplink reception at satellite/gateway (no downlink, no ACK)",
        pdr=pdr, pdr_ci95=wilson(len(delivered), K),
        pdr_deadline=on_time, pdr_deadline_ci95=wilson(len(in_deadline), K),
        causes={k: v / K for k, v in causes.items()},
        latency_mean_s=(sum(delivered) / len(delivered)) if delivered else None,
        latency_p50_s=q(0.5), latency_p95_s=q(0.95),
        energy_per_msg_j=e_mean, energy_per_delivered_j=(e_mean / pdr) if pdr > 0 else None,
        energy_per_on_time_j=(e_mean / on_time) if on_time > 0 else None,
        battery_years=bat, battery_limited_by=lim,
        alloc_hz=alloc,
        on_time_msgs_per_s_per_mhz=(n_cell / sc["interval_s"] * on_time / (alloc / 1e6)) if alloc else None,
        mean_tx_elev_deg=(sum(els) / len(els)) if els else None,
        median_cn0_dbhz=sorted(cn0s)[len(cn0s) // 2] if cn0s else None,
        energy_basis="generated", n_mc=K, seed=g["seed"], model_version=MODEL_VERSION, **extra)
    if keep_samples:
        out["latencies"] = lat
        if tech in ("NBIOT", "LTEM"):
            out["sched_marks"] = marks
            out["cap_hz"] = cap_hz
        out["elevations"] = els
    return out


def margin_curve(stack, scen, elevs=None, los=True, **kw):
    case = Case(stack, scen, **kw)
    elevs = elevs or list(range(10, 91, 5))
    return [case.margin_at(e, los) for e in elevs]
