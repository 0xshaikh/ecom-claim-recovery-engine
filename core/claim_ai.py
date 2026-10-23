"""AI-powered claim note generator.

Generates marketplace-specific dispute text for Flipkart SPF, Meesho, Amazon SAFE-T,
and courier weight disputes. Falls back to template-based generation when no
GemINI_API_KEY is configured.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class Marketplace(Enum):
    FLIPKART = "Flipkart"
    MEESHO = "Meesho"
    AMAZON = "Amazon"
    COURIER_WEIGHT = "Courier Weight Dispute"


class ClaimType(Enum):
    WEIGHT_FRAUD = "Weight Fraud"
    LOST_RTO = "Lost RTO / Untracked Return"
    DAMAGED_RETURN = "Unpaid Damaged Return"


@dataclass
class ClaimContext:
    """Structured context for a single claim."""
    awb_number: str
    marketplace: Marketplace
    claim_type: ClaimType
    product_name: str
    invoice_value: int
    claimed_amount: int
    # Optional details
    dead_weight_g: Optional[int] = None
    volumetric_weight_g: Optional[int] = None
    courier_charged_g: Optional[int] = None
    days_in_transit: Optional[int] = None
    ticket_number: Optional[str] = None
    date_initiated: Optional[str] = None
    snapshot_paths: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_claim_note(context: ClaimContext) -> str:
    """Generate a claim note. Uses Gemini if a key is configured, else template."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        try:
            return _generate_with_gemini(api_key, context)
        except Exception as exc:  # noqa: BLE001 - graceful fallback is intentional
            logger.warning("Gemini generation failed, falling back to template: %s", exc)
    return _generate_with_template(context)


# ---------------------------------------------------------------------------
# Gemini path
# ---------------------------------------------------------------------------

def _generate_with_gemini(api_key: str, context: ClaimContext) -> str:
    """Call Gemini 2.5 Flash for structured dispute text."""
    from google import genai  # type: ignore
    from google.genai import types  # type: ignore

    client = genai.Client(api_key=api_key)

    system_prompt = (
        "You are a senior e-commerce dispute analyst for Indian marketplace "
        "sellers. Draft a formal, professional claim note addressed to the "
        "marketplace grievance cell. Include: subject line, salutation, facts "
        "of case (numbered), policy clause references (Flipkart SPF, Meesho "
        "Claims Policy, Amazon SAFE-T), requested relief, and a polite but firm "
        "escalation note. Use Indian English. Use Indian Rupees (Rs.) and INR "
        "spelling where natural. Do NOT invent ticket numbers, dates, GSTINs, "
        "or addresses — use bracketed placeholders where the seller must fill in."
    )

    user_prompt = (
        f"Marketplace: {context.marketplace.value}\n"
        f"Claim type: {context.claim_type.value}\n"
        f"AWB: {context.awb_number}\n"
        f"Product: {context.product_name}\n"
        f"Invoice value: Rs.{context.invoice_value}\n"
        f"Claimed amount: Rs.{context.claimed_amount}\n"
        f"Days in transit: {context.days_in_transit}\n"
        f"Dead weight: {context.dead_weight_g} g\n"
        f"Volumetric weight: {context.volumetric_weight_g} g\n"
        f"Courier-charged weight: {context.courier_charged_g} g\n"
        "Draft the claim note now."
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_prompt,
        config=types.GenerateContentConfig(system_instruction=system_prompt),
    )
    return (response.text or "").strip()


# ---------------------------------------------------------------------------
# Template fallback
# ---------------------------------------------------------------------------

def _generate_with_template(context: ClaimContext) -> str:
    """Deterministic template fallback. Always works, no external call."""
    today = date.today().isoformat()
    d_init = context.date_initiated or today
    days = context.days_in_transit or "45+"
    ticket = context.ticket_number or "[Ticket Number]"

    if context.marketplace == Marketplace.COURIER_WEIGHT:
        return _template_courier_weight(context, today)

    if context.claim_type == ClaimType.WEIGHT_FRAUD:
        return _template_weight_fraud(context, today)
    if context.claim_type == ClaimType.LOST_RTO:
        return _template_lost_rto(context, today, d_init, days, ticket)
    if context.claim_type == ClaimType.DAMAGED_RETURN:
        return _template_damaged(context, today)

    return _template_lost_rto(context, today, d_init, days, ticket)


def _template_lost_rto(
    context: ClaimContext, today: str, d_init: str, days: str, ticket: str
) -> str:
    if context.marketplace == Marketplace.FLIPKART:
        return f"""Subject: Formal Claim Intimation — Order AWB #{context.awb_number} — Package Undelivered / Lost in Transit

Dear Flipkart Seller Support,

I am writing to formally request a Full Settlement of Rs.{context.claimed_amount} for the order bearing AWB number {context.awb_number} under the Flipkart Standard Performance Framework (SPF), Section "Lost Returns & RTO Claims".

FACTS OF CASE:
1. Return was initiated on {d_init}. As of today ({today}), {days} days have elapsed.
2. The consignment has not been received at my registered warehouse.
3. No RTO reverse settlement has been credited to my Seller Hub settlement account.
4. The forward shipment was successfully delivered and the customer confirmed receipt.

I HAVE EXHAUSTED:
- Multiple check-ins with the assigned courier (AWB status: Last Updated 45+ days ago)
- Flipkart Help Center ticket #{ticket}
- Seller Hub Dispute submission on {d_init}

UNDER THE FLIPKART SPF POLICY, orders in transit beyond 45 calendar days without delivery confirmation or RTO receipt are eligible for FULL SETTLEMENT of the seller's net invoice value (Rs.{context.claimed_amount}), inclusive of:
- Product value: Rs.{context.invoice_value}
- Forward fulfillment charge waiver
- Reverse shipping charge waiver
- Applicable platform fee reversal

REQUESTED RELIEF:
1. Issue immediate settlement of Rs.{context.claimed_amount} to my Seller Hub account.
2. Update the order status in Seller Hub from 'RTO IN TRANSIT' to 'SETTLED — LOST'.
3. Confirm within 7 working days as per SPF SLA.

If not resolved within the SLA window, I will escalate this to the Flipkart Seller Grievance Officer and pursue legal remedy under the Consumer Protection Act 2019 and the Digital India Act 2018.

Sincerely,
[Your Name]
[Your Registered Business]
[Registered Address]
[GSTIN]
Seller ID: [Seller ID]
"""
    if context.marketplace == Marketplace.MEESHO:
        return f"""Subject: Lost RTO / Undelivered Return — AWB #{context.awb_number} — Claim for Rs.{context.claimed_amount}

Dear Meesho Seller Support Team,

I am filing a formal claim under the Meesho Seller Dispute Resolution Policy for the reverse shipment bearing AWB {context.awb_number}, which has been in transit for over {days} days without delivery to my registered warehouse.

FACTS:
1. The buyer initiated a return request on or around {d_init}.
2. The forward order was delivered successfully.
3. The RTO package has not been returned to my warehouse.
4. No reverse shipment credit appears in my Meesho Seller app / settlement wallet.
5. Ticket #{ticket} raised with Meesho Support on {d_init}.

MEESHO CLAIMS POLICY — SECTION 5 (Lost & Damaged Reverse Shipments):
Meesho settles full order value + forward shipping credit when a reverse shipment is not traced for over 45 calendar days.

REQUESTED SETTLEMENT: Rs.{context.claimed_amount}, comprising:
- Product value: Rs.{context.invoice_value}
- Forward shipping credit: Rs.[amount]
- Platform fee reversal (if applicable): Rs.[amount]

Kindly close this ticket with a settlement within the SLA of 7 working days. Failure to resolve will result in escalation to Meesho Grievance Officer and the Consumer Affairs Commission.

Regards,
[Your Name]
Meesho Seller ID: [Seller ID]
[Registered Business Address]
[GSTIN]
"""
    if context.marketplace == Marketplace.AMAZON:
        return f"""Subject: SAFE-T Request — AWB #{context.awb_number} — RTO Lost in Transit

Dear Amazon Seller Central Support,

I am submitting a SAFE-T (Seller Appeal Friendly & Efficient Turnaround) request for Order ID {context.awb_number} which is reflected as "Returned to Seller — In Transit" on my seller account, but has not been received at my registered warehouse after {days} days.

FACTS:
1. Original order: {context.awb_number} — {context.product_name} (FBA / MFN)
2. Invoice value: Rs.{context.invoice_value}
3. RTO initiated on or around {d_init}; today is {today}.
4. Tracking shows last scan {days}+ days ago with no delivery attempt.
5. Case ID {ticket} raised.

SAFE-T POLICY:
Under Amazon's FBA / MFN Return Dispute process, undelivered reverse shipments exceeding 45 calendar days are eligible for reimbursement of the full order amount plus outbound fulfilment fees.

REQUESTED ACTION:
1. Post a SAFE-T settlement of Rs.{context.claimed_amount} to my bank account on file.
2. Close case {ticket} as "Lost in Transit".
3. Credit any applicable storage / fulfilment fee waiver.

I confirm that the item is not in my possession and will not file a duplicate claim.

Regards,
[Your Name]
Merchant ID: [Merchant ID]
[Registered Business Address]
[GSTIN]
"""
    return f"""Subject: Claim for Lost RTO — AWB #{context.awb_number} — Rs.{context.claimed_amount}

Dear Seller Support Team,

I am filing a claim for order {context.awb_number}, which has not been returned to my warehouse despite the buyer's return being initiated.

FACTS:
- Product: {context.product_name}
- Invoice value: Rs.{context.invoice_value}
- Claimed amount: Rs.{context.claimed_amount}
- Days in transit: {days}

Kindly resolve within the marketplace's stated SLA.

Regards,
[Your Name]
"""


def _template_weight_fraud(context: ClaimContext, today: str) -> str:
    dead = context.dead_weight_g or 0
    vol = context.volumetric_weight_g or 0
    charged = context.courier_charged_g or max(dead, vol, 0)
    billable = max(dead, vol)
    overcharge_g = max(charged - billable, 0)
    return f"""Subject: Courier Charge Overbilling — AWB #{context.awb_number} — Recharge Demand of Rs.{context.claimed_amount}

Dear [Courier Partner / Marketplace Support],

I am writing to formally dispute the courier charges levied on order {context.awb_number} for the product {context.product_name}.

WEIGHT RECONCILIATION:
- Dead weight (as recorded at pickup): {dead} g
- Volumetric weight (Length x Breadth x Height / 5000): {vol} g
- Billable weight per courier slab rules: max(Dead, Volumetric) = {billable} g
- Weight charged by courier: {charged} g
- Excess weight charged (unjustified): {overcharge_g} g

This constitutes an overcharge of {overcharge_g} grams billed to me, resulting in an unjustified additional cost of Rs.{context.claimed_amount}.

POLICY BASIS:
- Indian courier industry standard: billable weight = max(dead weight, volumetric weight).
- [Courier's] Tariff Circular (FY {today[:4]}) — charges must be calculated on billable weight, not on any inflated variant.
- Marketplace Fulfilment Partner SOP — any weight discrepancy > 20% is subject to recharge within 30 days of settlement.

SUPPORTING EVIDENCE ATTACHED:
1. Packing photo with digital weighing scale reading: {dead} g
2. Packing dimensions measurement: [L] x [B] x [H] cm
3. Courier invoice / AWB showing charged weight {charged} g
4. Marketplace order export — settlement showing deducted amount

REQUESTED ACTION:
1. Reverse Rs.{context.claimed_amount} as an immediate recharge to my settlement.
2. Correct the weight record for AWB {context.awb_number} in the fulfilment partner system.
3. Issue an audit note if this is a systemic issue affecting other AWBs.

Kindly resolve within 7 working days as per the Marketplace SOP for weight disputes.

Regards,
[Your Name]
Seller ID: [Seller ID]
[GSTIN]
"""


def _template_damaged(context: ClaimContext, today: str) -> str:
    return f"""Subject: Damaged Return Not Reimbursed — AWB #{context.awb_number} — Rs.{context.claimed_amount}

Dear Seller Support Team,

I am filing a claim for the return shipment bearing AWB {context.awb_number} (product: {context.product_name}), which arrived at my warehouse in damaged / non-resalable condition on or before {today}.

FACTS:
1. Original order was delivered successfully.
2. Buyer returned the item citing [reason].
3. Upon unboxing at my warehouse, the item was found damaged and unfit for resale.
4. I have filed a damaged-return claim via the Seller Hub / Seller App within the 7-day window.
5. No reimbursement has been posted to my settlement for Rs.{context.claimed_amount}.

POLICY BASIS:
Under the marketplace's Damaged Returns Policy, when an RTO item arrives damaged and unfit for resale, the seller is entitled to the full invoice value (Rs.{context.invoice_value}) plus forward shipping credit, less any mandatory platform fee reversal.

SUPPORTING EVIDENCE:
1. Unboxing video (attached)
2. Photos of damage (attached)
3. AWB {context.awb_number} pickup confirmation
4. Damaged return claim ticket #[Ticket Number]

REQUESTED ACTION:
1. Process Rs.{context.claimed_amount} as a damaged-return credit to my settlement wallet.
2. Mark the item as "Damaged — Not Resalable" in my RTO inventory.
3. Confirm resolution within the marketplace's SLA.

Regards,
[Your Name]
Seller ID: [Seller ID]
[GSTIN]
"""


def _template_courier_weight(context: ClaimContext, today: str) -> str:
    """Same as weight fraud template, addressed directly to the courier."""
    return _template_weight_fraud(context, today)
