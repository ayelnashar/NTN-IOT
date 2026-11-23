"""Satellite antenna models.

Two pattern families:
  broad  - single nadir-pointing beam, cos^q pattern derived from boresight gain
           (patch / deployable antennas on small satellites).
  multibeam - large phased array forming narrow beams steered at the device;
           gain from aperture, Gaussian main lobe, planar-array scan loss.
Gain and beamwidth are always derived from the same aperture, so footprint and
gain cannot be set inconsistently.
"""
import math

C_MS = 299792458.0


def wavelength_m(f_hz):
    return C_MS / f_hz


def gain_from_aperture_dbi(area_m2, f_hz, eff=0.65):
    lam = wavelength_m(f_hz)
    return 10 * math.log10(eff * 4 * math.pi * area_m2 / lam ** 2)


def aperture_for_gain_m2(g_dbi, f_hz, eff=0.65):
    lam = wavelength_m(f_hz)
    return 10 ** (g_dbi / 10) * lam ** 2 / (eff * 4 * math.pi)


def beamwidth_from_aperture_deg(area_m2, f_hz):
    """-3 dB full beamwidth ~ 70 lambda / D for a uniformly illuminated aperture."""
    d = math.sqrt(4 * area_m2 / math.pi)
    return 70.0 * wavelength_m(f_hz) / d


def bessel_j1(x):
    """J1(x), Numerical Recipes rational/asymptotic approximation (portable)."""
    ax = abs(x)
    if ax < 8.0:
        y = x * x
        a1 = x * (72362614232.0 + y * (-7895059235.0 + y * (242396853.1 + y * (-2972611.439
             + y * (15704.48260 + y * (-30.16036606))))))
        a2 = 144725228442.0 + y * (2300535178.0 + y * (18583304.74 + y * (99447.43394
             + y * (376.9991397 + y))))
        return a1 / a2
    z = 8.0 / ax
    y = z * z
    xx = ax - 2.356194491
    a1 = 1.0 + y * (0.183105e-2 + y * (-0.3516396496e-4 + y * (0.2457520174e-5 + y * (-0.240337019e-6))))
    a2 = 0.04687499995 + y * (-0.2002690873e-3 + y * (0.8449199096e-5 + y * (-0.88228987e-6 + y * 0.105787412e-6)))
    ans = math.sqrt(0.636619772 / ax) * (math.cos(xx) * a1 - z * math.sin(xx) * a2)
    return ans if x > 0 else -ans


def airy_rel_db(sep_deg, bw_deg):
    """Circular-aperture pattern [2 J1(x)/x]^2, scaled so the -3 dB full width
    equals bw_deg. Physically normalised (integral of G over the sphere <= 1)."""
    if sep_deg <= 0:
        return 0.0
    x = 1.6163 * math.sin(math.radians(min(sep_deg, 90.0))) / math.sin(math.radians(bw_deg / 2))
    v = 2 * bessel_j1(x) / x
    return 10 * math.log10(max(v * v, 1e-12))


def s1528_rel_db(sep_deg, bw_deg, g0_dbi, ln_db=-20.0, lf_dbi=0.0, alpha=1.5, z=1.0):
    """ITU-R S.1528 recommends 1.2 envelope (circular beam, z = 1), relative to
    peak; main-lobe exponent alpha = 1.5 per recommends 1.2 (external review;
    pin the recommendation revision before publication). Back lobe for
    90-180 deg: L_B = max(15 + L_N + 0.25 G_m + 5 log10 z, 0) dBi (N06).
    The elliptical-beam branches (z > 1) are not implemented: scanned beams
    use the equivalent-angle ellipse of gain_direction(). An interference-
    assessment bound, not a realised pattern."""
    psib = bw_deg / 2
    a, b = 2.58, 6.32
    p = abs(sep_deg)
    if p > 90.0:
        return max(15.0 + ln_db + 0.25 * g0_dbi + 5 * math.log10(z), 0.0) - g0_dbi
    if p <= a * psib:
        g = -3 * (p / psib) ** alpha
    elif p <= b * psib:
        g = ln_db
    else:
        y = b * psib * 10 ** (0.04 * (g0_dbi + ln_db - lf_dbi))
        g = ln_db - 25 * math.log10(p / (b * psib)) if p <= y else lf_dbi - g0_dbi
    return g


def cosq_exponent(g0_dbi):
    """q such that a cos^q(theta) pattern over a hemisphere has peak gain g0."""
    return max(10 ** (g0_dbi / 10) / 2.0 - 1.0, 0.0)


def cosq_beamwidth_deg(q):
    if q <= 0:
        return 180.0
    return 2 * math.degrees(math.acos(0.5 ** (1.0 / q)))


class SatAntenna:
    def __init__(self, cfg, f_hz):
        self.cfg = cfg
        self.f = f_hz
        self.kind = cfg["pattern"]
        self.nf_db = cfg.get("nf_db", 2.0)
        self.t_ant_k = cfg.get("t_ant_k", 290.0)
        if self.kind == "multibeam":
            self.g0 = gain_from_aperture_dbi(cfg["aperture_m2"], f_hz, cfg.get("eff", 0.65))
            self.bw = beamwidth_from_aperture_deg(cfg["aperture_m2"], f_hz)
            self.scan_k = cfg.get("scan_loss_exp", 1.2)
            self.side_model = cfg.get("sidelobe_model", "airy")   # 'airy' (realised) | 's1528' (envelope)
        else:
            self.g0 = cfg["gain_dbi"]
            self.q = cosq_exponent(self.g0)
            self.bw = cosq_beamwidth_deg(self.q)

    # T_sys and G/T ---------------------------------------------------------
    def t_sys_k(self):
        return self.t_ant_k + 290.0 * (10 ** (self.nf_db / 10) - 1)

    def g_over_t(self, gain_dbi):
        return gain_dbi - 10 * math.log10(self.t_sys_k())

    # gain toward a device ----------------------------------------------------
    def gain_toward(self, off_nadir_deg, beam_offset_frac=0.0):
        """Gain (dBi) toward a device at the given off-nadir angle.

        beam_offset_frac in [0,1]: radial position inside the -3 dB contour of
        the serving beam (multibeam only). 1.0 is the beam edge (-3 dB).
        """
        if self.kind == "multibeam":
            a = math.radians(min(off_nadir_deg, 89.0))
            scan = 10 * self.scan_k * math.log10(max(math.cos(a), 1e-3))
            off = -3.0 * beam_offset_frac ** 2
            return self.g0 + scan + off
        a = math.radians(min(off_nadir_deg, 89.9))
        return self.g0 + 10 * self.q * math.log10(max(math.cos(a), 1e-6))

    def gain_direction(self, off_nadir_deg, sep_deg, az_rad=0.0, axis_scan_deg=0.0):
        """Gain toward an arbitrary emitter: element factor at the emitter's
        off-nadir angle times the array factor at its separation from the beam
        axis (multibeam); cos^q about nadir (broad).

        The scanned array beam is elliptical (N06): its width in the scan plane
        is bw / cos(scan) and bw across it. az_rad is the emitter's azimuth
        around the beam axis measured from the scan plane. The separation is
        mapped to the circular-equivalent angle before applying the pattern, so
        wanted-signal gain, footprint and interference use one scanned pattern."""
        if self.kind == "multibeam":
            a = math.radians(min(off_nadir_deg, 89.0))
            elem = 10 * self.scan_k * math.log10(max(math.cos(a), 1e-3))
            c = max(math.cos(math.radians(axis_scan_deg)), 0.05)
            s_eq = sep_deg * math.sqrt((math.cos(az_rad) * c) ** 2 + math.sin(az_rad) ** 2)
            if self.side_model == "s1528":
                # S.1528-based scanned envelope: circular (z = 1) branches on the equivalent angle,
                # back lobe selected on the PHYSICAL separation (P08); not the full elliptical S.1528
                rel = (s1528_rel_db(sep_deg, self.bw, self.g0) if sep_deg > 90.0
                       else s1528_rel_db(min(s_eq, 90.0), self.bw, self.g0))
            else:
                rel = airy_rel_db(s_eq, self.bw)
            return self.g0 + elem + rel
        return self.gain_toward(off_nadir_deg)

    def pattern_integral(self, axis_off_nadir_deg=0.0, n_s=1200, n_b=96):
        """(1/4pi) * integral of G over the sphere (Earth-facing and space-facing
        hemisphere both counted); <= 1 for a physical antenna."""
        tot = 0.0
        smax = math.pi
        for i in range(n_s):
            sp = (i + 0.5) * smax / n_s
            for j in range(n_b):
                be = (j + 0.5) * 2 * math.pi / n_b
                # direction relative to beam axis, axis tilted by axis_off_nadir from nadir
                ta = math.radians(axis_off_nadir_deg)
                ux = math.sin(sp) * math.cos(be)
                uy = math.sin(sp) * math.sin(be)
                uz = math.cos(sp)
                # rotate about y by ta: nadir is +z in this frame
                nz = -ux * math.sin(ta) + uz * math.cos(ta)
                off = math.degrees(math.acos(max(-1.0, min(1.0, nz))))
                if off >= 90.0:
                    g = -60.0 if self.kind == "broad" else self.g0 + (s1528_rel_db(math.degrees(sp), self.bw, self.g0) if self.side_model == "s1528" else -60.0)
                else:
                    g = self.gain_direction(off, math.degrees(sp), be, axis_off_nadir_deg) if self.kind == "multibeam" else self.gain_toward(off)
                tot += 10 ** (g / 10) * math.sin(sp) * (smax / n_s) * (2 * math.pi / n_b)
        return tot / (4 * math.pi)

    def beam_spot_area_km2(self, h_km, elev_deg, slant_km):
        """Ground area of one -3 dB beam spot (multibeam). The array beam
        broadens as 1/cos(scan) in the scan plane, and the spot is stretched by
        1/sin(elevation) on the ground (F10)."""
        if self.kind != "multibeam":
            return None
        RE = 6371.0
        scan = math.asin(min(1.0, RE * math.cos(math.radians(elev_deg)) / (RE + h_km)))
        r_cross = slant_km * math.tan(math.radians(self.bw / 2))
        r_along = slant_km * math.tan(math.radians(min(self.bw / (2 * max(math.cos(scan), 0.05)), 60.0)))
        return math.pi * r_cross * r_along / max(math.sin(math.radians(elev_deg)), 0.1)

    def summary(self):
        d = dict(pattern=self.kind, boresight_gain_dbi=round(self.g0, 2),
                 beamwidth_deg=round(self.bw, 2), t_sys_k=round(self.t_sys_k(), 1),
                 g_over_t_dbk=round(self.g_over_t(self.g0), 2))
        if self.kind == "multibeam":
            d["aperture_m2"] = self.cfg["aperture_m2"]
        return d
