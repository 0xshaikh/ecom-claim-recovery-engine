"""Reconciliation engine for Indian e-commerce claim recovery.

Merges three inputs — Orders, Settlement, SKU Master — and detects the
three claimable categories the app cares about:

1. **Weight fraud** — the courier billed at a weight materially above
   what the SKU dimensions allow (15% tolerance for rounding).
2. **Lost RTO (45+ days)** — a return/RTO that has been in transit for
   more than 45 days with no physical receipt at the seller's godown
   and no claim settled.
3. **Unpaid damaged returns** — customer returned damaged goods but the
   seller was not compensated.

Pure pandas logic. No external API calls. Deterministic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict

import numpy as np
import pandas as pd

from .rate_card import (
    compute_billable_weight_g,
    compute_shipping_fee,
    compute_volumetric_weight_g,
)


# --------------------------------------------------------------------------- #
# Thresholds / constants
# --------------------------------------------------------------------------- #

WEIGHT_TOLERANCE = 1.15          # 15% buffer for rounding
LOST_RTO_DAYS = 45               # minimum days in transit to count as "lost"
RTO_LOSS_FACTOR = 0.85           # % of invoice_value recoverable on lost RTO
DAMAGED_RETURN_FACTOR = 0.90     # % of invoice_value recoverable on damaged return

RTO_STATUSES = {"RTO_IN_TRANSIT", "RETURN_IN_TRANSIT", "RTO_INITIATED"}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _parse_dates(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], errors="coerce")
    return df


def _to_bool(series: pd.Series) -> pd.Series:
    """Coerce mixed True/False/'true'/'FALSE' values to real booleans."""
    if series.dtype == bool:
        return series
    s = series.astype(str).str.strip().str.lower()
    return s.isin({"true", "1", "yes"})


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def run_reconciliation(
    orders_path: str,
    settlement_path: str,
    sku_master_path: str,
) -> Dict[str, object]:
    """Run full reconciliation and detect claimable rows.

    Args:
        orders_path: Path to the orders CSV.
        settlement_path: Path to the settlement/billing CSV.
        sku_master_path: Path to the SKU master CSV.

    Returns:
        Dict with keys:
        - ``merged``: fully joined DataFrame.
        - ``weight_fraud``: weight-fraud rows, sorted by claimable DESC.
        - ``lost_rto``: 45+ day lost RTO rows, sorted by claimable DESC.
        - ``unpaid_damaged``: unpaid damaged returns, sorted by claimable DESC.
        - ``summary``: dict with counts and recoverable totals.
    """
    orders = _parse_dates(
        pd.read_csv(orders_path),
        ["Order_Date", "Return_Initiated_Date", "Delivered_To_Seller_Date"],
    )
    settlements = pd.read_csv(settlement_path)
    sku = pd.read_csv(sku_master_path)

    df = orders.merge(settlements, on="AWB_Number", how="inner", validate="one_to_one")
    # Drop orders-side Product_Name so SKU merge produces a single Product_Name column
    if "Product_Name" in df.columns and "Product_Name" in sku.columns:
        df = df.drop(columns=["Product_Name"])
    df = df.merge(sku, on="SKU", how="left", validate="many_to_one")

    df["Warehouse_Physical_Received"] = _to_bool(df["Warehouse_Physical_Received"])
    df["Claim_Paid"] = _to_bool(df["Claim_Paid"])

    df["Volume_Weight_g"] = df.apply(
        lambda r: compute_volumetric_weight_g(
            float(r["Length_cm"]), float(r["Breadth_cm"]), float(r["Height_cm"])
        ),
        axis=1,
    )
    df["Billable_Weight_g"] = df.apply(
        lambda r: compute_billable_weight_g(
            float(r["Dead_Weight_g"]), float(r["Volume_Weight_g"])
        ),
        axis=1,
    )
    df["Expected_Shipping_Fee"] = df.apply(
        lambda r: compute_shipping_fee(str(r["Zone"]), float(r["Billable_Weight_g"])),
        axis=1,
    )

    # Days in transit (for RTO rows)
    reference_date = pd.Timestamp.now(tz=None).normalize()
    # Fall back to max date in dataset if no Return_Initiated_Date at all
    if df["Return_Initiated_Date"].notna().any():
        # Use the later of today / max(return_initiated) so we don't
        # undercount when the dataset has been regenerated.
        max_return = df["Return_Initiated_Date"].max()
        reference_date = max(reference_date, pd.Timestamp(max_return))
    df["Days_In_Transit"] = (reference_date - df["Return_Initiated_Date"]).dt.days

    # ---- Detection --------------------------------------------------------- #

    recon_type = pd.Series("CLEAN", index=df.index, dtype=object)
    claimable = pd.Series(0, index=df.index, dtype="int64")

    # Weight fraud
    weight_mask = (
        df["Weight_Charged_by_Courier_g"].astype(float)
        > df["Billable_Weight_g"].astype(float) * WEIGHT_TOLERANCE
    )
    # Only consider rows where forward shipping was actually charged
    weight_mask = weight_mask & (df["Forward_Shipping_Charged"].astype(float) > 0)
    weight_mask = weight_mask & recon_type.eq("CLEAN")

    recon_type.loc[weight_mask] = "WEIGHT_FRAUD"
    claimable.loc[weight_mask] = (
        df.loc[weight_mask, "Forward_Shipping_Charged"].astype(int)
        - df.loc[weight_mask, "Expected_Shipping_Fee"].astype(int)
    ).clip(lower=0)

    # Lost RTO
    rto_mask = (
        df["Order_Status"].isin(RTO_STATUSES)
        & df["Days_In_Transit"].fillna(0).gt(LOST_RTO_DAYS)
        & (~df["Warehouse_Physical_Received"])
        & (df["Claim_Settlement_Amount"].fillna(0).astype(float) == 0)
        & (~df["Claim_Paid"])
        & recon_type.eq("CLEAN")
    )
    recon_type.loc[rto_mask] = "LOST_RTO"
    claimable.loc[rto_mask] = (
        df.loc[rto_mask, "Invoice_Value"].astype(float) * RTO_LOSS_FACTOR
    ).round().astype(int)

    # Unpaid damaged
    damaged_mask = (
        df["Order_Status"].eq("CUSTOMER_RETURN_DAMAGED")
        & (df["Actual_Bank_Settlement"].fillna(0).astype(float) == 0)
        & (~df["Claim_Paid"])
        & recon_type.eq("CLEAN")
    )
    recon_type.loc[damaged_mask] = "UNPAID_DAMAGED"
    claimable.loc[damaged_mask] = (
        df.loc[damaged_mask, "Invoice_Value"].astype(float) * DAMAGED_RETURN_FACTOR
    ).round().astype(int)

    df["Recon_Type"] = recon_type
    df["Claimable_Amount"] = claimable

    weight_fraud = df.loc[recon_type.eq("WEIGHT_FRAUD")].copy()
    lost_rto = df.loc[recon_type.eq("LOST_RTO")].copy()
    unpaid_damaged = df.loc[recon_type.eq("UNPAID_DAMAGED")].copy()

    weight_fraud = weight_fraud.sort_values("Claimable_Amount", ascending=False)
    lost_rto = lost_rto.sort_values("Claimable_Amount", ascending=False)
    unpaid_damaged = unpaid_damaged.sort_values("Claimable_Amount", ascending=False)

    summary = {
        "total_orders": int(len(df)),
        "total_recoverable": int(
            weight_fraud["Claimable_Amount"].sum()
            + lost_rto["Claimable_Amount"].sum()
            + unpaid_damaged["Claimable_Amount"].sum()
        ),
        "weight_fraud_count": int(len(weight_fraud)),
        "weight_fraud_amount": int(weight_fraud["Claimable_Amount"].sum()),
        "lost_rto_count": int(len(lost_rto)),
        "lost_rto_amount": int(lost_rto["Claimable_Amount"].sum()),
        "unpaid_damaged_count": int(len(unpaid_damaged)),
        "unpaid_damaged_amount": int(unpaid_damaged["Claimable_Amount"].sum()),
        "clean_count": int((recon_type == "CLEAN").sum()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return {
        "merged": df,
        "weight_fraud": weight_fraud,
        "lost_rto": lost_rto,
        "unpaid_damaged": unpaid_damaged,
        "summary": summary,
    }
