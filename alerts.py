"""
Price Alert Tool
================
A clean, modular command-line tool that evaluates financial price series against
custom alert rules using only the Python standard library.

Supported Rule Types:
1. 'level': Detects when the closing price crosses a target level compared to the previous day.
2. 'ma_cross': Detects when a short simple moving average (SMA) crosses a long SMA
               (evaluated only after full lookback windows are available).

Usage:
    python alerts.py <prices.csv> <rules.json>

Output Format:
    YYYY-MM-DD rule_id instrument description
    (Sorted strictly by date ascending, then by rule ID ascending. Prints nothing if no rules fire.)
"""

import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, NamedTuple, Optional


class PriceRecord(NamedTuple):
    """Represents a single daily price record for an instrument."""
    date: str          # Format: YYYY-MM-DD
    instrument: str    # e.g., 'AAPL', 'MSFT'
    close: float       # Daily closing price


class Alert(NamedTuple):
    """Represents an alert triggered by a rule evaluation."""
    date: str          # Date the alert triggered (YYYY-MM-DD)
    rule_id: str       # Identifier of the triggering rule
    instrument: str    # Target instrument symbol
    description: str   # Human-readable explanation of the alert condition


def parse_prices(filepath: str) -> Dict[str, List[PriceRecord]]:
    """
    Parses prices.csv and groups records by instrument.
    
    Handles out-of-order dates by sorting each instrument's price history
    chronologically. Robust against header casing and common column name variants.
    
    Returns:
        Dict[instrument, List[PriceRecord]] sorted by date ascending.
    """
    prices_by_instrument: Dict[str, List[PriceRecord]] = defaultdict(list)

    with open(filepath, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return {}

        # Normalize fieldnames to lowercase and strip whitespace for resilient lookup
        field_map = {name.strip().lower(): name for name in reader.fieldnames}

        # Identify date, instrument, and close price columns
        date_col = next((field_map[k] for k in ["date", "timestamp"] if k in field_map), None)
        inst_col = next((field_map[k] for k in ["instrument", "symbol", "ticker"] if k in field_map), None)
        price_col = next((field_map[k] for k in ["close", "price", "adj_close"] if k in field_map), None)

        if not (date_col and inst_col and price_col):
            raise ValueError(
                f"CSV must contain date, instrument, and close/price columns. Found: {reader.fieldnames}"
            )

        for row_num, row in enumerate(reader, start=2):
            raw_date = row[date_col].strip()
            raw_inst = row[inst_col].strip()
            raw_price = row[price_col].strip()

            if not raw_date or not raw_inst or not raw_price:
                continue

            # Standardize date to YYYY-MM-DD format
            parsed_date = datetime.strptime(raw_date, "%Y-%m-%d").strftime("%Y-%m-%d")
            close_price = float(raw_price)

            record = PriceRecord(date=parsed_date, instrument=raw_inst, close=close_price)
            prices_by_instrument[raw_inst].append(record)

    # Sort each instrument's records chronologically to handle out-of-order CSV dates
    for inst in prices_by_instrument:
        prices_by_instrument[inst].sort(key=lambda r: r.date)

    return prices_by_instrument


def parse_rules(filepath: str) -> List[dict]:
    """
    Loads and normalizes rules from rules.json.
    
    Accepts:
      - A JSON list: [{"id": "r1", "type": "level", ...}, ...]
      - A JSON object with a 'rules' list: {"rules": [...]}
      - A JSON object keyed by rule ID: {"r1": {"type": "level", ...}}
    """
    with open(filepath, mode="r", encoding="utf-8") as f:
        data = json.load(f)

    rules = []
    if isinstance(data, list):
        for idx, item in enumerate(data):
            rule = dict(item)
            rule.setdefault("id", str(item.get("id", f"rule_{idx + 1}")))
            rules.append(rule)
    elif isinstance(data, dict):
        if "rules" in data and isinstance(data["rules"], list):
            for idx, item in enumerate(data["rules"]):
                rule = dict(item)
                rule.setdefault("id", str(item.get("id", f"rule_{idx + 1}")))
                rules.append(rule)
        else:
            # Format: {"rule_id": { ...rule attributes... }}
            for rule_id, details in data.items():
                rule = dict(details)
                rule.setdefault("id", str(rule_id))
                rules.append(rule)
    else:
        raise ValueError("Rules file must be a JSON array or object.")

    return rules


def calculate_sma(prices: List[float], window: int) -> List[Optional[float]]:
    """
    Computes Simple Moving Average (SMA) over a sliding window.
    
    Returns a list of the same length as `prices`. For indices where fewer than
    `window` data points are available, the value is None.
    """
    sma: List[Optional[float]] = []
    current_sum = 0.0

    for i, price in enumerate(prices):
        current_sum += price
        if i >= window:
            current_sum -= prices[i - window]

        if i >= window - 1:
            sma.append(current_sum / window)
        else:
            sma.append(None)

    return sma


def evaluate_level_rule(rule: dict, records: List[PriceRecord]) -> List[Alert]:
    """
    Evaluates a 'level' rule:
    Triggers an alert when the closing price crosses a target level compared to the previous day.
    
    Conditions:
      - Cross above: previous_close < target_level and current_close >= target_level
      - Cross below: previous_close > target_level and current_close <= target_level
    """
    target_level = float(rule["level"])
    direction = rule.get("direction", "both").lower()  # 'above', 'below', or 'both'
    rule_id = str(rule["id"])
    instrument = rule["instrument"]

    alerts: List[Alert] = []

    for i in range(1, len(records)):
        prev_close = records[i - 1].close
        curr_close = records[i].close
        curr_date = records[i].date

        crossed_above = (prev_close < target_level <= curr_close)
        crossed_below = (prev_close > target_level >= curr_close)

        if crossed_above and direction in ("above", "both"):
            custom_desc = rule.get("description")
            desc = custom_desc if custom_desc else f"crossed above {target_level}"
            alerts.append(Alert(date=curr_date, rule_id=rule_id, instrument=instrument, description=desc))

        elif crossed_below and direction in ("below", "both"):
            custom_desc = rule.get("description")
            desc = custom_desc if custom_desc else f"crossed below {target_level}"
            alerts.append(Alert(date=curr_date, rule_id=rule_id, instrument=instrument, description=desc))

    return alerts


def evaluate_ma_cross_rule(rule: dict, records: List[PriceRecord]) -> List[Alert]:
    """
    Evaluates an 'ma_cross' rule:
    Triggers an alert when the short moving average crosses the long moving average.
    
    Only evaluates after the full window of days is available for both the current
    day and the previous day (i.e., at least long_window + 1 days of data).
    
    Conditions:
      - Bullish cross (golden cross): short MA was <= long MA on day t-1, and is > long MA on day t.
      - Bearish cross (death cross):  short MA was >= long MA on day t-1, and is < long MA on day t.
    """
    short_window = int(rule["short_window"])
    long_window = int(rule["long_window"])
    direction = rule.get("direction", "both").lower()  # 'above', 'below', or 'both'
    rule_id = str(rule["id"])
    instrument = rule["instrument"]

    if short_window >= long_window:
        raise ValueError(
            f"Rule {rule_id}: short_window ({short_window}) must be strictly less than long_window ({long_window})"
        )

    # Need at least long_window + 1 records to compare day t with day t-1
    if len(records) <= long_window:
        return []

    close_prices = [r.close for r in records]
    short_sma = calculate_sma(close_prices, short_window)
    long_sma = calculate_sma(close_prices, long_window)

    alerts: List[Alert] = []

    # First day where both t-1 and t have full long moving averages available is index long_window
    for i in range(long_window, len(records)):
        prev_s = short_sma[i - 1]
        prev_l = long_sma[i - 1]
        curr_s = short_sma[i]
        curr_l = long_sma[i]

        # Defensive check: ensure neither value is None
        if prev_s is None or prev_l is None or curr_s is None or curr_l is None:
            continue

        curr_date = records[i].date
        crossed_above = (prev_s <= prev_l) and (curr_s > curr_l)
        crossed_below = (prev_s >= prev_l) and (curr_s < curr_l)

        if crossed_above and direction in ("above", "both"):
            custom_desc = rule.get("description")
            desc = custom_desc if custom_desc else f"MA({short_window}) crossed above MA({long_window})"
            alerts.append(Alert(date=curr_date, rule_id=rule_id, instrument=instrument, description=desc))

        elif crossed_below and direction in ("below", "both"):
            custom_desc = rule.get("description")
            desc = custom_desc if custom_desc else f"MA({short_window}) crossed below MA({long_window})"
            alerts.append(Alert(date=curr_date, rule_id=rule_id, instrument=instrument, description=desc))

    return alerts


def evaluate_all_rules(
    prices_by_instrument: Dict[str, List[PriceRecord]], rules: List[dict]
) -> List[Alert]:
    """
    Evaluates all loaded rules against price histories and collects all alerts.
    """
    alerts: List[Alert] = []

    for rule in rules:
        instrument = rule.get("instrument")
        rule_type = rule.get("type", "").lower()

        if not instrument or instrument not in prices_by_instrument:
            continue

        records = prices_by_instrument[instrument]

        if rule_type == "level":
            alerts.extend(evaluate_level_rule(rule, records))
        elif rule_type == "ma_cross":
            alerts.extend(evaluate_ma_cross_rule(rule, records))
        else:
            print(f"Warning: Unknown rule type '{rule_type}' for rule ID {rule.get('id')}", file=sys.stderr)

    return alerts


def format_and_print_alerts(alerts: List[Alert]) -> None:
    """
    Sorts alerts strictly by date ascending, then by rule ID ascending,
    and prints them in the format: YYYY-MM-DD rule_id instrument description.
    
    Prints nothing if no rules fire.
    """
    # Sort strictly by date, then rule ID
    alerts.sort(key=lambda a: (a.date, a.rule_id))

    for alert in alerts:
        print(f"{alert.date} {alert.rule_id} {alert.instrument} {alert.description}")


def main() -> None:
    """Entry point for the command-line tool."""
    if len(sys.argv) != 3:
        print("Usage: python alerts.py <prices.csv> <rules.json>", file=sys.stderr)
        sys.exit(1)

    prices_path = sys.argv[1]
    rules_path = sys.argv[2]

    try:
        prices_by_instrument = parse_prices(prices_path)
        rules = parse_rules(rules_path)
        alerts = evaluate_all_rules(prices_by_instrument, rules)
        format_and_print_alerts(alerts)
    except FileNotFoundError as e:
        print(f"Error: File not found - {e.filename}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
