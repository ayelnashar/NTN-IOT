"""Techno-economic template.

ALL DEFAULT PRICES ARE PLACEHOLDERS, not market data. They exist so the
calculation runs; replace them with quotes before drawing conclusions. Results
are tagged 'placeholder_inputs': True until every price is overridden.
"""

PLACEHOLDER_PRICES = {
    "operator_nbiot_ntn": dict(module_usd=None, connectivity_usd_per_year=None,
                               install_usd=None),
    "iot_only_lorawan_ntn": dict(module_usd=None, connectivity_usd_per_year=None,
                                 install_usd=None),
}


def tco_per_device(prices, years, battery_life_yr, battery_usd, delivered_per_year):
    """Total cost of ownership and cost per delivered message."""
    if any(v is None for v in prices.values()) or battery_usd is None:
        return dict(placeholder_inputs=True, note="enter module, install, connectivity and battery prices")
    swaps = max(0, int(years / max(battery_life_yr, 1e-6) - 1e-9))
    tco = prices["module_usd"] + prices["install_usd"] * (1 + swaps) + battery_usd * (1 + swaps) \
        + prices["connectivity_usd_per_year"] * years
    return dict(placeholder_inputs=False, tco_usd=tco, battery_swaps=swaps,
                usd_per_delivered_msg=tco / max(delivered_per_year * years, 1e-9))
