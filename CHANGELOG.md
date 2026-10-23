# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-10-23

### Added

- CSV reconciliation engine detecting three leakage classes:
  - Courier weight-fraud slab overcharges (recomputed dead + volumetric weight per SKU)
  - Lost RTO returns in transit beyond 45 days with no reverse settlement
  - Unpaid damaged returns with forward shipping already paid by the seller
- Rate card module for Indian marketplace couriers (Flipkart, Meesho, Amazon) with dead-weight and volumetric-weight billing slabs.
- Excel report exporter producing an executive-summary sheet plus per-AWB claim detail tabs.
- Streamlit dashboard with KPI cards, Plotly breakdowns (by recon type, marketplace, zone), and a top-10 claims table.
- Warehouse video barcode splitter engine with a pyzbar/ffmpeg real path and a deterministic mock fallback for environments lacking those dependencies.
- AI claim-note drafter with marketplace-specific templates (Flipkart SPF, Meesho Claims Policy, Amazon SAFE-T, Courier Weight Dispute) and an optional Gemini-powered path that falls back to templates when no API key is configured.
- Sample data generator producing 200 orders with 35 weight-fraud, 25 lost-RTO, and 15 unpaid-damaged cases.
- Marketing site under `website/index.html`, GitHub Actions CI, issue/PR templates, code of conduct, and security policy.

### Documentation

- README, USAGE_GUIDE, CONTRIBUTING, SECURITY, LICENSE (MIT, 2026).

[0.1.0]: https://github.com/0xshaikh/ecom-claim-recovery-engine/releases/tag/v0.1.0
