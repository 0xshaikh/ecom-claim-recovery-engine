"""Generate sample CSVs for the e-commerce claim recovery engine.

Creates three CSVs in ``sample_data/``:
- orders_sample.csv        (200 orders with intentional fraud patterns)
- settlement_sample.csv    (200 settlement rows keyed by AWB_Number)
- sku_master_sample.csv    (25 SKUs with real physical dimensions)

Distribution (deterministic via ``random.seed(42)``):
- 35 rows courier weight fraud
- 25 rows 45+ day lost RTO
- 15 rows unpaid damaged returns
- 125 clean delivered orders

Run with: ``python generate_sample_data.py``
"""

from __future__ import annotations

import csv
import os
import random
from datetime import date, timedelta

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SEED = 42
N_ORDERS = 200
N_FRAUD_WEIGHT = 35
N_LOST_RTO = 25
N_UNPAID_DAMAGED = 15
N_CLEAN = N_ORDERS - N_FRAUD_WEIGHT - N_LOST_RTO - N_UNPAID_DAMAGED  # 125

MARKETPLACES = ("Flipkart", "Meesho", "Amazon")
MARKET_PREFIX = {"Flipkart": "FLK", "Meesho": "MSH", "Amazon": "AMZ"}
COURIERS = ("Shiprocket", "BlueDart", "Delhivery", "Ecom Express")
ZONES = ("Local", "Zonal", "National")

OUTER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample_data")


# --------------------------------------------------------------------------- #
# SKU master
# --------------------------------------------------------------------------- #

SKU_DEFS = [
    # (SKU, name, dead_g, L, B, H, cost, sell)
    ("CPS-001", "Cotton Panjabi", 480, 32, 22, 4, 520, 1299),
    ("CPS-002", "Silk Panjabi", 620, 35, 25, 4, 980, 2499),
    ("TRO-001", "Terry T-shirt", 180, 30, 22, 2, 110, 399),
    ("TRO-002", "Cotton T-shirt", 200, 30, 22, 2, 140, 499),
    ("DRT-001", "Straight Jeans", 420, 38, 25, 3, 620, 1499),
    ("DRT-002", "Slim Jeans", 430, 38, 25, 3, 640, 1599),
    ("SKT-001", "Cotton Socks Pack", 90, 18, 12, 3, 60, 199),
    ("HAT-001", "Sun Hat", 220, 28, 18, 8, 240, 699),
    ("BAG-001", "Canvas Tote", 320, 42, 32, 10, 380, 999),
    ("BAG-002", "Denim Bag", 340, 44, 32, 12, 420, 1199),
    ("PNT-001", "Cotton Pant", 460, 36, 26, 3, 560, 1399),
    ("SKR-001", "Cotton Skirt", 380, 34, 24, 3, 480, 1199),
    ("KUR-001", "Kurta", 500, 36, 26, 4, 620, 1499),
    ("LEG-001", "Leggings", 250, 32, 22, 3, 180, 549),
    ("BLB-001", "Baby Blanket", 520, 40, 30, 5, 640, 1799),
    ("SHE-001", "Bedsheet", 780, 48, 34, 6, 720, 1899),
    ("BLP-001", "Bath Towel", 460, 38, 32, 4, 380, 999),
    ("PIL-001", "Memory Pillow", 900, 42, 32, 14, 850, 2299),
    ("CUSH-001", "Sofa Cushion", 720, 45, 35, 18, 620, 1699),
    ("MUG-001", "Ceramic Mug", 380, 12, 12, 10, 180, 499),
    ("BTL-001", "Steel Bottle 1L", 520, 30, 9, 9, 320, 899),
    ("BOX-001", "Cosmetics Kit", 850, 25, 18, 12, 900, 2499),
    ("CHG-001", "Power Charger", 280, 14, 10, 5, 240, 799),
    ("CAM-001", "Action Camera", 620, 18, 12, 8, 4200, 11999),
    ("WTR-001", "Water Bottle Set", 980, 34, 22, 12, 520, 1299),
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _today() -> date:
    return date.today()


def _rand_int(rng: random.Random, lo: int, hi: int) -> int:
    return rng.randint(lo, hi)


def _pick(rng: random.Random, seq):
    return rng.choice(seq)


# --------------------------------------------------------------------------- #
# SKU master
# --------------------------------------------------------------------------- #


def _build_sku_master(rows: list[dict]) -> None:
    path = os.path.join(OUTER_DIR, "sku_master_sample.csv")
    fieldnames = [
        "SKU", "Product_Name", "Dead_Weight_g", "Length_cm",
        "Breadth_cm", "Height_cm", "Cost_Price", "Selling_Price",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- #
# Orders + settlements
# --------------------------------------------------------------------------- #


def _make_awb(rng: random.Random, market: str, counter: int) -> str:
    return f"{MARKET_PREFIX[market]}{counter:06d}"


def _generate(rng: random.Random, sku_defs):
    orders = []
    settlements = []

    # Bucket allocation
    buckets: list[tuple[int, str]] = (
        [(i, "WEIGHT_FRAUD") for i in range(N_FRAUD_WEIGHT)]
        + [(i, "LOST_RTO") for i in range(N_LOST_RTO)]
        + [(i, "UNPAID_DAMAGED") for i in range(N_UNPAID_DAMAGED)]
        + [(i, "CLEAN") for i in range(N_CLEAN)]
    )
    rng.shuffle(buckets)

    sku_by_code = {s[0]: s for s in sku_defs}

    for idx, (row_idx, bucket) in enumerate(buckets):
        market = _pick(rng, MARKETPLACES)
        awb = _make_awb(rng, market, idx + 1)
        sku_def = _pick(rng, sku_defs)
        sku, product_name = sku_def[0], sku_def[1]
        dead_weight_g = sku_def[2]
        cost_price = sku_def[6]
        selling_price = sku_def[7]

        # Order date: last 90 days
        days_ago = _rand_int(rng, 0, 89)
        order_date = _today() - timedelta(days=days_ago)

        qty = 1 if _rand_int(rng, 0, 4) else 2
        invoice_value = selling_price * qty
        zone = _pick(rng, ZONES)
        courier = _pick(rng, COURIERS)

        # Pick an order status based on bucket.
        # BUCKET: WEIGHT_FRAUD -> status DELIVERED (so shipping was charged normally)
        # BUCKET: LOST_RTO -> RTO_IN_TRANSIT / RETURN_IN_TRANSIT / RTO_INITIATED
        # BUCKET: UNPAID_DAMAGED -> CUSTOMER_RETURN_DAMAGED
        # BUCKET: CLEAN -> DELIVERED / CUSTOMER_RETURN / mixed but non-fraudulent
        if bucket == "WEIGHT_FRAUD":
            status = "DELIVERED"
            return_initiated = ""
            physical_received = "True"
            delivered_to_seller = str(order_date + timedelta(days=_rand_int(rng, 1, 4)))
        elif bucket == "LOST_RTO":
            status = _pick(rng, ("RTO_IN_TRANSIT", "RETURN_IN_TRANSIT", "RTO_INITIATED"))
            # Return initiated 46-90 days ago (so >45 days)
            rto_days_ago = _rand_int(rng, 46, 90)
            return_initiated = str(_today() - timedelta(days=rto_days_ago))
            physical_received = "False"
            delivered_to_seller = ""
        elif bucket == "UNPAID_DAMAGED":
            status = "CUSTOMER_RETURN_DAMAGED"
            return_initiated = str(order_date + timedelta(days=_rand_int(rng, 5, 20)))
            physical_received = "True"
            delivered_to_seller = str(order_date + timedelta(days=_rand_int(rng, 3, 10)))
        else:  # CLEAN
            # Mix of delivered + a few clean returns that were actually paid
            r = rng.random()
            if r < 0.85:
                status = "DELIVERED"
                return_initiated = ""
                physical_received = "True"
                delivered_to_seller = str(order_date + timedelta(days=_rand_int(rng, 1, 5)))
            else:
                # clean returned goods — but the seller was compensated, no claim needed
                status = "RTO_DELIVERED"
                return_initiated = str(order_date + timedelta(days=_rand_int(rng, 5, 20)))
                physical_received = "True"
                delivered_to_seller = str(order_date + timedelta(days=_rand_int(rng, 15, 30)))

        orders.append({
            "AWB_Number": awb,
            "Marketplace": market,
            "SKU": sku,
            "Product_Name": product_name,
            "Qty": qty,
            "Order_Date": order_date.isoformat(),
            "Order_Status": status,
            "Return_Initiated_Date": return_initiated,
            "Warehouse_Physical_Received": physical_received,
            "Delivered_To_Seller_Date": delivered_to_seller,
            "Zone": zone,
            "Courier": courier,
        })

        # --- settlement ---
        # Forward shipping based on a "normal" billable weight (dead weight approx)
        # then fraud pads the courier weight.
        base_billable = max(dead_weight_g, (sku_def[3] * sku_def[4] * sku_def[5]) / 5.0)
        # Actual dead weight with slight variance per parcel
        actual_dead = max(100, int(dead_weight_g * rng.uniform(0.92, 1.08)))

        marketplace_fee_pct = rng.choice((0.08, 0.09, 0.10, 0.12, 0.14, 0.15))
        marketplace_fee = int(invoice_value * marketplace_fee_pct)

        # Weight charged by courier
        if bucket == "WEIGHT_FRAUD":
            # Fraud multiplier is scaled against the SKU's *billable*
            # weight (dead vs volumetric) so the charged weight reliably
            # clears the 15% tolerance in recon_engine. Small items
            # need a bigger multiplier than volumetric-heavy ones.
            billable_est = max(actual_dead,
                               (sku_def[3] * sku_def[4] * sku_def[5]) / 5.0)
            if billable_est < 300:
                multiplier = rng.choice((3.0, 4.0, 5.0))
            elif billable_est < 800:
                multiplier = rng.choice((2.5, 3.0, 4.0))
            else:
                multiplier = rng.choice((2.0, 2.5, 3.0))
            weight_charged = int(billable_est * multiplier)
            forward_charged = _forward_fee_estimate(zone, weight_charged)
        else:
            weight_charged = int(base_billable)
            forward_charged = _forward_fee_estimate(zone, weight_charged)

        is_return = status in {
            "RTO_IN_TRANSIT", "RETURN_IN_TRANSIT", "RTO_INITIATED",
            "RTO_DELIVERED", "CUSTOMER_RETURN_DAMAGED",
        }
        reverse_charged = _forward_fee_estimate(zone, weight_charged) if is_return else 0

        if bucket == "LOST_RTO":
            bank_settlement = 0
            claim_amt = 0
            claim_paid = "False"
        elif bucket == "UNPAID_DAMAGED":
            bank_settlement = 0
            claim_amt = 0
            claim_paid = "False"
        elif bucket == "WEIGHT_FRAUD":
            # Delivered orders do settle, but the freight was over-charged
            bank_settlement = invoice_value - marketplace_fee - forward_charged
            claim_amt = 0
            claim_paid = "False"
        else:  # CLEAN
            if status == "DELIVERED":
                bank_settlement = invoice_value - marketplace_fee - forward_charged
                claim_amt = 0
                claim_paid = "False"
            else:
                # RTO_DELIVERED — some get a reverse-logistics credit, some don't
                if rng.random() < 0.4:
                    bank_settlement = 0
                    claim_amt = 0
                    claim_paid = "False"
                else:
                    bank_settlement = int(invoice_value * 0.5) - reverse_charged
                    claim_amt = 0
                    claim_paid = "False"

        settlements.append({
            "AWB_Number": awb,
            "Invoice_Value": invoice_value,
            "Marketplace_Fee": marketplace_fee,
            "Forward_Shipping_Charged": forward_charged,
            "Reverse_Shipping_Charged": reverse_charged,
            "Actual_Bank_Settlement": bank_settlement,
            "Claim_Settlement_Amount": claim_amt,
            "Claim_Paid": claim_paid,
            "Weight_Charged_by_Courier_g": weight_charged,
        })

    return orders, settlements


def _forward_fee_estimate(zone: str, weight_g: float) -> int:
    """Rough forward-shipping fee mirroring core.rate_card for sample data."""
    import math
    base = {"Local": 40, "Zonal": 55, "National": 72}[zone]
    per = {"Local": 18, "Zonal": 25, "National": 34}[zone]
    slabs = max(1, math.ceil(weight_g / 500))
    return base + per * (slabs - 1)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    random.seed(SEED)
    rng = random.Random(SEED)

    os.makedirs(OUTER_DIR, exist_ok=True)

    _build_sku_master([
        {
            "SKU": s[0],
            "Product_Name": s[1],
            "Dead_Weight_g": s[2],
            "Length_cm": s[3],
            "Breadth_cm": s[4],
            "Height_cm": s[5],
            "Cost_Price": s[6],
            "Selling_Price": s[7],
        }
        for s in SKU_DEFS
    ])

    orders, settlements = _generate(rng, SKU_DEFS)

    orders_path = os.path.join(OUTER_DIR, "orders_sample.csv")
    settlements_path = os.path.join(OUTER_DIR, "settlement_sample.csv")

    order_fields = [
        "AWB_Number", "Marketplace", "SKU", "Product_Name", "Qty",
        "Order_Date", "Order_Status", "Return_Initiated_Date",
        "Warehouse_Physical_Received", "Delivered_To_Seller_Date",
        "Zone", "Courier",
    ]
    settlement_fields = [
        "AWB_Number", "Invoice_Value", "Marketplace_Fee",
        "Forward_Shipping_Charged", "Reverse_Shipping_Charged",
        "Actual_Bank_Settlement", "Claim_Settlement_Amount",
        "Claim_Paid", "Weight_Charged_by_Courier_g",
    ]

    with open(orders_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=order_fields)
        w.writeheader()
        w.writerows(orders)

    with open(settlements_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=settlement_fields)
        w.writeheader()
        w.writerows(settlements)

    print(
        f"Generated {N_ORDERS} orders: "
        f"{N_FRAUD_WEIGHT} weight fraud, {N_LOST_RTO} lost RTO, "
        f"{N_UNPAID_DAMAGED} unpaid damaged, {N_CLEAN} clean."
    )


if __name__ == "__main__":
    main()
