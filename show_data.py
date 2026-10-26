"""
Campus Express — Data Viewer
Run this script to show all stored data to the examiner.
Usage: python show_data.py
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "web_app", "campus_express.db")

def separator(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def show_table(conn, label, query, columns):
    separator(label)
    rows = conn.execute(query).fetchall()
    if not rows:
        print("  (no records yet)")
        return
    header = " | ".join(f"{c:<20}" for c in columns)
    print("  " + header)
    print("  " + "-" * len(header))
    for row in rows:
        print("  " + " | ".join(f"{str(v):<20}" for v in row))
    print(f"\n  Total: {len(rows)} record(s)")

conn = sqlite3.connect(DB_PATH)

show_table(conn, "STUDENTS (users table)",
    "SELECT id, name, email, phone, role, ROUND(balance,2) FROM users",
    ["ID", "Name", "Email", "Phone", "Role", "Balance (Rs)"])

show_table(conn, "VENDORS (canteen & print shop)",
    "SELECT id, name, email, role, shop_name, CASE is_open WHEN 1 THEN 'Open' ELSE 'Closed' END FROM vendors",
    ["ID", "Name", "Email", "Role", "Shop Name", "Status"])

show_table(conn, "MENU ITEMS",
    "SELECT id, name, price, category, stock, CASE is_available WHEN 1 THEN 'Yes' ELSE 'No' END FROM menu_items",
    ["ID", "Item Name", "Price (Rs)", "Category", "Stock", "Available"])

show_table(conn, "ORDERS",
    """SELECT o.id, u.name, v.shop_name, o.order_type, o.total_amount, o.status, o.payment_ref
       FROM orders o
       JOIN users u ON o.student_id = u.id
       JOIN vendors v ON o.vendor_id = v.id
       ORDER BY o.id DESC""",
    ["ID", "Student", "Shop", "Type", "Amount (Rs)", "Status", "Payment Ref"])

show_table(conn, "PRINT JOBS",
    """SELECT pj.id, u.name, pj.original_filename, pj.page_count, pj.copies, pj.print_type, pj.total_pages
       FROM print_jobs pj
       JOIN orders o ON pj.order_id = o.id
       JOIN users u ON o.student_id = u.id""",
    ["ID", "Student", "File", "Pages", "Copies", "Type", "Total Pgs"])

show_table(conn, "PRINT PRICING",
    """SELECT v.shop_name, pp.bw_price_per_page, pp.color_price_per_page, pp.updated_at
       FROM print_pricing pp JOIN vendors v ON pp.vendor_id = v.id""",
    ["Shop", "B&W Rs/page", "Color Rs/page", "Last Updated"])

conn.close()

separator("DATABASE LOCATION")
print(f"  File : {DB_PATH}")
print(f"  Size : {os.path.getsize(DB_PATH) / 1024:.1f} KB")
print(f"  Engine: SQLite 3 (built into Python)")
print()
