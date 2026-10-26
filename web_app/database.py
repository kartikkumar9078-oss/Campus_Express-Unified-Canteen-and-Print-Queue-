import sqlite3
import os
import hashlib
import secrets

DB_PATH = os.path.join(os.path.dirname(__file__), "campus_express.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def hash_password(password: str, salt: str = None):
    if salt is None:
        salt = secrets.token_hex(16)
    hashed = hashlib.sha256((password + salt).encode()).hexdigest()
    return hashed, salt

def verify_password(password: str, hashed: str, salt: str):
    return hashlib.sha256((password + salt).encode()).hexdigest() == hashed

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users table (students)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'student',
            balance REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Vendors table (canteen owners & stationery shops)
    c.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            password_salt TEXT NOT NULL,
            role TEXT NOT NULL,  -- 'canteen' or 'print_shop'
            shop_name TEXT NOT NULL,
            description TEXT,
            is_open INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Menu items (canteen)
    c.execute("""
        CREATE TABLE IF NOT EXISTS menu_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            price REAL NOT NULL,
            category TEXT DEFAULT 'Food',
            stock INTEGER DEFAULT 50,
            is_available INTEGER DEFAULT 1,
            image_emoji TEXT DEFAULT '🍽️',
            image_url TEXT DEFAULT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
        )
    """)

    # Migration: add image_url column to existing databases
    try:
        c.execute("ALTER TABLE menu_items ADD COLUMN image_url TEXT DEFAULT NULL")
    except Exception:
        pass  # Column already exists — safe to ignore

    # Print shop pricing config
    c.execute("""
        CREATE TABLE IF NOT EXISTS print_pricing (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            bw_price_per_page REAL DEFAULT 1.0,
            color_price_per_page REAL DEFAULT 5.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (vendor_id) REFERENCES vendors(id) ON DELETE CASCADE
        )
    """)

    # Orders table
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            vendor_id INTEGER NOT NULL,
            order_type TEXT NOT NULL,  -- 'canteen' or 'print'
            status TEXT DEFAULT 'pending',  -- pending, paid, accepted, rejected, completed
            total_amount REAL NOT NULL,
            payment_status TEXT DEFAULT 'unpaid',  -- unpaid, paid
            payment_ref TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (vendor_id) REFERENCES vendors(id)
        )
    """)

    # Canteen order items
    c.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            menu_item_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            price_at_order REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE,
            FOREIGN KEY (menu_item_id) REFERENCES menu_items(id)
        )
    """)

    # Print jobs
    c.execute("""
        CREATE TABLE IF NOT EXISTS print_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            stored_filename TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            copies INTEGER DEFAULT 1,
            print_type TEXT DEFAULT 'bw',  -- 'bw' or 'color'
            total_pages INTEGER NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
    """)

    # Migration: add ticket_number column to existing print_jobs tables
    try:
        c.execute("ALTER TABLE print_jobs ADD COLUMN ticket_number TEXT DEFAULT NULL")
    except Exception:
        pass  # Column already exists — safe to ignore

    # Payment Gateway Transactions (mock/testing gateway)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payment_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            gateway_txn_id TEXT NOT NULL UNIQUE,
            amount REAL NOT NULL,
            method TEXT NOT NULL,        -- 'card', 'upi', 'netbanking'
            status TEXT DEFAULT 'initiated',  -- initiated, success, failed
            wallet_credited INTEGER DEFAULT 0,  -- 1 if balance was added
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users(id)
        )
    """)

    # Seed demo data if empty
    c.execute("SELECT COUNT(*) FROM vendors")
    if c.fetchone()[0] == 0:
        # Seed canteen vendor
        ph, ps = hash_password("canteen123")
        c.execute("""
            INSERT INTO vendors (name, email, phone, password_hash, password_salt, role, shop_name, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("Raj Kumar", "canteen@campus.in", "9876543210", ph, ps, "canteen",
              "Main Canteen", "Serving fresh & delicious campus food daily"))

        canteen_id = c.lastrowid

        # Seed print shop vendor
        ph2, ps2 = hash_password("print123")
        c.execute("""
            INSERT INTO vendors (name, email, phone, password_hash, password_salt, role, shop_name, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ("Suresh Prints", "print@campus.in", "9876500001", ph2, ps2, "print_shop",
              "Central Print Hub", "Fast & affordable printing services"))

        print_id = c.lastrowid

        # Seed menu items
        items = [
            (canteen_id, "Samosa", "Crispy golden samosas with chutney", 15.0, "Snacks", 50, "🥟"),
            (canteen_id, "Cold Coffee", "Chilled blended coffee with milk", 40.0, "Drinks", 30, "☕"),
            (canteen_id, "Veg Thali", "Full meal with roti, dal, sabzi & rice", 80.0, "Meals", 20, "🍱"),
            (canteen_id, "Masala Chai", "Hot spiced Indian tea", 10.0, "Drinks", 100, "🍵"),
            (canteen_id, "Paneer Sandwich", "Grilled paneer with veggies", 35.0, "Snacks", 25, "🥪"),
            (canteen_id, "Maggi Noodles", "Classic 2-minute noodles", 25.0, "Snacks", 40, "🍜"),
        ]
        c.executemany("""
            INSERT INTO menu_items (vendor_id, name, description, price, category, stock, image_emoji)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, items)

        # Seed print pricing
        c.execute("""
            INSERT INTO print_pricing (vendor_id, bw_price_per_page, color_price_per_page)
            VALUES (?, ?, ?)
        """, (print_id, 1.5, 6.0))

        # Seed a student
        ph3, ps3 = hash_password("student123")
        c.execute("""
            INSERT INTO users (name, email, phone, password_hash, password_salt, role, balance)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("Shivansh Gupta", "shivansh@geu.ac.in", "9999999999", ph3, ps3, "student", 500.0))

    conn.commit()
    conn.close()
