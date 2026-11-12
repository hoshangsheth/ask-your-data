"""
Physical schema of the demo store: four tables defined with SQLAlchemy Core.

These definitions are used to create the tables (app/db/seed.py), to describe them to the model
(app/db/catalog.py) and to allow-list which tables generated SQL may read (app/sql/guard.py).

To add a table: define it here, describe it in DATA_DICTIONARY (catalog.py), and load data for it
in seed.py. ALLOWED_TABLES updates automatically.
"""

from sqlalchemy import Column, Date, ForeignKey, Index, Integer, MetaData, Numeric, String, Table

metadata = MetaData()

# One row per registered customer.
customers = Table(
    "customers",
    metadata,
    Column("customer_id", Integer, primary_key=True),
    Column("customer_name", String(80), nullable=False),
    Column("city", String(40), nullable=False),
    Column("state", String(40), nullable=False),
    Column("region", String(10), nullable=False),
    Column("segment", String(20), nullable=False),
    Column("signup_date", Date, nullable=False),
)

# Product catalogue. Money columns are NUMERIC so arithmetic is exact on every database.
products = Table(
    "products",
    metadata,
    Column("product_id", Integer, primary_key=True),
    Column("product_name", String(80), nullable=False),
    Column("category", String(30), nullable=False),
    Column("sub_category", String(30), nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("unit_cost", Numeric(10, 2), nullable=False),
)

# Order header: one row per order.
orders = Table(
    "orders",
    metadata,
    Column("order_id", Integer, primary_key=True),
    Column("customer_id", Integer, ForeignKey("customers.customer_id"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("status", String(12), nullable=False),
    Column("payment_method", String(12), nullable=False),
    Column("channel", String(8), nullable=False),
    Index("ix_orders_order_date", "order_date"),
    Index("ix_orders_customer_id", "customer_id"),
)

# Order lines: one row per product in an order.
order_items = Table(
    "order_items",
    metadata,
    Column("order_item_id", Integer, primary_key=True),
    Column("order_id", Integer, ForeignKey("orders.order_id"), nullable=False),
    Column("product_id", Integer, ForeignKey("products.product_id"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(10, 2), nullable=False),
    Column("discount", Numeric(4, 2), nullable=False),
    Index("ix_order_items_order_id", "order_id"),
    Index("ix_order_items_product_id", "product_id"),
)

# Tables that model-generated SQL is allowed to read.
ALLOWED_TABLES: frozenset[str] = frozenset(metadata.tables)
