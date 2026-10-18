"""Profit math. Pure functions only, so every number on the dashboard is testable."""

import csv
import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


# ---------- inputs ----------

def load_ad_spend(path):
    """ad_spend.csv -> {date: spend}. Columns: date,campaign,spend[,clicks,impressions]."""
    spend = {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = date.fromisoformat(row["date"])
                spend[d] = spend.get(d, 0.0) + float(row["spend"])
    except FileNotFoundError:
        pass
    return spend


def simulated_spend(day, revenue):
    """Demo-only ad spend for days missing from ad_spend.csv.

    Deterministic per date (same input -> same number on every rebuild):
    a small daily base plus 22-38% of that day's revenue, which lands ROAS in a
    realistic 2.5-4.5x range. Clearly labelled as simulated on the dashboard.
    """
    h = int(hashlib.sha256(day.isoformat().encode()).hexdigest()[:8], 16)
    ratio = 0.22 + (h % 1000) / 1000 * 0.16
    base = 12 + (h // 1000) % 9
    return round(base + revenue * ratio, 2)


def unit_cost(title, costs):
    """Product cost per unit from costs.json; None when unknown (falls back to a % of price)."""
    return costs.get("products", {}).get(title)


# ---------- per-order and per-day math ----------

def order_cogs(order, costs):
    """Cost of goods for one order. Known products use their unit cost; the rest of the
    order value is costed at default_cost_pct."""
    known_cost, known_units_value = 0.0, 0.0
    for item in order["items"]:
        c = unit_cost(item["title"], costs)
        if c is not None:
            known_cost += c * item["quantity"]
            price = costs.get("prices", {}).get(item["title"])
            known_units_value += (price or 0) * item["quantity"]
    if known_cost and known_units_value:
        unknown_value = max(order["total"] - known_units_value, 0)
        return known_cost + unknown_value * costs.get("default_cost_pct", 0.35)
    if known_cost:
        return known_cost
    return order["total"] * costs.get("default_cost_pct", 0.35)


def payment_fees(order, costs):
    return order["total"] * costs.get("payment_fee_pct", 0.029) + costs.get("payment_fee_fixed", 0.30)


def local_day(iso_ts, tz):
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00")).astimezone(tz).date()


def daily_metrics(orders, ad_spend, costs, end_day, days, tz_name="UTC", simulate_missing_spend=True):
    """One row per day for the `days` days ending on `end_day` (inclusive), oldest first."""
    tz = ZoneInfo(tz_name)
    start = end_day - timedelta(days=days - 1)
    rows = {start + timedelta(days=i): {
        "orders": 0, "revenue": 0.0, "refunds": 0.0, "cogs": 0.0, "fees": 0.0,
    } for i in range(days)}
    for o in orders:
        d = local_day(o["processed_at"], tz)
        if d not in rows:
            continue
        r = rows[d]
        r["orders"] += 1
        r["revenue"] += o["total"]
        r["refunds"] += o["refunded"]
        r["cogs"] += order_cogs(o, costs)
        r["fees"] += payment_fees(o, costs)

    out = []
    for d, r in rows.items():
        spend_simulated = d not in ad_spend and simulate_missing_spend
        spend = ad_spend.get(d, simulated_spend(d, r["revenue"]) if simulate_missing_spend else 0.0)
        out.append(finish_row(d, r, spend, spend_simulated))
    return out


def finish_row(d, r, spend, spend_simulated=False):
    net = r["revenue"] - r["refunds"]
    profit = net - r["cogs"] - r["fees"] - spend
    return {
        "date": d.isoformat(),
        "orders": r["orders"],
        "revenue": round(r["revenue"], 2),
        "refunds": round(r["refunds"], 2),
        "net_revenue": round(net, 2),
        "cogs": round(r["cogs"], 2),
        "fees": round(r["fees"], 2),
        "ad_spend": round(spend, 2),
        "ad_spend_simulated": spend_simulated,
        "profit": round(profit, 2),
        # no sales that day -> ROAS is "not applicable", not 0x
        "roas": round(r["revenue"] / spend, 2) if spend and r["revenue"] else None,
        "aov": round(r["revenue"] / r["orders"], 2) if r["orders"] else None,
        "cost_per_order": round(spend / r["orders"], 2) if r["orders"] else None,
        "refund_rate": round(r["refunds"] / r["revenue"], 4) if r["revenue"] else None,
        "margin": round(profit / net, 4) if net else None,
    }


# ---------- period summaries ----------

def summarize(rows):
    """Totals and ratios for a list of daily rows (ratios from totals, never averaged)."""
    t = {k: sum(r[k] for r in rows) for k in
         ("orders", "revenue", "refunds", "net_revenue", "cogs", "fees", "ad_spend", "profit")}
    t = {k: round(v, 2) if isinstance(v, float) else v for k, v in t.items()}
    t["roas"] = round(t["revenue"] / t["ad_spend"], 2) if t["ad_spend"] else None
    t["aov"] = round(t["revenue"] / t["orders"], 2) if t["orders"] else None
    t["cost_per_order"] = round(t["ad_spend"] / t["orders"], 2) if t["orders"] else None
    t["refund_rate"] = round(t["refunds"] / t["revenue"], 4) if t["revenue"] else None
    t["margin"] = round(t["profit"] / t["net_revenue"], 4) if t["net_revenue"] else None
    t["days"] = len(rows)
    return t


def change(current, previous):
    """Relative change, or None when there is no meaningful base."""
    if current is None or previous in (None, 0):
        return None
    return round((current - previous) / abs(previous), 4)


def compare_periods(rows, period=7):
    """Last `period` days vs the `period` days before."""
    cur, prev = summarize(rows[-period:]), summarize(rows[-2 * period:-period])
    return {"current": cur, "previous": prev,
            "change": {k: change(cur[k], prev[k]) for k in cur if k != "days"}}
