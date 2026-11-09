Market Cycle Tracker — Indicator layer files

Copy these files into the existing backend project:
  app/engines/indicator_engine.py
  app/services/indicator_service.py
  tests/test_indicator_engine.py

Current behavior:
- Indices: NIFTY50, BANKNIFTY, SENSEX, FINNIFTY, MIDCPNIFTY.
- INDIA_VIX is explicitly rejected by the standard EMA/SMA engine.
- Timeframes: 1D, 1W, 1M, 1Y.
- EMA: 9, 20, 50, 100, 200. SMA: 222.
- EMA seed: arithmetic mean of the first N eligible closes.
- Excluded candles reset calculation state; missing W/M/Y calendar buckets reset state.
- Daily calendar gaps are not inferred as missing sessions.
- Aggregate session_coverage_status is preserved; not_checked is not represented as verified.
- Decimal arithmetic; output precision is eight decimal places.
- No data is changed merely by importing these modules.

The service requires the caller to own the transaction:

  from app.core.database import SessionLocal
  from app.services.indicator_service import calculate_and_store_indicators

  with SessionLocal.begin() as session:
      summary = calculate_and_store_indicators(session, import_batch_id=5)
      print(summary)

Existing rows are protected by default. replace_existing=True explicitly deletes
and recalculates rows for the given snapshot and the five standard indices.

Run tests from backend:
  python -m unittest tests.test_indicator_engine -v
