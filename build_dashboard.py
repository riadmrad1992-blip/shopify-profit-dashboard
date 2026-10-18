"""Build the profit dashboard: Shopify orders + ad spend + costs -> site/index.html.

Usage:
  python build_dashboard.py              # live data from Shopify (needs .env or secrets)
  python build_dashboard.py --sample     # offline sample data, for previews and tests
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import metrics

ROOT = Path(__file__).parent
SITE = ROOT / "site"
DAYS = 30

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def sample_orders(end_day, days, tz):
    """Offline sample orders so the page can be built without credentials."""
    rng = random.Random(42)
    products = list(json.loads((ROOT / "costs.json").read_text())["prices"].items())
    orders = []
    for i in range(days):
        d = end_day - timedelta(days=i)
        for n in range(rng.randint(1, 6)):
            items = rng.sample(products, k=rng.randint(1, 2))
            lines = [{"title": t, "quantity": rng.randint(1, 2)} for t, _ in items]
            total = sum(dict(products)[li["title"]] * li["quantity"] for li in lines)
            ts = datetime(d.year, d.month, d.day, rng.randint(8, 22), rng.randint(0, 59), tzinfo=tz)
            orders.append({"name": f"#S{i}{n}", "processed_at": ts.isoformat(), "total": total,
                           "refunded": total if rng.random() < 0.04 else 0.0, "items": lines})
    return orders


def collect(sample=False):
    costs = json.loads((ROOT / "costs.json").read_text())
    ad_spend = metrics.load_ad_spend(ROOT / "ad_spend.csv")
    if sample:
        shop = {"name": "Sample store", "currencyCode": "USD", "ianaTimezone": "UTC"}
        tz = ZoneInfo("UTC")
        end_day = datetime.now(tz).date()
        orders = sample_orders(end_day, DAYS, tz)
    else:
        import shopify_client as sc
        cfg = sc.load_env()
        token = sc.get_access_token(cfg)
        shop = sc.fetch_shop(cfg, token)
        tz = ZoneInfo(shop["ianaTimezone"] or "UTC")
        end_day = datetime.now(tz).date()
        since = datetime.combine(end_day - timedelta(days=DAYS + 1), datetime.min.time(), tz)
        orders = sc.fetch_orders(cfg, token, since.isoformat())
    rows = metrics.daily_metrics(orders, ad_spend, costs, end_day, DAYS, tz.key)
    return {
        "shop": shop["name"],
        "currency": shop["currencyCode"],
        "timezone": tz.key,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "days": rows,
        "summary": metrics.compare_periods(rows, 7),
        "spend_simulated": any(r["ad_spend_simulated"] for r in rows),
        "assumptions": {
            "default_cost_pct": costs.get("default_cost_pct", 0.35),
            "payment_fee_pct": costs.get("payment_fee_pct", 0.029),
            "payment_fee_fixed": costs.get("payment_fee_fixed", 0.30),
        },
        "sample": sample,
    }


def write_site(data):
    SITE.mkdir(exist_ok=True)
    (SITE / "data.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    cols = ["date", "orders", "revenue", "refunds", "net_revenue", "cogs", "fees",
            "ad_spend", "profit", "roas", "aov", "cost_per_order", "refund_rate"]
    lines = [",".join(cols)] + [",".join("" if r[c] is None else str(r[c]) for c in cols)
                                for r in data["days"]]
    (SITE / "data.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    template = (ROOT / "dashboard_template.html").read_text(encoding="utf-8")
    payload = json.dumps(data).replace("</", "<\\/")
    (SITE / "index.html").write_text(template.replace("/*__DATA__*/null", payload), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="build with offline sample data")
    args = ap.parse_args()
    data = collect(sample=args.sample)
    write_site(data)
    s = data["summary"]["current"]
    print(f"Built site/index.html for {data['shop']}: last 7 days revenue {s['revenue']:.2f} "
          f"{data['currency']}, profit {s['profit']:.2f}, ROAS {s['roas']}")


if __name__ == "__main__":
    main()
