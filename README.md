# HVAC Field Estimator
> A 4-step quote tool for HVAC field technicians, optimized for mobile and tablet use in the field. Select a customer, build a parts and labor estimate, and generate a printable quote — in under 2 minutes.

## Author(s)
Serena Nguyen

## Demo
[Google Drive Demo Link](https://drive.google.com/file/d/1tydVMUEM5inrMtOmRhLPmAhuaG0JZO3a/view?usp=sharing)

## The Problem
Technicians were spending 10–45 minutes per estimate on-site, manually cross-referencing equipment binders, labor rate sheets, and customer records. Customers waited. Estimates were inconsistent. Jobs were lost to competitors who quoted faster.

This tool puts everything a tech needs in one place, optimized for phone and tablet use in the field — reducing estimate time to under 2 minutes.

## My Approach & Why

The core constraint was speed in the field — technicians need to generate accurate estimates with minimal friction while standing in front of a customer. Every decision in this tool prioritizes reducing time-to-quote while keeping the workflow intuitive and reliable.

While this implementation is optimized for a single-tech workflow, I intentionally avoided introducing a backend at this stage to reduce complexity and ensure reliability in field conditions. If deployed across a 40-tech team, I would prioritize introducing a lightweight backend API for quote syncing and reporting, starting with a simple REST service and shared datastore, and layering in authentication and admin tooling as the system scales.

No framework (vanilla JS) — A React or Vue app would introduce a build step and dependency management. For this use case, a technician or manager should be able to clone the repo and run it immediately. Vanilla JS enables zero setup and instant execution from a static server.

Data pipeline separate from the UI — Pricing changes are a business operation, not a code change. By keeping normalize_data.py as the single source of truth, raw data can be updated and reprocessed without modifying the application logic.

localStorage over a backend — For a single-tech workflow, localStorage provides instant persistence and crash recovery (e.g., refresh, tab close, or device interruption) without requiring network access or infrastructure. In field environments, reliability and speed take priority over cross-device syncing.

4-step guided flow over a single form — Structuring the process as Customer → Equipment → Labor → Quote mirrors how technicians think during a job. This reduces cognitive load and enables natural validation at each step.

Per-category markup in the pipeline — Different equipment categories carry different margins in real HVAC businesses. Applying markup during data normalization ensures pricing reflects real-world practices while keeping the frontend logic simple.

## Getting Started
1. git clone https://github.com/snuwin/Full-Stack-Dev-Test.git
2. cd Full-Stack-Dev-Test
3. python -m http.server 8000
4. Open "http://localhost:8000/hvac_estimator_tool.html" in a browser.

Note: The clean data in data/clean/ is already generated. If you update the raw data in data/, run python normalize_data.py to regenerate it.

## Data Pipeline
Raw JSON files in data/ are normalized by normalize_data.py before the app loads them from data/clean/:
- Standardizes field names (snake_case → camelCase)
- Applies per-category markup to compute _retailPrice for each equipment item
- Flags data quality issues (missing phone, unknown system age, no last service date)
- Embeds tax rate and catalog freshness timestamp into meta.json

#### Run in terminal:
python normalize_data.py

## How It Works

### Header
- Displays catalog freshness date so techs know if pricing is current
- Estimate tab for building new quotes, History tab for saved quotes
- Step progress bar: green = complete, black = current, red = required but incomplete

### Step 1 -- Find Customer
- Full-text search across name, address, and phone number with substring matching and result ranking
- Digit-only search strips formatting so typing 2175550391 matches (217) 555-0391
- Selecting a customer reveals property details: system type, property type, square footage, system age, and last service date
- Systems 15+ years old trigger an advisory warning to discuss system health on the visit
- Customer cards display Commercial and System Age badges for quick visual scanning
- Continue button is disabled until a customer is selected

### Step 2 -- Equipment & Parts Catalog
- Scrollable category filter pills with arrow buttons for mobile navigation
- Full catalog displayed on load — no extra taps needed
- Search by name, brand, or model number
- (+ / −) quantity steppers per item
- Prices reflect per-category markup applied during the data normalization pipeline

### Step 3 -- Labor Charges
- All labor types and rates pulled from labor_rates.json
- Typical min/max hour ranges shown as reference
- Hours adjusted in 0.5 increments via stepper buttons — input is readonly to prevent mobile keyboard
- Live price updates as hours change
- Optional tech notes field for observations and recommendations

### Step 4 -- Build Quote
- Summary cards for Parts, Labor, and Total + Tax
- Pricing tier selector: Standard (full retail), Preferred (10% off), Commercial (13% off)
- Line items with individual removal
- Totals breakdown: subtotal, tax (9.75% Springfield IL), and grand total
- View Printable Quote — formatted receipt modal with copy to clipboard and print/save PDF
- Save & Finalize — saves to local history, resets state, returns to Step 1
- Clear Quote — confirmation modal before wiping the current estimate

### History
- All finalized quotes saved to localStorage
- View, delete per entry, or clear all with confirmation modal
- Timestamps and item summaries per quote

## Planned for V2
- Backend API to sync quotes across devices and technicians
- Per-technician authentication
- Admin panel for updating pricing without code changes
- PWA support for true offline use and home screen install
- Inline quantity editing on the quote screen
- Pagination for larger customer and equipment lists

## Tech Stack
- Vanilla HTML, CSS, JavaScript — no frameworks, no build step
- localStorage for draft persistence and quote history
- Python data normalization pipeline (normalize_data.py)
- Fully functional after git clone with no npm install or build process
