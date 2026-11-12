"""
Deterministic demo dataset: a synthetic Indian e-commerce store, Jan 2024 - Dec 2025.

Patterns are planted on purpose so there is something to discover:
    - steady growth, with a festive-season (Diwali) spike in Oct/Nov and sale discounts
    - the East region's revenue drops in Q4 2025 while the South keeps growing
    - COD orders are cancelled more often; orders with Fashion items are returned more often

Run from the project root:
    python -m app.db.seed            # create tables and load data (skips if data already exists)
    python -m app.db.seed --force    # drop all tables and reload

Programmatic use (tests use smaller sizes):
    seed(engine, force=True, n_customers=300, n_orders=2500)
"""

import argparse
import bisect
import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import Engine, func, select

from app.core.config import get_settings
from app.db.engine import make_engines
from app.db.models import customers, metadata, order_items, orders, products

# ---- Reference data -------------------------------------------------------------------------
START, END = date(2024, 1, 1), date(2025, 12, 31)

GEO = {
    "North": [
        ("Delhi", "Delhi"),
        ("Lucknow", "Uttar Pradesh"),
        ("Noida", "Uttar Pradesh"),
        ("Jaipur", "Rajasthan"),
        ("Ludhiana", "Punjab"),
        ("Chandigarh", "Chandigarh"),
    ],
    "West": [
        ("Mumbai", "Maharashtra"),
        ("Pune", "Maharashtra"),
        ("Nagpur", "Maharashtra"),
        ("Ahmedabad", "Gujarat"),
        ("Surat", "Gujarat"),
        ("Panaji", "Goa"),
    ],
    "South": [
        ("Bengaluru", "Karnataka"),
        ("Mysuru", "Karnataka"),
        ("Chennai", "Tamil Nadu"),
        ("Coimbatore", "Tamil Nadu"),
        ("Hyderabad", "Telangana"),
        ("Kochi", "Kerala"),
    ],
    "East": [
        ("Kolkata", "West Bengal"),
        ("Bhubaneswar", "Odisha"),
        ("Patna", "Bihar"),
        ("Guwahati", "Assam"),
        ("Ranchi", "Jharkhand"),
    ],
}
REGION_WEIGHTS = {"North": 0.25, "West": 0.30, "South": 0.30, "East": 0.15}

FIRST = [
    "Aarav",
    "Vivaan",
    "Aditya",
    "Arjun",
    "Sai",
    "Reyansh",
    "Krishna",
    "Ishaan",
    "Rohan",
    "Kabir",
    "Ananya",
    "Diya",
    "Saanvi",
    "Aadhya",
    "Kavya",
    "Isha",
    "Meera",
    "Priya",
    "Riya",
    "Neha",
    "Rahul",
    "Vikram",
    "Karan",
    "Siddharth",
    "Nikhil",
    "Pooja",
    "Sneha",
    "Tanvi",
    "Lakshmi",
    "Fatima",
    "Imran",
    "Zoya",
    "Harpreet",
    "Gurpreet",
    "Anjali",
    "Deepak",
    "Suresh",
    "Ramesh",
    "Divya",
    "Nisha",
]
LAST = [
    "Sharma",
    "Verma",
    "Patel",
    "Shah",
    "Mehta",
    "Iyer",
    "Nair",
    "Reddy",
    "Rao",
    "Gupta",
    "Singh",
    "Kumar",
    "Das",
    "Banerjee",
    "Chatterjee",
    "Joshi",
    "Kulkarni",
    "Desai",
    "Pillai",
    "Menon",
    "Khan",
    "Ansari",
    "Gill",
    "Sandhu",
    "Mishra",
    "Pandey",
    "Bose",
    "Ghosh",
    "Naidu",
    "Sheikh",
]

# category -> sub_category -> (item names, min price, max price)
CATALOGUE = {
    "Electronics": {
        "Mobiles": (["Smartphone 5G", "Smartphone Lite", "Feature Phone", "Foldable Phone"], 6000, 60000),
        "Laptops": (["Ultrabook 14", "Gaming Laptop 15", "Student Laptop", "2-in-1 Laptop"], 30000, 110000),
        "Accessories": (
            ["Wireless Earbuds", "Power Bank 20000mAh", "Smartwatch", "USB-C Charger", "Bluetooth Speaker"],
            500,
            6000,
        ),
    },
    "Fashion": {
        "Men": (["Cotton Kurta", "Slim Fit Jeans", "Formal Shirt", "Polo T-Shirt"], 500, 3000),
        "Women": (["Silk Saree", "Anarkali Kurti", "Palazzo Set", "Denim Jacket"], 700, 6000),
        "Footwear": (["Running Shoes", "Leather Sandals", "Kolhapuri Chappals", "Sneakers"], 600, 5000),
    },
    "Home & Kitchen": {
        "Cookware": (["Pressure Cooker 5L", "Non-stick Tawa", "Kadai Set", "Steel Dinner Set"], 600, 4000),
        "Appliances": (["Mixer Grinder", "Air Fryer", "Water Purifier", "Induction Cooktop"], 2000, 15000),
        "Decor": (["Brass Diya Set", "Wall Clock", "Cushion Covers", "Table Lamp"], 300, 2500),
    },
    "Beauty": {
        "Skincare": (["Sunscreen SPF50", "Vitamin C Serum", "Face Wash", "Moisturiser"], 200, 1500),
        "Haircare": (["Hair Oil", "Anti-dandruff Shampoo", "Hair Dryer", "Conditioner"], 150, 3000),
    },
    "Grocery": {
        "Staples": (["Basmati Rice 5kg", "Toor Dal 1kg", "Atta 10kg", "Cold-pressed Oil 1L"], 150, 900),
        "Snacks": (["Namkeen Mix", "Dry Fruits Box", "Masala Chips", "Cookies Pack"], 50, 1200),
        "Beverages": (["Assam Tea 500g", "Filter Coffee 500g", "Green Tea", "Fruit Juice 1L"], 100, 700),
    },
    "Books": {
        "Fiction": (["Mystery Novel", "Mythology Retelling", "Romance Novel", "Short Stories"], 199, 699),
        "Non-fiction": (
            ["Personal Finance Guide", "Startup Playbook", "History of India", "Data Science Handbook"],
            249,
            999,
        ),
    },
}
CATEGORY_WEIGHTS = {
    "Electronics": 0.18,
    "Fashion": 0.24,
    "Home & Kitchen": 0.16,
    "Beauty": 0.12,
    "Grocery": 0.22,
    "Books": 0.08,
}
BRAND_PREFIX = ["Nova", "Desi", "Urban", "Prime", "Lotus", "Indus", "Sapphire", "Kesar"]

# Relative order volume by month (Oct/Nov = festive season).
MONTH_SEASON = {1: 0.9, 2: 0.85, 3: 0.95, 4: 0.95, 5: 0.9, 6: 0.85, 7: 0.9, 8: 1.0, 9: 1.05, 10: 1.5, 11: 1.6, 12: 1.2}
PAYMENTS = (["UPI", "Card", "COD", "NetBanking", "Wallet"], [0.45, 0.20, 0.20, 0.08, 0.07])


# ---- Small helpers --------------------------------------------------------------------------
def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def _round_price(x: float) -> float:
    """Make prices look real: 1499, 2999, ..."""
    return max(49.0, round(x / 100) * 100 - 1) if x > 200 else round(x)


# ---- Generators (one per table family) -------------------------------------------------------
def _make_customers(rng: random.Random, n: int) -> list[dict]:
    """Customers sorted by signup date, so the customers existing on a day are a list prefix."""
    signup_start, signup_end = date(2023, 6, 1), date(2025, 11, 30)
    span = (signup_end - signup_start).days
    regions = list(REGION_WEIGHTS)
    rows = []
    for _ in range(n):
        region = rng.choices(regions, weights=list(REGION_WEIGHTS.values()))[0]
        city, state = rng.choice(GEO[region])
        # Skew signups earlier: the base grows over time but most customers exist early.
        signup = signup_start + timedelta(days=int(span * (rng.random() ** 1.6)))
        rows.append(
            {
                "customer_name": f"{rng.choice(FIRST)} {rng.choice(LAST)}",
                "city": city,
                "state": state,
                "region": region,
                "segment": rng.choices(["Consumer", "Corporate", "Small Business"], [0.72, 0.12, 0.16])[0],
                "signup_date": signup,
            }
        )
    rows.sort(key=lambda r: r["signup_date"])
    for i, r in enumerate(rows, start=1):
        r["customer_id"] = i
    return rows


def _make_products(rng: random.Random) -> list[dict]:
    """One or two branded products per catalogue item."""
    rows, pid = [], 1
    for category, subs in CATALOGUE.items():
        for sub, (items, lo, hi) in subs.items():
            for item in items:
                for _ in range(rng.choice([1, 2])):
                    price = _round_price(rng.uniform(lo, hi))
                    rows.append(
                        {
                            "product_id": pid,
                            "product_name": f"{rng.choice(BRAND_PREFIX)} {item}",
                            "category": category,
                            "sub_category": sub,
                            "unit_price": _money(price),
                            "unit_cost": _money(price * rng.uniform(0.55, 0.80)),
                        }
                    )
                    pid += 1
    return rows


def _daily_intensity() -> list[tuple[date, float]]:
    """Relative order volume per day: growth x seasonality x weekend bump."""
    days = [START + timedelta(days=i) for i in range((END - START).days + 1)]
    out = []
    for i, d in enumerate(days):
        growth = 1 + 0.45 * i / len(days)
        weekend = 1.15 if d.weekday() >= 5 else 1.0
        out.append((d, growth * MONTH_SEASON[d.month] * weekend))
    return out


def _order_status(rng: random.Random, d: date, payment: str, has_fashion: bool) -> str:
    """COD cancels more; Fashion returns more; the last week is still in transit."""
    cancel_p = 0.13 if payment == "COD" else 0.06
    return_p = 0.14 if has_fashion else 0.04
    r = rng.random()
    if r < cancel_p:
        return "cancelled"
    if r < cancel_p + return_p:
        return "returned"
    return "shipped" if (END - d).days < 7 else "delivered"


def _make_orders(
    rng: random.Random, cust_rows: list[dict], prod_rows: list[dict], n_orders: int
) -> tuple[list[dict], list[dict]]:
    """Orders and order lines, day by day, with the planted regional patterns."""
    by_category: dict[str, list[dict]] = {c: [] for c in CATALOGUE}
    for p in prod_rows:
        by_category[p["category"]].append(p)
    signup_dates = [r["signup_date"] for r in cust_rows]
    south_idx = [i for i, r in enumerate(cust_rows) if r["region"] == "South"]
    categories = list(CATEGORY_WEIGHTS)

    intensity = _daily_intensity()
    scale = n_orders / sum(w for _, w in intensity)
    order_rows, item_rows = [], []
    oid, iid = 1, 1

    for d, w in intensity:
        # Poisson-ish count: integer part plus a coin flip for the fraction.
        expected = w * scale
        count = int(expected) + (1 if rng.random() < expected - int(expected) else 0)
        n_eligible = bisect.bisect_right(signup_dates, d)  # customers who had signed up by day d
        if n_eligible == 0:
            continue

        for _ in range(count):
            cust = cust_rows[rng.randrange(n_eligible)]
            # Planted pattern 1: East slumps in Q4 2025.
            if cust["region"] == "East" and d >= date(2025, 10, 1) and rng.random() < 0.45:
                continue
            # Planted pattern 2: South takes a growing share of 2025 orders.
            if cust["region"] != "South" and d.year == 2025 and rng.random() < 0.10:
                n_south = bisect.bisect_left(south_idx, n_eligible)
                if n_south:
                    cust = cust_rows[south_idx[rng.randrange(n_south)]]

            payment = rng.choices(*PAYMENTS)[0]
            n_lines = rng.choices([1, 2, 3, 4], [0.55, 0.27, 0.12, 0.06])[0]
            festive = d.month in (10, 11)
            lines, has_fashion = [], False
            for _ in range(n_lines):
                cat = rng.choices(categories, weights=list(CATEGORY_WEIGHTS.values()))[0]
                prod = rng.choice(by_category[cat])
                has_fashion |= cat == "Fashion"
                if cat == "Grocery":
                    qty = rng.choices([1, 2, 3, 4, 5], [0.5, 0.25, 0.15, 0.06, 0.04])[0]
                else:
                    qty = rng.choices([1, 2, 3], [0.82, 0.14, 0.04])[0]
                discounts = [0.0, 0.05, 0.10, 0.20, 0.30] if festive else [0.0, 0.0, 0.05, 0.10]
                lines.append(
                    {
                        "order_item_id": iid,
                        "order_id": oid,
                        "product_id": prod["product_id"],
                        "quantity": qty,
                        "unit_price": prod["unit_price"],
                        "discount": Decimal(str(rng.choice(discounts))),
                    }
                )
                iid += 1

            order_rows.append(
                {
                    "order_id": oid,
                    "customer_id": cust["customer_id"],
                    "order_date": d,
                    "status": _order_status(rng, d, payment, has_fashion),
                    "payment_method": payment,
                    "channel": rng.choices(["app", "web"], [0.6, 0.4])[0],
                }
            )
            item_rows.extend(lines)
            oid += 1

    return order_rows, item_rows


# ---- Public API -----------------------------------------------------------------------------
def generate(n_customers: int = 2500, n_orders: int = 16000, seed: int = 42) -> dict[str, list[dict]]:
    """Return rows for every table. Same seed -> same data."""
    rng = random.Random(seed)
    cust_rows = _make_customers(rng, n_customers)
    prod_rows = _make_products(rng)
    order_rows, item_rows = _make_orders(rng, cust_rows, prod_rows, n_orders)
    return {"customers": cust_rows, "products": prod_rows, "orders": order_rows, "order_items": item_rows}


def seed(engine: Engine, force: bool = False, **kwargs) -> dict[str, int]:
    """Create tables and load data; return row counts. Skips if data exists unless force=True."""
    if force:
        metadata.drop_all(engine)
    metadata.create_all(engine)
    with engine.connect() as conn:
        existing = conn.execute(select(func.count()).select_from(orders)).scalar_one()
    if existing and not force:
        return {}

    data = generate(**kwargs)
    with engine.begin() as conn:  # one transaction: all tables load or none do
        for table in (customers, products, orders, order_items):
            rows = data[table.name]
            for i in range(0, len(rows), 5000):  # batch inserts to keep memory flat
                conn.execute(table.insert(), rows[i : i + 5000])
    return {name: len(rows) for name, rows in data.items()}


def main() -> None:
    """CLI entry point: python -m app.db.seed [--force]."""
    parser = argparse.ArgumentParser(description="Seed the demo store database.")
    parser.add_argument("--force", action="store_true", help="drop and recreate all tables")
    args = parser.parse_args()
    owner, _ = make_engines(get_settings().database_url)
    counts = seed(owner, force=args.force)
    print(f"Seeded: {counts}" if counts else "Data already present - nothing to do (use --force to reseed).")


if __name__ == "__main__":
    main()
