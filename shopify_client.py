"""Shopify Admin API access: settings, short-lived token, paginated order fetch."""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API_VERSION = "2026-07"


def load_env(required=("SHOPIFY_STORE", "SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET")):
    """Read .env next to this file; real environment variables (GitHub secrets) win."""
    env_file = Path(__file__).with_name(".env")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing settings: {', '.join(missing)}. Add them to .env or GitHub secrets.")
    store = os.environ["SHOPIFY_STORE"].replace("https://", "").strip("/")
    if not store.endswith(".myshopify.com"):
        store += ".myshopify.com"
    return {
        "store": store,
        "client_id": os.environ["SHOPIFY_CLIENT_ID"],
        "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
    }


def post_json(url, payload, headers=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            return json.loads(body) if body.strip().startswith(("{", "[")) else body
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"{e.code} error from {url.split('?')[0]}: {detail}") from None


def get_access_token(cfg):
    """Client credentials grant: Client ID + Secret -> Admin API token (about 24h)."""
    result = post_json(
        f"https://{cfg['store']}/admin/oauth/access_token",
        {"client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
         "grant_type": "client_credentials"},
    )
    token = result.get("access_token") if isinstance(result, dict) else None
    if not token:
        raise RuntimeError(f"Shopify did not return a token: {str(result)[:300]}")
    return token


def graphql(cfg, token, query, variables=None):
    result = post_json(
        f"https://{cfg['store']}/admin/api/{API_VERSION}/graphql.json",
        {"query": query, "variables": variables or {}},
        {"X-Shopify-Access-Token": token},
    )
    if result.get("errors"):
        raise RuntimeError(f"Shopify API error: {json.dumps(result['errors'])[:300]}")
    return result["data"]


SHOP_QUERY = "{ shop { name currencyCode ianaTimezone } }"

ORDERS_QUERY = """
query Orders($cursor: String, $q: String) {
  orders(first: 100, after: $cursor, query: $q, sortKey: PROCESSED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name
      processedAt
      totalPriceSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      lineItems(first: 50) { nodes { title quantity } }
    }
  }
}
"""


def fetch_shop(cfg, token):
    return graphql(cfg, token, SHOP_QUERY)["shop"]


def fetch_orders(cfg, token, since_iso):
    """All orders processed since `since_iso`, flattened to plain dicts."""
    orders, cursor = [], None
    while True:
        page = graphql(cfg, token, ORDERS_QUERY,
                       {"cursor": cursor, "q": f"processed_at:>={since_iso}"})["orders"]
        for o in page["nodes"]:
            orders.append({
                "name": o["name"],
                "processed_at": o["processedAt"],
                "total": float(o["totalPriceSet"]["shopMoney"]["amount"]),
                "refunded": float(o["totalRefundedSet"]["shopMoney"]["amount"]),
                "items": [{"title": li["title"], "quantity": li["quantity"]}
                          for li in o["lineItems"]["nodes"]],
            })
        if not page["pageInfo"]["hasNextPage"]:
            return orders
        cursor = page["pageInfo"]["endCursor"]
