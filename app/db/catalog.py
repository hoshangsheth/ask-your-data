"""
Schema catalogue: what the model is told about the data.

The data dictionary and business glossary act as a small semantic layer. They pin down what
"revenue" or "return rate" means, so the model does not invent its own definition.

Usage:
    from app.db.catalog import describe_schema
    text = describe_schema(engine)     # tables, columns, types, descriptions, enum values, glossary
"""

from sqlalchemy import Engine, func, select

from app.db.executor import jsonable
from app.db.models import metadata, orders

# Human descriptions per table/column. "_table" describes the table itself.
DATA_DICTIONARY: dict[str, dict[str, str]] = {
    "customers": {
        "_table": "One row per registered customer.",
        "customer_id": "Primary key.",
        "customer_name": "Full name.",
        "city": "City of the shipping address.",
        "state": "Indian state or union territory.",
        "region": "Sales region.",
        "segment": "Customer segment.",
        "signup_date": "Date the account was created.",
    },
    "products": {
        "_table": "Product catalogue.",
        "product_id": "Primary key.",
        "product_name": "Display name.",
        "category": "Top-level category.",
        "sub_category": "Second-level category.",
        "unit_price": "Current list price in INR.",
        "unit_cost": "Cost to the store per unit in INR.",
    },
    "orders": {
        "_table": "One row per order (order header).",
        "order_id": "Primary key.",
        "customer_id": "FK to customers.customer_id.",
        "order_date": "Date the order was placed.",
        "status": "Order lifecycle status.",
        "payment_method": "Payment method (COD = cash on delivery).",
        "channel": "Sales channel.",
    },
    "order_items": {
        "_table": "One row per product line in an order.",
        "order_item_id": "Primary key.",
        "order_id": "FK to orders.order_id.",
        "product_id": "FK to products.product_id.",
        "quantity": "Units ordered.",
        "unit_price": "Price per unit charged on this order in INR (before discount).",
        "discount": "Fractional discount on this line, e.g. 0.10 = 10% off.",
    },
}

# Low-cardinality columns whose distinct values are listed for the model (it filters on these).
ENUM_COLUMNS: dict[str, list[str]] = {
    "customers": ["region", "segment", "state"],
    "products": ["category", "sub_category"],
    "orders": ["status", "payment_method", "channel"],
}

# Metric definitions. Edit here to change how every answer computes a metric.
BUSINESS_GLOSSARY = """\
- Line revenue = order_items.quantity * order_items.unit_price * (1 - order_items.discount).
- Revenue (also "sales", "GMV") = SUM of line revenue for orders whose status IN ('delivered', 'shipped').
  Cancelled and returned orders never count toward revenue.
- Cost = SUM(order_items.quantity * products.unit_cost) over the same orders. Gross profit = revenue - cost.
  Gross margin = gross profit / revenue.
- Order count = COUNT(DISTINCT orders.order_id) for orders with status IN ('delivered', 'shipped')
  unless the question is explicitly about all orders, cancellations or returns.
- Average order value (AOV) = revenue / order count.
- Cancellation rate = cancelled orders / all orders.
- Return rate = returned orders / (delivered + returned orders).
- Active customer = a customer with at least one delivered or shipped order in the period.
- Quarters are calendar quarters (Q1 = Jan-Mar). Weeks start on Monday.
- Money is Indian rupees (INR)."""


def describe_schema(engine: Engine) -> str:
    """Build the schema text for the model prompt from live metadata plus the catalogue above."""
    lines: list[str] = []
    with engine.connect() as conn:
        # 1) Tables and columns, with keys, descriptions and enum values.
        for table in metadata.sorted_tables:
            docs = DATA_DICTIONARY.get(table.name, {})
            lines.append(f"TABLE {table.name} -- {docs.get('_table', '')}")
            for col in table.columns:
                tags = ["PK"] if col.primary_key else []
                tags += [f"FK -> {fk.target_fullname}" for fk in col.foreign_keys]
                tag = f" [{', '.join(tags)}]" if tags else ""
                desc = docs.get(col.name, "")
                if col.name in ENUM_COLUMNS.get(table.name, []):
                    values = conn.execute(select(col).distinct().order_by(col)).scalars().all()
                    desc += f" Values: {', '.join(map(str, values))}."
                lines.append(f"  {col.name} {col.type}{tag} -- {desc}".rstrip(" -"))
            lines.append("")

        # 2) Date range, so relative dates ("last quarter") resolve against the data, not today.
        lo, hi = conn.execute(select(func.min(orders.c.order_date), func.max(orders.c.order_date))).one()
    lines.append(
        f"orders.order_date ranges from {jsonable(lo)} to {jsonable(hi)}. "
        f"Treat {jsonable(hi)} as 'today' when interpreting relative dates "
        "('last month', 'this year', 'last quarter' = the latest complete calendar quarter)."
    )

    # 3) Metric definitions.
    lines += ["", "BUSINESS DEFINITIONS", BUSINESS_GLOSSARY]
    return "\n".join(lines)
