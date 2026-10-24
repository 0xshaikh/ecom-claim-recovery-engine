"""Streamlit dashboard for the EcoClaim.

Imports from `core.recon_engine`, `core.exporter`, and `generate_sample_data`.
Video Cutter and Claim Notes tabs degrade gracefully if the underlying modules
are unavailable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# --- Load .env (optional, non-fatal) ----------------------------------------
# If the user drops a .env file at the repo root, we'll pick up API keys from it.
# This lets a fresh clone work out of the box: copy .env.example -> .env,
# fill in keys, run streamlit.
try:
    from dotenv import load_dotenv
    # Load from repo root (where this file lives) and cwd.
    _REPO_ROOT = Path(__file__).resolve().parent
    load_dotenv(_REPO_ROOT / ".env", override=False)
    load_dotenv(override=False)  # also pick up cwd .env
except Exception:
    # python-dotenv missing — still works, user can export vars manually.
    pass

# Ensure the repo root is importable when launched from anywhere.
sys.path.insert(0, ".")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- Import core modules with graceful degradation --------------------------

RECON_AVAILABLE = False
EXPORTER_AVAILABLE = False
SAMPLE_AVAILABLE = False
CLAIM_AI_AVAILABLE = False
VIDEO_ENGINE_AVAILABLE = False

try:
    from core.recon_engine import run_reconciliation  # type: ignore
    RECON_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _RECON_IMPORT_ERROR = _exc

try:
    from core.exporter import export_report  # type: ignore
    EXPORTER_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _EXPORTER_IMPORT_ERROR = _exc

try:
    import generate_sample_data  # type: ignore
    SAMPLE_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _SAMPLE_IMPORT_ERROR = _exc

try:
    from core.claim_ai import (  # type: ignore
        ClaimContext,
        ClaimType,
        Marketplace,
        generate_claim_note,
    )
    CLAIM_AI_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _CLAIM_IMPORT_ERROR = _exc

try:
    from core.video_engine import VideoEngine  # type: ignore
    VIDEO_ENGINE_AVAILABLE = True
except Exception as _exc:  # noqa: BLE001
    _VIDEO_IMPORT_ERROR = _exc


# --------------------------------------------------------------------------- #
# Page config
# --------------------------------------------------------------------------- #

st.set_page_config(
    page_title="EcoClaim",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Dark theme tweaks via inline CSS.
st.markdown(
    """
    <style>
    .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 1400px; }
    .metric-card { padding: 0.4rem; }
    div[data-testid="stMetric"] { background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; padding: 14px; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------- #
# Formatting helpers
# --------------------------------------------------------------------------- #

def _fmt_rupee(amount) -> str:
    """Format as Indian Rupees."""
    try:
        return f"₹{int(float(amount)):,}"
    except (TypeError, ValueError):
        return "₹0"


def _recon_color(amount: int) -> str:
    if amount >= 10_000:
        return "red"
    if amount >= 1_000:
        return "orange"
    return "green"


# --------------------------------------------------------------------------- #
# Sidebar — data loading controls
# --------------------------------------------------------------------------- #

SAMPLE_DATA_DIR = Path("sample_data").resolve()
OUTPUT_DIR = Path("output").resolve()
OUTPUT_DIR.mkdir(exist_ok=True)

with st.sidebar:
    st.markdown("### EcoClaim")
    st.caption("India Marketplace Audit Tool · Flipkart · Meesho · Amazon")
    st.divider()

    st.markdown("**📊 Sample Data**")
    if SAMPLE_AVAILABLE:
        if st.button("🎯 Load Sample Data (200 orders)", use_container_width=True):
            with st.spinner("Generating sample data…"):
                try:
                    generate_sample_data.main()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Sample data generation failed: {exc}")
            st.success("Sample data generated.")
            st.rerun()
    else:
        st.warning("generate_sample_data not available.")

    st.markdown("---")
    st.markdown("**📁 Upload Custom CSVs (optional)**")

    orders_up = st.file_uploader("Orders CSV", type=["csv"], key="orders_up")
    settlement_up = st.file_uploader("Settlement CSV", type=["csv"], key="settlement_up")
    sku_up = st.file_uploader("SKU Master CSV", type=["csv"], key="sku_up")

    def _stage(uploaded, filename: str) -> Optional[str]:
        if uploaded is None:
            return None
        out = OUTPUT_DIR / filename
        out.write_bytes(uploaded.getvalue())
        return str(out)

    orders_path: Optional[str] = _stage(orders_up, "custom_orders.csv")
    settlement_path: Optional[str] = _stage(settlement_up, "custom_settlement.csv")
    sku_path: Optional[str] = _stage(sku_up, "custom_sku_master.csv")

    # Fallback to sample files if they exist.
    sample_orders = SAMPLE_DATA_DIR / "orders_sample.csv"
    sample_settlement = SAMPLE_DATA_DIR / "settlement_sample.csv"
    sample_sku = SAMPLE_DATA_DIR / "sku_master_sample.csv"

    if orders_path is None and sample_orders.exists():
        orders_path = str(sample_orders)
    if settlement_path is None and sample_settlement.exists():
        settlement_path = str(sample_settlement)
    if sku_path is None and sample_sku.exists():
        sku_path = str(sample_sku)

    st.markdown("---")
    can_run = RECON_AVAILABLE and all([orders_path, settlement_path, sku_path])
    run_clicked = st.button(
        "🚀 Run Reconciliation",
        use_container_width=True,
        type="primary",
        disabled=not can_run,
    )
    if run_clicked and can_run:
        st.session_state["recon_requested"] = True

    if not can_run:
        missing = []
        if not RECON_AVAILABLE:
            missing.append("recon_engine")
        if not orders_path:
            missing.append("orders CSV")
        if not settlement_path:
            missing.append("settlement CSV")
        if not sku_path:
            missing.append("SKU master CSV")
        st.caption("Waiting for: " + ", ".join(missing))

    st.markdown("---")
    st.caption("v0.1.0 · MIT · github.com/0xshaikh")


# --------------------------------------------------------------------------- #
# Run reconciliation (cached)
# --------------------------------------------------------------------------- #

@st.cache_data(show_spinner=False)
def _cached_recon(orders: str, settlement: str, sku: str) -> dict:
    return run_reconciliation(orders, settlement, sku)


recon_result: Optional[dict] = None

if st.session_state.get("recon_requested") and can_run:
    with st.spinner("Running reconciliation…"):
        try:
            recon_result = _cached_recon(orders_path, settlement_path, sku_path)
            st.session_state["recon_result"] = recon_result
        except Exception as exc:  # noqa: BLE001
            st.error(f"Reconciliation failed: {exc}")

if recon_result is None:
    recon_result = st.session_state.get("recon_result")

st.session_state.pop("recon_requested", None)


# --------------------------------------------------------------------------- #
# Tabs
# --------------------------------------------------------------------------- #

tab_home, tab_weight, tab_lost, tab_damaged, tab_video, tab_claim = st.tabs(
    [
        "🏠 Home / Overview",
        "⚖️ Weight Fraud",
        "📦 Lost RTO",
        "🔧 Damaged Returns",
        "🎬 Video Cutter",
        "✍️ Claim Notes",
    ]
)


# --------------------------------------------------------------------------- #
# HOME TAB
# --------------------------------------------------------------------------- #

with tab_home:
    st.markdown("# EcoClaim")
    st.markdown(
        "Recover hidden courier weight fraud, lost RTOs, and unpaid damaged returns "
        "across Flipkart, Meesho and Amazon marketplaces."
    )

    if recon_result is None:
        st.info(
            "👈 Load sample data (or upload CSVs) and press **🚀 Run Reconciliation** in the sidebar."
        )
        st.stop() if False else None

    summary = recon_result["summary"]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric(
            "Total Recoverable",
            _fmt_rupee(summary["total_recoverable"]),
            delta=f"{summary['total_orders']} orders scanned",
            delta_color=_recon_color(summary["total_recoverable"]),
        )
    with c2:
        st.metric(
            "Weight Fraud",
            _fmt_rupee(summary["weight_fraud_amount"]),
            delta=f"{summary['weight_fraud_count']} cases",
            delta_color="inverse",
        )
    with c3:
        st.metric(
            "Lost RTO",
            _fmt_rupee(summary["lost_rto_amount"]),
            delta=f"{summary['lost_rto_count']} AWBs",
            delta_color="inverse",
        )
    with c4:
        st.metric(
            "Unpaid Damaged",
            _fmt_rupee(summary["unpaid_damaged_amount"]),
            delta=f"{summary['unpaid_damaged_count']} items",
            delta_color="inverse",
        )

    st.divider()

    # Recoverable amount by recon type
    type_labels = [
        ("Weight Fraud", summary["weight_fraud_amount"]),
        ("Lost RTO", summary["lost_rto_amount"]),
        ("Unpaid Damaged", summary["unpaid_damaged_amount"]),
    ]
    df_type = pd.DataFrame({"Recon_Type": [t[0] for t in type_labels],
                            "Claimable_Amount": [t[1] for t in type_labels]})
    fig = px.bar(
        df_type, x="Claimable_Amount", y="Recon_Type", orientation="h",
        color="Claimable_Amount", color_continuous_scale="Spectral",
        title="Recoverable Amount by Recon Type (₹)",
    )
    fig.update_layout(template="plotly_dark", height=320, xaxis_title="₹")
    st.plotly_chart(fig, use_container_width=True)

    # By marketplace
    all_df = pd.concat(
        [recon_result["weight_fraud"], recon_result["lost_rto"], recon_result["unpaid_damaged"]]
    )
    if not all_df.empty:
        df_mkt = all_df.groupby("Marketplace", dropna=False)["Claimable_Amount"].sum().reset_index()
        fig2 = px.bar(df_mkt, x="Marketplace", y="Claimable_Amount",
                      color="Marketplace",
                      title="Recoverable Amount by Marketplace (₹)")
        fig2.update_layout(template="plotly_dark", height=320, yaxis_title="₹")
        st.plotly_chart(fig2, use_container_width=True)

        # By zone
        df_zone = all_df.groupby("Zone", dropna=False)["Claimable_Amount"].sum().reset_index()
        fig3 = px.bar(df_zone, x="Zone", y="Claimable_Amount", color="Zone",
                      title="Recoverable Amount by Zone (₹)")
        fig3.update_layout(template="plotly_dark", height=320, yaxis_title="₹")
        st.plotly_chart(fig3, use_container_width=True)

        st.markdown("#### 🏆 Top 10 Biggest Claims")
        top_cols = ["AWB_Number", "Marketplace", "Product_Name", "Zone",
                    "Recon_Type", "Invoice_Value", "Claimable_Amount"]
        top_cols = [c for c in top_cols if c in all_df.columns]
        st.dataframe(
            all_df[top_cols].sort_values("Claimable_Amount", ascending=False).head(10),
            use_container_width=True,
        )

        st.divider()
        if EXPORTER_AVAILABLE:
            out_path = "output/claim_recovery_report.xlsx"

            def _do_export():
                return export_report(recon_result, out_path)

            try:
                with st.spinner("Building Excel report…"):
                    path = _do_export()
                with open(path, "rb") as f:
                    st.download_button(
                        "📥 Download Complete Report (.xlsx)",
                        data=f.read(),
                        file_name=Path(path).name,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        type="primary",
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Export failed: {exc}")
        else:
            st.warning("Exporter not available in this environment.")
    else:
        st.info("No claimable rows detected in this dataset.")


# --------------------------------------------------------------------------- #
# WEIGHT FRAUD TAB
# --------------------------------------------------------------------------- #

with tab_weight:
    st.markdown("## ⚖️ Weight Fraud — Courier Charge Over-Billing")
    st.markdown(
        """
        Couriers charge shipping based on **billable weight = max(dead weight, volumetric weight)**.
        When a parcel is billed at a weight **materially above** what the SKU dimensions allow,
        the difference between the charged fee and the expected slab fee is recoverable.

        This engine flags rows where courier-charged weight exceeds billable weight by more than
        **15 %** and calculates the recoverable amount.
        """
    )

    if recon_result is None:
        st.info("Run reconciliation first.")
    else:
        wf = recon_result["weight_fraud"]
        if wf.empty:
            st.success("No weight-fraud rows detected. 🎉")
        else:
            st.markdown(f"**{len(wf)} cases · ₹{int(wf['Claimable_Amount'].sum()):,} recoverable**")
            st.dataframe(wf, use_container_width=True)

            show_cols = ["Dead_Weight_g", "Billable_Weight_g",
                         "Weight_Charged_by_Courier_g", "Claimable_Amount"]
            show_cols = [c for c in show_cols if c in wf.columns]
            if all(c in wf.columns for c in ["Billable_Weight_g", "Weight_Charged_by_Courier_g"]):
                fig = go.Figure(go.Scatter(
                    x=wf["Billable_Weight_g"],
                    y=wf["Weight_Charged_by_Courier_g"],
                    mode="markers",
                    text=wf["AWB_Number"],
                    hovertext=wf["Claimable_Amount"].apply(lambda v: f"Recoverable: ₹{int(v):,}"),
                    marker=dict(
                        size=wf["Claimable_Amount"].clip(lower=20).astype(float),
                        color=wf["Claimable_Amount"],
                        colorscale="Spectral",
                        opacity=0.85,
                    ),
                ))
                fig.add_shape(
                    type="line", x0=0, y0=0, x1=wf["Weight_Charged_by_Courier_g"].max() * 1.1,
                    y1=wf["Weight_Charged_by_Courier_g"].max() * 1.1,
                    line=dict(dash="dash", color="rgba(255,255,255,0.4)"),
                )
                fig.update_layout(
                    template="plotly_dark", height=420,
                    xaxis_title="Actual Billable Weight (g)",
                    yaxis_title="Weight Charged by Courier (g)",
                    title="Charged vs Actual Billable Weight (size = overcharge)",
                )
                st.plotly_chart(fig, use_container_width=True)


# --------------------------------------------------------------------------- #
# LOST RTO TAB
# --------------------------------------------------------------------------- #

with tab_lost:
    st.markdown("## 📦 Lost RTO — 45+ Day Untracked Returns")
    st.markdown(
        "Returns in transit for more than 45 calendar days without physical receipt are treated "
        "as **Lost RTO** and are eligible for full invoice-value recovery under marketplace policies."
    )

    if recon_result is None:
        st.info("Run reconciliation first.")
    else:
        lr = recon_result["lost_rto"]
        if lr.empty:
            st.success("No lost-RTO rows detected. 🎉")
        else:
            st.markdown(f"**{len(lr)} AWBs · ₹{int(lr['Claimable_Amount'].sum()):,} recoverable**")
            st.dataframe(lr, use_container_width=True)

            if "Days_In_Transit" in lr.columns:
                fig = go.Figure()
                days = lr["Days_In_Transit"]
                over45 = days > 45
                fig.add_trace(go.Histogram(
                    x=days[~over45].dropna(), name="≤ 45 days",
                    marker_color="#4CAF50",
                ))
                fig.add_trace(go.Histogram(
                    x=days[over45].dropna(), name="> 45 days (LOST)",
                    marker_color="#E53935",
                ))
                fig.update_layout(
                    template="plotly_dark", height=380, barmode="overlay",
                    xaxis_title="Days in Transit", yaxis_title="Count",
                    title="Days in Transit Distribution (red = lost, >45d)",
                )
                st.plotly_chart(fig, use_container_width=True)

            if not lr.empty:
                st.markdown("#### Unreconciled AWBs")
                unreconciled = lr[["AWB_Number", "Marketplace", "Product_Name",
                                   "Order_Status", "Days_In_Transit", "Claimable_Amount"]]
                st.dataframe(unreconciled, use_container_width=True)


# --------------------------------------------------------------------------- #
# DAMAGED RETURNS TAB
# --------------------------------------------------------------------------- #

with tab_damaged:
    st.markdown("## 🔧 Unpaid Damaged Returns")
    st.markdown(
        "Customer returns that arrive damaged and are not compensated via bank settlement. "
        "Eligible for 90 % of invoice value recovery."
    )

    if recon_result is None:
        st.info("Run reconciliation first.")
    else:
        ud = recon_result["unpaid_damaged"]
        if ud.empty:
            st.success("No unpaid-damaged rows detected. 🎉")
        else:
            st.markdown(f"**{len(ud)} items · ₹{int(ud['Claimable_Amount'].sum()):,} recoverable**")
            show_cols = ["AWB_Number", "Marketplace", "Product_Name",
                         "Invoice_Value", "Claimable_Amount"]
            show_cols = [c for c in show_cols if c in ud.columns]
            st.dataframe(ud[show_cols], use_container_width=True)


# --------------------------------------------------------------------------- #
# VIDEO CUTTER TAB
# --------------------------------------------------------------------------- #

with tab_video:
    st.markdown("## 🎬 Warehouse Video Barcode Cutter")
    st.markdown(
        "Upload a warehouse unpacking video. The engine will detect AWB barcodes "
        "frame-by-frame using **pyzbar + OpenCV**, and slice per-AWB clips for claim evidence."
    )

    video_file = st.file_uploader(
        "Unpacking video", type=["mp4", "mov", "avi", "mkv"], key="video_up"
    )

    if not VIDEO_ENGINE_AVAILABLE:
        st.warning(f"Video engine not available: {_VIDEO_IMPORT_ERROR!r}")
    else:
        if video_file is not None:
            clip_dir = OUTPUT_DIR / "video_source"
            clip_dir.mkdir(parents=True, exist_ok=True)
            local_path = clip_dir / video_file.name
            local_path.write_bytes(video_file.getvalue())

            sample_every = st.slider(
                "Frame sampling interval", min_value=1, max_value=60, value=15, step=1
            )

            if st.button("🎯 Detect AWB ranges", type="primary", use_container_width=True):
                with st.spinner("Scanning video frames for barcodes…"):
                    engine = VideoEngine(str(local_path), str(OUTPUT_DIR / "video_clips"))
                    ranges = engine.detect_barcode_ranges(sample_every=sample_every)
                    ranges = engine.slice_clips(ranges)
                    ranges = engine.extract_snapshots(ranges)
                    st.session_state["video_ranges"] = ranges

            ranges = st.session_state.get("video_ranges", [])
            if ranges:
                st.markdown("### Detected clips")
                df = pd.DataFrame([
                    {
                        "AWB": c.awb_number,
                        "Start (s)": round(c.start_time, 2),
                        "End (s)": round(c.end_time, 2),
                        "Duration (s)": round(c.duration, 2),
                        "Size (MB)": round(c.size_mb, 2),
                        "Clip": c.clip_path or "—",
                        "Snapshots": len(c.snapshot_paths),
                    }
                    for c in ranges
                ])
                st.dataframe(df, use_container_width=True)
        else:
            st.info("No video uploaded. The engine uses a deterministic mock fallback for testing.")

            if st.button("🔍 Try mock detection (no video needed)"):
                engine = VideoEngine("nonexistent.mp4", str(OUTPUT_DIR / "video_clips"))
                ranges = engine.detect_barcode_ranges()
                st.session_state["video_ranges"] = ranges

            ranges = st.session_state.get("video_ranges", [])
            if ranges:
                st.markdown("### Mock detection results")
                st.dataframe(
                    pd.DataFrame([
                        {"AWB": c.awb_number,
                         "Start (s)": c.start_time,
                         "End (s)": c.end_time,
                         "Size (MB)": c.size_mb}
                        for c in ranges
                    ]),
                    use_container_width=True,
                )

        st.markdown("#### Expected output directory")
        st.code(
            """output/video_clips/
├── FLK001234.mp4        # sliced per-AWB clip
├── MSH005678.mp4
├── AMZ009012.mp4
└── snapshots/
    ├── FLK001234_1.jpg  # start / label
    ├── FLK001234_2.jpg  # middle / package
    ├── FLK001234_3.jpg  # end / product
    ├── MSH005678_1.jpg
    └── ...""",
            language="text",
        )
        st.caption(
            "**Prerequisites for real detection:** `pip install pyzbar opencv-python` "
            "and `ffmpeg` on PATH (e.g. `apt-get install ffmpeg libzbar0`)."
        )


# --------------------------------------------------------------------------- #
# CLAIM NOTES TAB
# --------------------------------------------------------------------------- #

with tab_claim:
    st.markdown("## ✍️ AI Claim Note Generator")
    st.markdown(
        "Select an AWB and marketplace, then generate a policy-compliant claim note "
        "for Flipkart SPF, Meesho, Amazon SAFE-T, or a courier weight dispute."
    )

    if not CLAIM_AI_AVAILABLE:
        st.warning(f"claim_ai not available: {_CLAIM_IMPORT_ERROR!r}")
        st.stop()

    left, right = st.columns([1, 1])

    with left:
        # Populate the AWB picker from recon results when available.
        awb_options: list[str] = []
        awb_lookup: dict[str, dict] = {}
        if recon_result is not None:
            for key, ctype in [
                ("weight_fraud", ClaimType.WEIGHT_FRAUD),
                ("lost_rto", ClaimType.LOST_RTO),
                ("unpaid_damaged", ClaimType.DAMAGED_RETURN),
            ]:
                df_k = recon_result[key]
                for row in df_k.itertuples(index=False):
                    d = row._asdict()
                    awb = d.get("AWB_Number")
                    if not awb or awb in awb_lookup:
                        continue
                    awb_options.append(awb)
                    awb_lookup[awb] = {**d, "_claim_type": ctype}

        awb_choice = st.selectbox(
            "Select AWB (from recon results)",
            options=["(type manually)"] + awb_options,
        )
        awb_input = awb_choice if awb_choice != "(type manually)" else st.text_input(
            "AWB number", value="FLK001234"
        )

        marketplace_choice = st.selectbox(
            "Marketplace",
            options=[m.value for m in Marketplace],
            key="mkt_choice",
        )
        marketplace = Marketplace(marketplace_choice)

        if awb_choice in awb_lookup:
            row = awb_lookup[awb_choice]
            default_type = row.get("_claim_type", ClaimType.LOST_RTO)
            product = str(row.get("Product_Name", "—"))
            invoice = int(row.get("Invoice_Value", 0) or 0)
            claimed = int(row.get("Claimable_Amount", 0) or 0)
            days = row.get("Days_In_Transit")
            days = int(days) if pd.notna(days) else None
            dead_w = int(row.get("Dead_Weight_g", 0) or 0) or None
            vol_w = int(row.get("Volume_Weight_g", 0) or 0) or None
            ch_w = int(row.get("Weight_Charged_by_Courier_g", 0) or 0) or None
        else:
            default_type = ClaimType.LOST_RTO
            product = "—"
            invoice = 0
            claimed = 0
            days = None
            dead_w = vol_w = ch_w = None

        claim_type = st.selectbox(
            "Claim type",
            options=[c.value for c in ClaimType],
            index=[c.value for c in ClaimType].index(default_type.value),
        )

        product_input = st.text_input("Product name", value=product)
        invoice_input = st.number_input("Invoice value (₹)", min_value=0, step=100,
                                        value=invoice)
        claimed_input = st.number_input("Claimed amount (₹)", min_value=0, step=100,
                                        value=claimed)
        if claim_type == ClaimType.LOST_RTO:
            days_input = st.number_input(
                "Days in transit", min_value=1, value=days if days else 48
            )
        else:
            days_input = days
        dead_input = st.number_input("Dead weight (g)", min_value=0,
                                     value=dead_w if dead_w else 0)
        vol_input = st.number_input("Volumetric weight (g)", min_value=0,
                                    value=vol_w if vol_w else 0)
        ch_input = st.number_input("Courier-charged weight (g)", min_value=0,
                                   value=ch_w if ch_w else 0)

    with right:
        if st.button("✍️ Generate Claim Note", type="primary", use_container_width=True):
            ctx = ClaimContext(
                awb_number=str(awb_input).strip() or "UNKNOWN",
                marketplace=marketplace,
                claim_type=ClaimType(claim_type),
                product_name=product_input,
                invoice_value=int(invoice_input),
                claimed_amount=int(claimed_input),
                dead_weight_g=int(dead_input) or None,
                volumetric_weight_g=int(vol_input) or None,
                courier_charged_g=int(ch_input) or None,
                days_in_transit=days_input,
                snapshot_paths=[],
            )
            with st.spinner("Drafting claim note…"):
                try:
                    note = generate_claim_note(ctx)
                except Exception as exc:  # noqa: BLE001
                    note = f"❌ Generation failed: {exc}"
                st.session_state["claim_note"] = note

        note = st.session_state.get("claim_note")
        if note:
            st.markdown("### Generated Claim Note")
            st.text_area("Claim note", value=note, height=400, key="claim_out")
            st.download_button(
                "📥 Download as .txt",
                data=note.encode("utf-8"),
                file_name=f"claim_{str(awb_input).strip() or 'draft'}.txt",
                mime="text/plain",
                use_container_width=True,
            )
