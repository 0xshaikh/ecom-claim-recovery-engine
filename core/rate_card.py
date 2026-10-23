"""Courier shipping slab calculator for Indian e-commerce.

Slab rules (typical Shiprocket / partner aggregator schedule):

- Base fee covers the first 0.5 kg.
- Every additional 0.5 kg slab costs a fixed increment.
- Slab size is rounded UP to the nearest 0.5 kg, minimum 0.5 kg.
- Volumetric weight = (L * B * H) / 5  (in grams, using cm and divisor 5000).
- Billable weight = max(dead weight, volumetric weight).

All functions are pure and deterministic. No external dependencies.
"""

from __future__ import annotations

import math
from typing import Dict


# --------------------------------------------------------------------------- #
# Slab configuration (₹)
# --------------------------------------------------------------------------- #

BASE_FEES: Dict[str, int] = {
    "Local": 40,       # First 0.5 kg
    "Zonal": 55,
    "National": 72,
}

ADDITIONAL_PER_SLAB: Dict[str, int] = {
    "Local": 18,       # Each additional 0.5 kg
    "Zonal": 25,
    "National": 34,
}

DEFAULT_ZONE = "Zonal"
SLAB_GRAMS = 500


# --------------------------------------------------------------------------- #
# Primitive calculations
# --------------------------------------------------------------------------- #


def compute_volumetric_weight_g(length_cm: float, breadth_cm: float, height_cm: float) -> float:
    """Volumetric weight in grams.

    Formula used by most Indian aggregators::

        volumetric_g = (L_cm * B_cm * H_cm / 5000) * 1000
                     = L_cm * B_cm * H_cm / 5

    Args:
        length_cm: Length in centimetres.
        breadth_cm: Breadth in centimetres.
        height_cm: Height in centimetres.

    Returns:
        Volumetric weight in grams (float). Returns ``0.0`` if any
        dimension is non-positive — the caller can decide whether to
        fall back to dead weight.
    """
    if length_cm <= 0 or breadth_cm <= 0 or height_cm <= 0:
        return 0.0
    return (length_cm * breadth_cm * height_cm) / 5.0


def compute_billable_weight_g(dead_weight_g: float, volumetric_weight_g: float) -> float:
    """Billable weight = max(dead weight, volumetric weight) in grams.

    Args:
        dead_weight_g: Actual dead (tare-inclusive) weight in grams.
        volumetric_weight_g: Volumetric weight in grams.

    Returns:
        Billable weight in grams. Non-positive inputs are clamped to 0.
    """
    return max(0.0, max(dead_weight_g, volumetric_weight_g))


def compute_slab_kg(billable_weight_g: float) -> float:
    """Return the shipping slab in kilograms.

    Slab = ceil(billable_g / 500) * 0.5, with a floor of 0.5 kg so that
    even an empty parcel costs at least one slab.

    Args:
        billable_weight_g: Billable weight in grams.

    Returns:
        Slab size in kilograms (float, multiple of 0.5, >= 0.5).
    """
    if billable_weight_g <= 0:
        return 0.5
    slabs = max(1, math.ceil(billable_weight_g / SLAB_GRAMS))
    return slabs * 0.5


# --------------------------------------------------------------------------- #
# Fee calculations
# --------------------------------------------------------------------------- #


def compute_shipping_fee(zone: str, billable_weight_g: float) -> int:
    """Return expected shipping fee in rupees.

    Args:
        zone: One of ``Local``, ``Zonal``, ``National``. Unknown zones
            fall back to ``Zonal`` so that a bad input never crashes the
            pipeline — it just uses the mid-tier price.
        billable_weight_g: Billable weight in grams.

    Returns:
        Shipping fee in rupees (int). Minimum is the base fee.
    """
    slab_kg = compute_slab_kg(billable_weight_g)
    base = BASE_FEES.get(zone, BASE_FEES[DEFAULT_ZONE])
    extra_per = ADDITIONAL_PER_SLAB.get(zone, ADDITIONAL_PER_SLAB[DEFAULT_ZONE])
    extra_slabs = int(round((slab_kg - 0.5) / 0.5))
    extra_slabs = max(0, extra_slabs)
    return base + extra_per * extra_slabs


def compute_weight_overcharge(
    zone: str,
    dead_weight_g: float,
    volumetric_weight_g: float,
    courier_charged_g: float,
) -> int:
    """Return overcharge amount in rupees. 0 if no fraud.

    Compares the fee implied by the actual billable weight with the fee
    implied by the weight the courier declared on the AWB.

    Args:
        zone: Delivery zone.
        dead_weight_g: Real dead weight of the parcel in grams.
        volumetric_weight_g: Real volumetric weight in grams.
        courier_charged_g: Weight the courier actually billed on.

    Returns:
        Overcharge in rupees (int >= 0). Returns 0 whenever the courier
        billed at or below the legitimate fee.
    """
    actual_billable = compute_billable_weight_g(dead_weight_g, volumetric_weight_g)
    expected_fee = compute_shipping_fee(zone, actual_billable)
    charged_fee = compute_shipping_fee(zone, max(0.0, courier_charged_g))
    return max(0, charged_fee - expected_fee)
