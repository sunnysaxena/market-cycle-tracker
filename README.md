# Market Cycle Tracker

A modular market-analysis application for Indian market indices. The project combines a Python/FastAPI backend, PostgreSQL data storage, and a React/Vite frontend to present historical market data, technical indicators, market structure, market-cycle classifications, and multi-timeframe analysis.

> **Project status:** Backend analytical APIs and the first frontend integration are implemented and verified. The next major phase is visual dashboard development, beginning with interactive candlestick charts and technical-indicator graphs.

---

## 1. Project purpose

Market Cycle Tracker is intended to provide a structured view of market behaviour across multiple Indian indices and timeframes.

The application is designed to:

- Retrieve and display historical OHLCV/index data.
- Present technical indicators calculated and stored by the backend.
- Display confirmed market-structure information, including support and resistance.
- Display market-cycle classifications and their supporting evidence.
- Compare the latest available market state across daily, weekly, monthly, and yearly timeframes.
- Support research, analysis, and future dashboard expansion through modular APIs.

The application is an analysis and decision-support tool. Its classifications are not guaranteed predictions or investment recommendations.

## 2. Supported instruments

### Price indices

- NIFTY50
- BANKNIFTY
- SENSEX
- FINNIFTY
- MIDCPNIFTY

### Volatility index

- INDIA_VIX

`INDIA_VIX` is registered separately as a volatility index. The current Multi-Timeframe Analysis API V1 supports the five price indices; INDIA_VIX is intentionally excluded from that endpoint.

Individual stocks are outside the current project scope. Options data and options-premium analysis are deferred to a future version.

## 3. Supported timeframes

- Daily (`1D`)
- Weekly (`1W`)
- Monthly (`1M`)
- Yearly (`1Y`)

Daily data is the underlying source for higher-timeframe aggregation. Aggregated records are only considered eligible for analysis when their period is completed and their boundary alignment is valid.

The latest period available can differ between timeframes. For example, a yearly record may be older than the latest daily record. The application must display the actual period dates returned by the API rather than implying that all timeframes end on the same date.

## 4. Market-cycle classification

The classification engine uses seven official labels:

1. `ACCUMULATION`
2. `MARKUP`
3. `DISTRIBUTION`
4. `MARKDOWN`
5. `SIDEWAYS_CONSOLIDATION`
6. `TRANSITION_UNCERTAIN`
7. `INSUFFICIENT_DATA`

Important interpretation notes:

- `ACCUMULATION` and `DISTRIBUTION` are price-action heuristics. They do **not** prove institutional buying, selling, or order-flow activity.
- `TRANSITION_UNCERTAIN` represents a state where the available evidence does not support a more decisive classification.
- `INSUFFICIENT_DATA` is a valid classification outcome, not an API failure.
- The API exposes evidence, missing inputs, rule score, classification basis, configuration, and calculation version so that results can be inspected rather than treated as unexplained labels.

Current calculation version audited in PostgreSQL:

`market_cycle_v1.1_confirmed_context`

## 5. Technical indicators

The stored indicator model includes the following groups.

### Moving averages

- EMA 9
- EMA 20
- EMA 50
- EMA 100
- EMA 200
- SMA 222

### Momentum and trend

- RSI 14
- ADX 14
- Positive DI 14 (`+DI`)
- Negative DI 14 (`-DI`)

### MACD

- MACD line (12, 26)
- Signal line (9)
- Histogram

### Volatility and range

- ATR 14
- CHOP 14
- Bollinger Bandwidth (20, 2)
- Bollinger upper, middle, and lower bands (20, 2)

Indicator records can have statuses such as `warming_up`, `partial`, or `ready`. The frontend should preserve and display partial/warming-up records with their status instead of silently removing them.

## 6. Market structure

The market-structure engine stores confirmed swing events and timeframe snapshots.

The API exposes information such as:

- Support and resistance levels.
- Pivot dates and confirmation dates.
- Swing-high and swing-low classifications.
- Market-structure state:
  - `BULLISH`
  - `BEARISH`
  - `MIXED_TRANSITION`
  - `INSUFFICIENT_DATA`
- Breakout status:
  - `NONE`
  - `BULLISH_BREAKOUT`
  - `BEARISH_BREAKDOWN`
  - `BOTH`
- Range position:
  - `INSUFFICIENT_LEVELS`
  - `ABOVE_RESISTANCE`
  - `BELOW_SUPPORT`
  - `WITHIN_SWING_RANGE`

Structure information is joined to other analytical records using the exact composite key: batch, instrument, timeframe, and period start.

## 7. Application architecture

The project is divided into backend and frontend applications.

```text
market-cycle-tracker/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   ├── core/
│   │   ├── engines/
│   │   ├── models/
│   │   ├── schemas/
│   │   └── services/
│   ├── alembic/
│   ├── scripts/
│   ├── tests/
│   └── data/
│       └── reports/
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   ├── components/
│   │   ├── assets/
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── public/
│   ├── package.json
│   └── vite.config.js
└── README.md
```

This is a logical overview, not a promise that every listed folder contains files at every stage. Preserve the actual project structure when adding modules.

### Backend

- Python
- FastAPI
- SQLAlchemy
- PostgreSQL
- Alembic migrations
- Pydantic schemas
- Automated tests

The backend separates API routes, request/response schemas, query services, database models, and analytical engines.

### Frontend

- React
- Vite
- Tailwind CSS
- `lightweight-charts`
- Recharts
- `lucide-react`

The frontend uses a Vite development proxy to forward `/api` requests to the local FastAPI server.

## 8. Backend API V1

All endpoints are under `/api/v1`.

### Index registry

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/indices` | List registered indices; supports `active_only` and `category` filters |
| GET | `/api/v1/indices/{index_id}` | Retrieve an index |
| POST | `/api/v1/indices` | Create an index |
| PATCH | `/api/v1/indices/{index_id}` | Update index details |
| PATCH | `/api/v1/indices/{index_id}/status` | Change active status |

The frontend should use the registry API for instrument selectors. Use the stable index `code` as the selected instrument value; do not hardcode the five indices into the selector.

### Historical market data

`GET /api/v1/market/{instrument}/history`

Returns stored daily or aggregated OHLCV records. The timeframe is required and supports `1D`, `1W`, `1M`, and `1Y`. The endpoint supports date filtering and pagination.

### Technical indicators

`GET /api/v1/market/{instrument}/indicators`

Returns stored indicator records for the selected instrument and timeframe. It is a read-only query endpoint.

### Market structure

`GET /api/v1/market/{instrument}/structure`

Returns market-structure snapshots.

`GET /api/v1/market/{instrument}/structure/events`

Returns swing-high/swing-low structure events.

### Market cycles

`GET /api/v1/market/{instrument}/cycles`

Returns stored market-cycle classifications. It supports timeframe, batch, date, classification, classification-basis, and pagination filters.

### Multi-Timeframe Analysis

`GET /api/v1/market/{instrument}/multi-timeframe`

Returns the latest eligible snapshot for each supported timeframe (`1D`, `1W`, `1M`, `1Y`) for the selected instrument.

- `import_batch_id` is optional.
- If omitted, the service resolves the latest completed batch.
- Each timeframe is selected independently.
- Daily source rows must be accepted.
- Aggregated source rows must be completed and boundary-aligned.
- Indicators, structure, and cycle data are joined using the exact composite key.
- Partial indicator records are retained.
- INDIA_VIX is not supported by this V1 endpoint.

### Health

`GET /api/v1/health`

Returns backend health information.

## 9. Read-only API design rule

Dashboard page loads must not trigger analytical calculations or write operations.

The frontend should read already calculated and persisted records through query services and API endpoints. Existing calculation/persistence services are for controlled data-processing workflows, not for interactive page rendering.

In particular, dashboard requests must not call:

- Indicator calculation/write services.
- Market-structure calculation/write services.
- Market-cycle calculation/write services.

This separation protects data integrity and keeps page loading predictable.

## 10. Current frontend state

The first frontend integration is in place.

### Completed

- Vite `/api` proxy to the local FastAPI server.
- Shared API client at `frontend/src/api/client.js`.
- Dynamic index registry loading.
- Separation of price indices and volatility indices.
- Dashboard cards for the five price indices using API-provided data.
- Multi-Timeframe API requests for the five supported price indices.
- Seven official market-cycle labels in the dashboard.
- Multi-Timeframe Analysis page component at `frontend/src/components/MultiTimeframePage.jsx`.
- Navigation connection from the application shell to the Multi-Timeframe page.
- Loading, error, availability, and no-data states.
- Display of the latest daily, weekly, monthly, and yearly market/indicator/structure/cycle information returned by the API.

The user has visually confirmed that the page displays the available fields and all navigation items. The current UI is functional but requires visual refinement.

### Existing frontend files of particular importance

- `frontend/src/App.jsx` — application shell, navigation, theme state, dashboard and page switching.
- `frontend/src/api/client.js` — API request helper and API functions.
- `frontend/src/components/MultiTimeframePage.jsx` — Multi-Timeframe Analysis view.
- `frontend/src/index.css` — global styling.
- `frontend/vite.config.js` — development server proxy configuration.

Preserve the existing working behavior when improving the UI.

## 11. Next frontend development phase: visual trading dashboard

The next planned work is to improve data representation with charts and visual summaries.

### Phase 1 — Interactive candlestick chart

Use `lightweight-charts` for:

- OHLC candlesticks.
- Daily, weekly, monthly, and yearly timeframe selection.
- EMA 9, 20, 50, 100, and 200 overlays.
- Volume histogram when valid volume data is available.
- Crosshair, zoom, and pan.
- Clear loading, empty-data, and API-error states.

Historical chart data must come from the historical market-data API. Indicator overlays must use stored indicator API data. Align series by their actual dates/period keys; do not assume arrays have matching lengths or indexes.

### Phase 2 — Technical-indicator panels

Use Recharts or suitable lightweight chart panels for:

- RSI 14, including 30 and 70 reference levels.
- MACD line, signal line, and histogram.
- ADX, +DI, and -DI.
- ATR 14.
- CHOP 14.
- Bollinger Bandwidth.

Indicator graphs require historical indicator series. The current Multi-Timeframe endpoint returns only the latest snapshot per timeframe and is not sufficient on its own for historical indicator charts. Use the indicators history endpoint for this purpose.

### Phase 3 — Market-structure overlays

Visualize available support/resistance and confirmed swing events on the price chart. Display breakout and range-position status clearly. Only plot levels/events whose dates and values are supplied by the API.

### Phase 4 — Market-cycle visualization

Add:

- A seven-category cycle distribution chart.
- A historical cycle timeline.
- Rule score and bandwidth-percentile visualizations where meaningful.
- Evidence and missing-input details in a readable expandable/detail area.

Cycle distribution should state its selected instrument, timeframe, and batch/filter scope. Do not mix timeframes or batches in a single count unless explicitly labelled.

### Phase 5 — Dashboard polish

- Professional dark trading-terminal default theme.
- Preserve the existing theme toggle.
- Improve typography, spacing, hierarchy, card layout, chart legends, tooltips, and responsive behavior.
- Keep market data readable and avoid decorative effects that reduce contrast.
- Display data dates, timeframe, source status, and availability.

## 12. Data and research integrity

The project has completed substantial historical research and data validation. Important principles:

- Preserve source provenance and import-batch identity.
- Use exact composite keys when joining analytics.
- Do not infer missing data.
- Do not silently drop partial or warming-up records.
- Distinguish `no_data`, `partial`, and `available`.
- Do not treat an `INSUFFICIENT_DATA` cycle as a successful directional signal.
- Do not interpret accumulation/distribution labels as proof of institutional activity.
- Keep filtered backtest results separate from baseline trade-cohort analysis.
- Do not select a universal ADX threshold based on the completed experiments; no universal threshold was established.

## 13. Historical research and validation status

The following analytical components have been implemented and tested:

1. Historical data pipeline.
2. Technical indicators.
3. Market structure.
4. Market-cycle classification.
5. Daily backtesting engine.
6. Market Regime Attribution V1.
7. ADX filter experiments and robustness comparisons.
8. Market-regime coverage and signal-distribution analysis.
9. Blocked-signal outcome and risk/reward analysis.

The historical classification import audit for batch 5 used calculation version `market_cycle_v1.1_confirmed_context`. The audited PostgreSQL import contained 23,110 eligible classification records across the five price indices and four timeframes.

The ADX research compared baseline, ADX >= 20 entry blocking, and ADX >= 25 entry blocking over NIFTY50 and SENSEX historical periods. Results did not establish a universally best threshold. These research scripts and CSV/Markdown reports are retained under `backend/scripts/` and `backend/data/reports/`.

Research reports are evidence for the specific tested strategy, instruments, date windows, and execution assumptions; they are not guarantees of future performance.

## 14. Development environment

Known project locations on the development machine:

```text
Project root:  E:\market-cycle-tracker
Backend:       E:\market-cycle-tracker\backend
Frontend:      E:\market-cycle-tracker\frontend
Python venv:   E:\Python-Environments\market-cycle-tracker-venv
```

### Backend setup

Open PowerShell and navigate to the backend:

```powershell
cd E:\market-cycle-tracker\backend
& E:\Python-Environments\market-cycle-tracker-venv\Scripts\Activate.ps1
```

The backend uses environment-based configuration. The database URL is loaded from the project environment configuration. Do not commit credentials, API keys, or `.env` files to source control.

Start the API using the project's installed ASGI server:

```powershell
python -m uvicorn app.main:app --reload
```

The API is expected to be available at:

```text
http://127.0.0.1:8000
```

Interactive API documentation is normally available at:

```text
http://127.0.0.1:8000/docs
```

### Frontend setup

Open a second PowerShell window:

```powershell
cd E:\market-cycle-tracker\frontend
npm install
npm run dev
```

The Vite development server prints the local frontend URL in the terminal. The configured proxy forwards `/api` requests to `http://127.0.0.1:8000`.

### Frontend production build

```powershell
cd E:\market-cycle-tracker\frontend
npm run build
```

### Backend tests

From the backend directory with the project virtual environment active:

```powershell
python -m unittest discover -s tests -v
```

Use the project's existing test and migration workflow. Do not recreate the database or rewrite migrations as part of ordinary frontend work.

## 15. Testing status at the last verified milestone

The user reported the following successful backend regression results:

| Milestone | Verified result |
|---|---:|
| Market Structure API V1 | 232 passed, 51 subtests passed |
| Market Cycle API V1 | 255 passed |
| Multi-Timeframe API V1 | 265 passed, 55 subtests passed |

A known non-blocking warning concerns Starlette's TestClient integration with `httpx`. It was intentionally left unchanged during the API implementation phase to avoid unrelated dependency changes.

Frontend production builds passed after the API client, dashboard, and Multi-Timeframe page integration. The user also visually confirmed the rendered page and navigation.

These are historical milestone results. Run the tests/build again after future changes before claiming the current working tree is fully verified.

## 16. Out of scope for the current phase

Unless explicitly approved later, do not introduce these into the current dashboard work:

- Options-chain and options-premium data.
- Intraday options backtesting.
- Individual stock analysis.
- New market-cycle calculation rules.
- New ADX threshold selection.
- FII/DII activity integration without an agreed data source and API contract.
- Automatic recalculation during dashboard page loads.

## 17. Working rules for future development

1. Preserve the existing project and working features.
2. Make changes in small, clearly defined batches.
3. Audit existing code before replacing or duplicating a component.
4. Keep API contracts and frontend field names aligned with the existing Pydantic schemas.
5. Prefer read-only query APIs for dashboard rendering.
6. Do not fabricate values, chart points, dates, or data availability.
7. Handle loading, errors, empty results, partial data, and unsupported instruments explicitly.
8. Run the relevant tests and production build after each meaningful implementation batch.
9. Report only test/build results that were actually run.
10. Update this README and the project handover notes when a major milestone is completed.

## 18. Immediate next task

**Start the visual chart phase with the interactive candlestick chart.**

Recommended first implementation batch:

1. Inspect the current historical and indicator API response schemas already implemented.
2. Add a reusable candlestick-chart component.
3. Fetch historical OHLC data for the selected instrument and timeframe.
4. Fetch the corresponding stored indicator history for EMA overlays.
5. Align the series by date and render candlesticks plus available EMA lines.
6. Add timeframe selection and chart loading/error/empty states.
7. Run the frontend production build and verify the chart in the browser.

Do not begin by rewriting the dashboard shell or changing backend calculations. Keep the existing dashboard and Multi-Timeframe Analysis page operational while the chart is introduced.

---

*Last updated: 2026-11-03*
