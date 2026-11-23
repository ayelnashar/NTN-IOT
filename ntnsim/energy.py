"""Device energy per message and battery life.

Current profiles are datasheet-typical values, labelled 'assumed'; replace with
measured values for a specific module. Everything is per-message energy (J)
built from state durations, so the same code runs for any traffic profile.
"""
import math

DEVICES = {
    "lora_lr11xx": dict(            # LR1120/SX1262-class radio + MCU
        v=3.3, tx_ma={14: 45.0, 17: 60.0, 20: 87.0, 22: 118.0},
        rx_ma=5.0, sleep_ua=2.0, mcu_ma=3.0, mcu_s=0.2,
        gnss_ma=10.0, gnss_hot_s=2.0, gnss_warm_s=2.0,       # LoRa Edge cloud-assisted scan
        source="SX1262 datasheet (14 dBm 45 mA, 22 dBm 118 mA); intermediate points and GNSS scan assumed"),
    "lora_lr1120_sband": dict(      # LR1120 HF PA path used for S-band
        v=3.3, tx_ma={11.5: 30.7}, rx_ma=6.7, sleep_ua=2.0, mcu_ma=3.0, mcu_s=0.2,
        gnss_ma=10.0, gnss_hot_s=2.0, gnss_warm_s=2.0,
        source="LR1121 module figures (30.7 mA at 13 dBm 2.4 GHz HF path, 6.7 mA RX) used for S-band; assumed"),
    "sband_hp_module": dict(        # external-PA S-band LoRa module
        v=3.6, tx_ma={27.0: 0.5012 / (0.30 * 3.6) * 1000 + 20.0}, rx_ma=7.0, sleep_ua=5.0,
        mcu_ma=3.0, mcu_s=0.2, gnss_ma=10.0, gnss_hot_s=2.0, gnss_warm_s=2.0,
        source="assumed: 27 dBm PA at 30 % efficiency from 3.6 V plus 20 mA; no datasheet profile used"),
    "nbiot_ntn": dict(              # NB-IoT / LTE-M NTN module with GNSS
        v=3.6, tx_ma={0: 60.0, 10: 90.0, 20: 180.0, 23: 230.0},
        rx_ma=30.0, idle_ma=6.0, sleep_ua=4.0,
        gnss_ma=25.0, gnss_hot_s=3.0, gnss_warm_s=30.0,
        sync_s=1.5,                 # cell search + MIB + SIBs incl. NTN ephemeris
        rar_s=0.25, release_rai_s=0.2, inactivity_s=10.0,
        setup_extra_rx_s=0.5, setup_extra_tx_s=0.05,
        source="assumed, typical of Rel-17 NTN modules; replace with measured profile"),
}


def tx_ma(profile, p_dbm):
    tbl = sorted(profile["tx_ma"].items())
    if p_dbm <= tbl[0][0]:
        return tbl[0][1]
    for (p0, i0), (p1, i1) in zip(tbl, tbl[1:]):
        if p_dbm <= p1:
            return i0 + (i1 - i0) * (p_dbm - p0) / (p1 - p0)
    return tbl[-1][1]


def lora_msg_energy_j(dev, p_dbm, toa_s, copies=1, gnss_fix=False, rx_window_s=0.0):
    """All blind copies are charged: an unconfirmed sender cannot know an earlier
    copy succeeded. rx_window_s = total Class A receive-window time per copy."""
    d = DEVICES[dev]
    q = (tx_ma(d, p_dbm) * toa_s + d["rx_ma"] * rx_window_s) * copies + d["mcu_ma"] * d["mcu_s"]
    if gnss_fix:
        q += d["gnss_ma"] * d["gnss_hot_s"]
    return d["v"] * q / 1000.0


def cellular_msg_energy_j(dev, p_dbm, t_data_s, attempts, prach_s_each, edt=True,
                          rai=True, gnss_s=0.0, rar_s=None, access_ok=True):
    """Same state timeline as the latency model. A failed access is charged sync,
    GNSS and its preamble attempts only (no data, no release)."""
    d = DEVICES[dev]
    i_tx = tx_ma(d, p_dbm)
    rar = d["rar_s"] if rar_s is None else rar_s
    q = d["rx_ma"] * d["sync_s"] + d["gnss_ma"] * gnss_s
    q += attempts * (i_tx * prach_s_each + d["rx_ma"] * rar)
    if access_ok:
        q += i_tx * t_data_s
        if not edt:
            q += d["rx_ma"] * d["setup_extra_rx_s"] + i_tx * d["setup_extra_tx_s"]
        q += d["rx_ma"] * d["release_rai_s"] if rai else d["idle_ma"] * d["inactivity_s"]
    return d["v"] * q / 1000.0


def battery_years(dev, e_msg_j, msgs_per_day, cap_mah=5200.0, v_batt=3.6,
                  usable=0.8, self_discharge_yr=0.01, calendar_years=None):
    """Energy-limited life, capped by an assumed calendar life of the cell.
    Returns (years, limited_by) with limited_by in {'energy', 'calendar'}."""
    d = DEVICES[dev]
    cap_j = cap_mah * 3.6 * v_batt * usable
    e_sleep_day = d["v"] * d["sleep_ua"] * 1e-6 * 86400
    e_year = (e_msg_j * msgs_per_day + e_sleep_day) * 365
    y = cap_j / (e_year + self_discharge_yr * cap_j)
    if calendar_years is not None and y > calendar_years:
        return calendar_years, "calendar"
    return y, "energy"
