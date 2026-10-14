# Command-Line Price Alert Tool

A simple, lightweight, and robust command-line price alert engine written strictly with Python standard libraries (`csv`, `json`, `sys`, `collections`, `datetime`).

---

## 1. Quick Start

### Running the Tool
```bash
python alerts.py prices.csv rules.json
```

**Output Format:**
```text
YYYY-MM-DD rule_id instrument description
```
*Note: If no rules trigger, the program outputs nothing.*

### Running Unit Tests
```bash
python -m unittest -v test_alerts.py
```

---

## 2. Architecture & Design Principles

The application is decomposed into short, single-responsibility functions designed for readability and presentation in a viva:

| Function | Responsibility |
| :--- | :--- |
| `parse_prices(filepath)` | Reads CSV, groups records by instrument, and sorts dates chronologically. |
| `parse_rules(filepath)` | Loads JSON rules (supports list format or dictionary formats). |
| `calculate_sma(prices, window)` | Computes Simple Moving Average in $O(N)$ time via sliding window. |
| `evaluate_level_rule(rule, records)` | Detects transitions across a target price level between day $t-1$ and $t$. |
| `evaluate_ma_cross_rule(rule, records)`| Detects bullish/bearish crossovers after both windows are fully formed. |
| `evaluate_all_rules(...)` | Applies all rules against isolated instrument price histories. |
| `format_and_print_alerts(...)` | Strictly sorts alerts by `(date, rule_id)` and prints each in required format. |

---

## 3. Supported Rule Types

### 1. Level Crossing (`level`)
Triggers when closing price crosses a target price level compared to the previous trading day:
- **Cross above**: `prev_close < level <= curr_close`
- **Cross below**: `prev_close > level >= curr_close`

```json
{
  "id": "rule_aapl_150",
  "type": "level",
  "instrument": "AAPL",
  "level": 150.0
}
```

### 2. Moving Average Crossover (`ma_cross`)
Triggers when a short simple moving average (SMA) crosses a long SMA:
- **Bullish (Golden Cross)**: `prev_short <= prev_long` and `curr_short > curr_long`
- **Bearish (Death Cross)**: `prev_short >= prev_long` and `curr_short < curr_long`

```json
{
  "id": "rule_msft_sma",
  "type": "ma_cross",
  "instrument": "MSFT",
  "short_window": 2,
  "long_window": 3
}
```

---

## 4. AI Assistant Collaboration, Errors & Fixes

During the development of this tool with the AI assistant, several critical edge cases and potential bugs were identified and addressed:

### Error 1: Moving Average Crossover Lookback Boundary (Off-by-One)
* **What the AI did wrong**: The initial AI implementation began evaluating crossovers at index `i = long_window - 1`. While this is the first day the long SMA exists, comparing day $t$ to day $t-1$ required `long_sma[i-1]`, which was `None` because day $t-1$ had fewer than `long_window` data points. This resulted in an unhandled comparison error between float and `None`.
* **How it was fixed**: The crossover loop was corrected to start at `i = long_window` (the $(L+1)$-th day). Day $L+1$ is mathematically the earliest day where **both** $t-1$ and $t$ have complete moving average windows. A defensive check (`prev_l is not None`) was also added.

### Error 2: Assuming In-Order and Single-Instrument CSV Rows
* **What the AI did wrong**: The initial parsing logic assumed that CSV rows were pre-sorted and grouped by instrument, evaluating row-by-row in a single streaming pass.
* **How it was fixed**: Separated parsing into a grouping phase (`prices_by_instrument[ticker]`) and an explicit sorting phase (`sort(key=lambda r: r.date)`). This guarantees correct chronological calculation even when dates are scrambled or interleaved across multiple symbols.

### Error 3: Non-Deterministic Alert Ordering
* **What the AI did wrong**: Alerts were initially appended to a list as each rule finished, meaning alerts on the same date were ordered by whatever order the rules appeared in `rules.json`.
* **How it was fixed**: Implemented a strict secondary sort key `alerts.sort(key=lambda a: (a.date, a.rule_id))`, ensuring consistent, deterministic output sorted strictly by date ascending, then rule ID ascending.

### Error 4: Extraneous Output on Empty Alerts
* **What the AI did wrong**: The initial script printed informational text (`"0 alerts found."`) when no conditions met the criteria.
* **How it was fixed**: Removed all diagnostic print statements to strictly adhere to the specification: *"Prints nothing if no rules fire."*
