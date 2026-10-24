# Usage Guide

Step-by-step walkthrough for getting value from the EcoClaim.

---

## 1. Install

```bash
git clone https://github.com/0xshaikh/ecom-claim-recovery-engine
cd ecom-claim-recovery-engine
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Requires Python 3.10+. Optional extras:

- `ffmpeg` + `pyzbar` — needed only for the real video-barcode path.
- `google-genai` + a `GEMINI_API_KEY` — optional; claim notes fall back to built-in templates without it.

Verify:

```bash
python -c "import pandas, streamlit, plotly, openpyxl; print('ok')"
```

## 2. Generate sample data

```bash
python generate_sample_data.py
```

Creates 200 sample orders under `sample_data/` with three leakage classes baked in:

- **35** courier weight-fraud parcels
- **25** lost RTO returns (>45 days in transit)
- **15** unpaid damaged returns

These let you see the dashboard working without exporting any portal data first.

## 3. Run the Streamlit app

```bash
streamlit run app.py
```

A browser tab opens on `http://localhost:8501`.

## 4. Load sample data

1. In the **sidebar**, click **🎯 Load Sample Data (200 orders)**.
2. This calls `generate_all()` and writes the three CSVs into `sample_data/`.
3. To use your own data instead, upload your Orders CSV, Settlement CSV, and SKU Master CSV into the three file uploaders in the sidebar.
4. Click **🚀 Run Reconciliation**.

A spinner shows while the three engines run. Results are cached with `@st.cache_data`, so re-running with the same inputs is instant.

## 5. Navigate the tabs

| Tab | What you see |
| --- | --- |
| **Overview** | 4 KPI cards (total recoverable, weight fraud, lost RTO, unpaid damaged), breakdowns by recon type / marketplace / zone, top 10 claims, and the Excel download button. |
| **Weight Fraud** | Full table of over-charged parcels, a scatter of charged vs. actual billable weight (bubble size = overcharge), and a note explaining courier billing slabs. |
| **Lost RTO** | Table of unreconciled AWBs, a histogram of days-in-transit with >45 days highlighted, and the list of AWBs to pursue. |
| **Damaged Returns** | Table of unpaid damaged returns with AWB, product, and claimable amount. |
| **Video Cutter** | Upload an unpacking video; the engine detects AWB barcodes frame-by-frame and slices per-AWB clips with keyframe snapshots. Falls back to a demo mode without `ffmpeg`/`pyzbar`. |
| **Claim Notes** | Pick an AWB from any claim table, choose a marketplace, and generate a policy-compliant claim draft. Copy to clipboard and paste into the seller hub. |

## 6. Download the report

On the **Overview** tab, click **📥 Download Complete Report (.xlsx)**.

The workbook contains:

- An executive-summary sheet (KPIs, breakdowns).
- One detail sheet per recon type with every claimable AWB, its computed claim amount, and the evidence columns used to compute it.

Send this to your seller client as the audit-ready deliverable.

## 7. Use the video cutter

**Prerequisites:** `ffmpeg` and `pyzbar` must be installed.

```bash
# macOS
brew install ffmpeg
pip install pyzbar

# Ubuntu/Debian
sudo apt install ffmpeg libzbar0
pip install pyzbar
```

Without these, the tab runs in demo mode: it shows the expected output directory structure and uses deterministic mock clips so the UI remains testable.

1. Upload an unpacking video.
2. The engine samples every Nth frame, decodes barcodes with `pyzbar`, and groups consecutive frames into per-AWB ranges.
3. `ffmpeg` slices each range into its own MP4 under `output/video_clips/`.
4. Three keyframe JPEGs are extracted per AWB: label-visible, package, product-visible — stored under `output/video_clips/snapshots/`.

The snapshots attach directly to the claim notes as evidence.

## 8. Generate claim notes

1. Open the **Claim Notes** tab.
2. Select an AWB from the dropdown (populated from weight-fraud, lost-RTO, and damaged-returns tables).
3. Pick the marketplace / dispute type:
   - Flipkart SPF (lost RTO, damaged return)
   - Meesho (claims policy)
   - Amazon SAFE-T (FBA return discrepancy)
   - Courier Weight Dispute (Shiprocket / Delhivery / etc. slab calculation)
4. Click **✍️ Generate Claim Note**.
5. The draft appears in the textarea. Use the copy button and paste into the seller-hub dispute form.

If `GEMINI_API_KEY` is set in your environment, notes are generated with Gemini 2.5 Flash; otherwise the built-in templates run deterministically and require no network call. Every template is marketplace-specific and cites the relevant policy section (SPF, Meesho Claims Policy, SAFE-T, or the courier's tariff card).

## Next steps

- **Invoice your client** a fixed fee or 20% commission on recovered value.
- **Re-run weekly** on fresh portal exports to catch new leakage.
- **File claims via the portal** using the generated notes; track SLA dates (usually 7 working days).
