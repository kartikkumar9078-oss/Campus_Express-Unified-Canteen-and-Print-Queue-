import os
import uuid
import secrets
import heapq
import threading
import time
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, send_from_directory
from werkzeug.utils import secure_filename
from database import get_db, hash_password, verify_password, init_db

def generate_ticket_number():
    """Generate a unique, human-readable print ticket number.
    Format: TKT-YYYYMMDD-XXXX  (e.g. TKT-20261026-A3F9)
    The date prefix makes tickets easy to file; the 4-char hex suffix
    keeps them short enough to read aloud at the counter.
    """
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    suffix = uuid.uuid4().hex[:4].upper()
    return f"TKT-{date_str}-{suffix}"

app = Flask(__name__)
app.secret_key = "campus_express_secret_2024_stable_key_xK9mP3"  # Fixed key so sessions persist across restarts

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
FOOD_IMAGE_FOLDER = os.path.join(os.path.dirname(__file__), "uploads", "food_images")
os.makedirs(FOOD_IMAGE_FOLDER, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "jpg", "jpeg", "png"}
FOOD_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}

# --- SJF Print Spooler (in-memory) ---
print_spooler_lock = threading.Lock()
print_queue = []  # min-heap: (page_count, counter, job_id)
spooler_counter = 0

def add_to_spooler(job_id, page_count):
    global spooler_counter
    with print_spooler_lock:
        spooler_counter += 1
        heapq.heappush(print_queue, (page_count, spooler_counter, job_id))

# ─── PRINT FILE CLEANUP (auto-delete after 10 minutes) ───────────────────────

PRINT_FILE_TTL_SECONDS = 10 * 60  # 10 minutes

def _cleanup_old_print_files():
    """Background daemon: runs every 60 s, deletes print files + DB rows older than TTL."""
    while True:
        time.sleep(60)  # check every minute
        try:
            db = get_db()
            # Find print jobs whose order was created more than TTL seconds ago
            expired = db.execute("""
                SELECT pj.id AS job_id, pj.order_id, pj.stored_filename
                FROM print_jobs pj
                JOIN orders o ON pj.order_id = o.id
                WHERE (strftime('%s','now') - strftime('%s', o.created_at)) > ?
            """, (PRINT_FILE_TTL_SECONDS,)).fetchall()

            for row in expired:
                # 1. Delete the physical file
                file_path = os.path.join(UPLOAD_FOLDER, row["stored_filename"])
                try:
                    if os.path.exists(file_path):
                        os.remove(file_path)
                except OSError:
                    pass  # already gone, carry on

                # 2. Remove print_job record (cascades to order_items if any)
                db.execute("DELETE FROM print_jobs WHERE id=?", (row["job_id"],))
                # 3. Remove the parent order record
                db.execute("DELETE FROM orders WHERE id=?", (row["order_id"],))

                print(f"[CLEANUP] Deleted print job #{row['job_id']} "
                      f"(file: {row['stored_filename']}, order: {row['order_id']})")

            db.commit()
            db.close()
        except Exception as exc:
            print(f"[CLEANUP] Error during print cleanup: {exc}")

# Start the cleanup daemon once (guard against Flask debug reloader double-start)
_cleanup_started = False

def start_cleanup_thread():
    global _cleanup_started
    if not _cleanup_started:
        _cleanup_started = True
        t = threading.Thread(target=_cleanup_old_print_files, daemon=True, name="PrintCleanup")
        t.start()
        print("[CLEANUP] Print-file cleanup thread started (TTL = 10 min)")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def allowed_food_image(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in FOOD_IMAGE_EXTENSIONS

def save_food_image(file_obj):
    """Save an uploaded food image and return its stored filename, or None on failure."""
    if not file_obj or file_obj.filename == "":
        return None
    if not allowed_food_image(file_obj.filename):
        return None
    ext = secure_filename(file_obj.filename).rsplit(".", 1)[-1].lower()
    stored_name = uuid.uuid4().hex + "." + ext
    file_obj.save(os.path.join(FOOD_IMAGE_FOLDER, stored_name))
    return stored_name

# ─── AUTH ROUTES ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        role = request.form.get("role")
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        
        if not all([role, name, email, phone, password]):
            return jsonify({"success": False, "message": "All fields are required."})
        
        pw_hash, pw_salt = hash_password(password)
        db = get_db()
        try:
            if role == "student":
                db.execute(
                    "INSERT INTO users (name, email, phone, password_hash, password_salt, role) VALUES (?,?,?,?,?,?)",
                    (name, email, phone, pw_hash, pw_salt, "student")
                )
            else:
                shop_name = request.form.get("shop_name", "").strip()
                description = request.form.get("description", "").strip()
                if not shop_name:
                    return jsonify({"success": False, "message": "Shop name is required."})
                db.execute(
                    "INSERT INTO vendors (name, email, phone, password_hash, password_salt, role, shop_name, description) VALUES (?,?,?,?,?,?,?,?)",
                    (name, email, phone, pw_hash, pw_salt, role, shop_name, description)
                )
                vendor_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
                if role == "print_shop":
                    db.execute(
                        "INSERT INTO print_pricing (vendor_id, bw_price_per_page, color_price_per_page) VALUES (?,?,?)",
                        (vendor_id, 1.5, 6.0)
                    )
                elif role == "canteen":
                    # Save food items submitted during registration
                    idx = 0
                    while True:
                        item_name = request.form.get(f"item_name_{idx}", "").strip()
                        if not item_name:
                            break
                        try:
                            item_price = float(request.form.get(f"item_price_{idx}", "0"))
                        except ValueError:
                            item_price = 0.0
                        item_category = request.form.get(f"item_category_{idx}", "Food").strip()
                        item_desc = request.form.get(f"item_description_{idx}", "").strip()
                        try:
                            item_stock = int(request.form.get(f"item_stock_{idx}", "50"))
                        except ValueError:
                            item_stock = 50
                        item_emoji = request.form.get(f"item_emoji_{idx}", "🍽️").strip()
                        image_url = None
                        img_key = f"item_image_{idx}"
                        if img_key in request.files:
                            stored = save_food_image(request.files[img_key])
                            if stored:
                                image_url = "/api/food-image/" + stored
                        db.execute(
                            "INSERT INTO menu_items (vendor_id, name, description, price, category, stock, image_emoji, image_url) VALUES (?,?,?,?,?,?,?,?)",
                            (vendor_id, item_name, item_desc, item_price, item_category, item_stock, item_emoji, image_url)
                        )
                        idx += 1
            db.commit()
            return jsonify({"success": True, "message": "Account created! Please log in."})
        except Exception as e:
            if "UNIQUE constraint failed" in str(e):
                return jsonify({"success": False, "message": "Email already registered."})
            return jsonify({"success": False, "message": str(e)})
        finally:
            db.close()
    return render_template("auth.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "student")

        db = get_db()
        try:
            if role == "student":
                user = db.execute("SELECT * FROM users WHERE email=? AND role='student'", (email,)).fetchone()
                if user and verify_password(password, user["password_hash"], user["password_salt"]):
                    session["user_id"] = user["id"]
                    session["user_name"] = user["name"]
                    session["user_role"] = "student"
                    session["user_email"] = user["email"]
                    return jsonify({"success": True, "redirect": url_for("student_dashboard")})
            else:
                vendor = db.execute("SELECT * FROM vendors WHERE email=? AND role=?", (email, role)).fetchone()
                if vendor and verify_password(password, vendor["password_hash"], vendor["password_salt"]):
                    session["user_id"] = vendor["id"]
                    session["user_name"] = vendor["name"]
                    session["user_role"] = role
                    session["shop_name"] = vendor["shop_name"]
                    if role == "canteen":
                        return jsonify({"success": True, "redirect": url_for("canteen_dashboard")})
                    else:
                        return jsonify({"success": True, "redirect": url_for("print_dashboard")})
            return jsonify({"success": False, "message": "Invalid email or password."})
        finally:
            db.close()
    return render_template("auth.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))

# ─── STUDENT DASHBOARD ────────────────────────────────────────────────────────

@app.route("/student")
def student_dashboard():
    if session.get("user_role") != "student":
        return redirect(url_for("index"))
    db = get_db()
    student = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
    canteens = db.execute("SELECT * FROM vendors WHERE role='canteen' AND is_open=1").fetchall()
    print_shops = db.execute("SELECT * FROM vendors WHERE role='print_shop' AND is_open=1").fetchall()
    
    # Recent orders
    orders = db.execute("""
        SELECT o.*, v.shop_name, v.role as vendor_type 
        FROM orders o JOIN vendors v ON o.vendor_id = v.id
        WHERE o.student_id=? ORDER BY o.created_at DESC LIMIT 10
    """, (session["user_id"],)).fetchall()
    
    db.close()
    return render_template("student_dashboard.html", student=student, canteens=canteens, print_shops=print_shops, orders=orders)

@app.route("/api/menu/<int:vendor_id>")
def get_menu(vendor_id):
    db = get_db()
    items = db.execute(
        "SELECT * FROM menu_items WHERE vendor_id=? AND is_available=1 ORDER BY category, name",
        (vendor_id,)
    ).fetchall()
    pricing = db.execute("SELECT * FROM print_pricing WHERE vendor_id=?", (vendor_id,)).fetchone()
    vendor = db.execute("SELECT * FROM vendors WHERE id=?", (vendor_id,)).fetchone()
    db.close()
    return jsonify({
        "items": [dict(i) for i in items],
        "pricing": dict(pricing) if pricing else None,
        "vendor": dict(vendor) if vendor else None
    })

@app.route("/api/place_canteen_order", methods=["POST"])
def place_canteen_order():
    if session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Not logged in"})
    
    data = request.get_json()
    vendor_id = data.get("vendor_id")
    items = data.get("items", [])  # [{menu_item_id, quantity}]
    
    if not items:
        return jsonify({"success": False, "message": "Cart is empty"})
    
    db = get_db()
    try:
        # Calculate total
        total = 0.0
        item_details = []
        for cart_item in items:
            menu_item = db.execute("SELECT * FROM menu_items WHERE id=? AND vendor_id=? AND is_available=1",
                                   (cart_item["menu_item_id"], vendor_id)).fetchone()
            if not menu_item:
                return jsonify({"success": False, "message": f"Item not found or unavailable"})
            if menu_item["stock"] < cart_item["quantity"]:
                return jsonify({"success": False, "message": f"Insufficient stock for {menu_item['name']}"})
            subtotal = menu_item["price"] * cart_item["quantity"]
            total += subtotal
            item_details.append((menu_item, cart_item["quantity"], subtotal))

        # Check student balance
        student = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if student["balance"] < total:
            return jsonify({"success": False, "message": f"Insufficient wallet balance. Need ₹{total:.2f}, have ₹{student['balance']:.2f}"})

        # Deduct balance
        payment_ref = "PAY-" + uuid.uuid4().hex[:8].upper()
        db.execute("UPDATE users SET balance = balance - ? WHERE id=?", (total, session["user_id"]))

        # Create order
        db.execute(
            "INSERT INTO orders (student_id, vendor_id, order_type, total_amount, status, payment_status, payment_ref) VALUES (?,?,?,?,?,?,?)",
            (session["user_id"], vendor_id, "canteen", total, "paid", "paid", payment_ref)
        )
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Create order items & update stock
        for menu_item, qty, price_at_order in item_details:
            db.execute(
                "INSERT INTO order_items (order_id, menu_item_id, quantity, price_at_order) VALUES (?,?,?,?)",
                (order_id, menu_item["id"], qty, price_at_order)
            )
            db.execute("UPDATE menu_items SET stock = stock - ? WHERE id=?", (qty, menu_item["id"]))

        db.commit()
        return jsonify({
            "success": True,
            "order_id": order_id,
            "total": total,
            "payment_ref": payment_ref,
            "message": "Order placed & payment successful!"
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        db.close()

@app.route("/api/place_print_order", methods=["POST"])
def place_print_order():
    if session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Not logged in"})
    
    vendor_id = request.form.get("vendor_id", type=int)
    page_count = request.form.get("page_count", type=int)
    copies = request.form.get("copies", type=int, default=1)
    print_type = request.form.get("print_type", "bw")
    
    if "file" not in request.files:
        return jsonify({"success": False, "message": "No file uploaded"})
    
    file = request.files["file"]
    if file.filename == "" or not allowed_file(file.filename):
        return jsonify({"success": False, "message": "Invalid file type. Allowed: PDF, DOC, DOCX, JPG, PNG"})
    
    db = get_db()
    try:
        pricing = db.execute("SELECT * FROM print_pricing WHERE vendor_id=?", (vendor_id,)).fetchone()
        if not pricing:
            return jsonify({"success": False, "message": "Vendor pricing not found"})
        
        price_per_page = pricing["color_price_per_page"] if print_type == "color" else pricing["bw_price_per_page"]
        total_pages = page_count * copies
        total_amount = total_pages * price_per_page

        student = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if student["balance"] < total_amount:
            return jsonify({"success": False, "message": f"Insufficient balance. Need ₹{total_amount:.2f}, have ₹{student['balance']:.2f}"})

        # Save file
        ext = secure_filename(file.filename).rsplit(".", 1)[-1]
        stored_name = uuid.uuid4().hex + "." + ext
        file.save(os.path.join(UPLOAD_FOLDER, stored_name))

        payment_ref = "PRNT-" + uuid.uuid4().hex[:8].upper()
        db.execute("UPDATE users SET balance = balance - ? WHERE id=?", (total_amount, session["user_id"]))
        
        db.execute(
            "INSERT INTO orders (student_id, vendor_id, order_type, total_amount, status, payment_status, payment_ref) VALUES (?,?,?,?,?,?,?)",
            (session["user_id"], vendor_id, "print", total_amount, "paid", "paid", payment_ref)
        )
        order_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]

        ticket_number = generate_ticket_number()

        db.execute("""
            INSERT INTO print_jobs (order_id, original_filename, stored_filename, page_count, copies, print_type, total_pages, ticket_number)
            VALUES (?,?,?,?,?,?,?,?)
        """, (order_id, secure_filename(file.filename), stored_name, page_count, copies, print_type, total_pages, ticket_number))

        db.commit()
        add_to_spooler(order_id, total_pages)

        return jsonify({
            "success": True,
            "order_id": order_id,
            "ticket_number": ticket_number,
            "total": total_amount,
            "payment_ref": payment_ref,
            "total_pages": total_pages,
            "message": "Print job queued & payment successful!"
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        db.close()

@app.route("/api/student/balance")
def get_student_balance():
    if session.get("user_role") != "student":
        return jsonify({"success": False})
    db = get_db()
    student = db.execute("SELECT balance FROM users WHERE id=?", (session["user_id"],)).fetchone()
    db.close()
    return jsonify({"balance": student["balance"]})

@app.route("/api/student/orders")
def get_student_orders():
    if session.get("user_role") != "student":
        return jsonify([])
    db = get_db()
    orders = db.execute("""
        SELECT o.*, v.shop_name, v.role as vendor_type 
        FROM orders o JOIN vendors v ON o.vendor_id = v.id
        WHERE o.student_id=? ORDER BY o.created_at DESC LIMIT 20
    """, (session["user_id"],)).fetchall()
    db.close()
    return jsonify([dict(o) for o in orders])

@app.route("/api/student/topup", methods=["POST"])
def student_topup():
    if session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Not logged in"})
    data = request.get_json()
    amount = float(data.get("amount", 0))
    if amount <= 0:
        return jsonify({"success": False, "message": "Amount must be positive"})
    if amount > 5000:
        return jsonify({"success": False, "message": "Maximum top-up is ₹5000 at a time"})
    db = get_db()
    try:
        db.execute("UPDATE users SET balance = balance + ? WHERE id=?", (amount, session["user_id"]))
        db.commit()
        student = db.execute("SELECT balance FROM users WHERE id=?", (session["user_id"],)).fetchone()
        return jsonify({"success": True, "balance": student["balance"], "message": f"₹{amount:.2f} added to wallet!"})
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        db.close()



# ─── MOCK PAYMENT GATEWAY ────────────────────────────────────────────────────
# This is a testing/mock gateway that simulates real payment processing.
# In production, replace with Razorpay / PayU / Cashfree SDK integration.

@app.route("/api/payment/initiate", methods=["POST"])
def payment_initiate():
    """Step 1: Student requests a payment — gateway creates a transaction record."""
    if session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Not logged in"})

    data = request.get_json()
    amount = float(data.get("amount", 0))
    method = data.get("method", "card")  # card | upi | netbanking

    if amount <= 0 or amount > 5000:
        return jsonify({"success": False, "message": "Amount must be between ₹1 and ₹5000"})
    if method not in ("card", "upi", "netbanking"):
        return jsonify({"success": False, "message": "Invalid payment method"})

    gateway_txn_id = "GW-" + uuid.uuid4().hex[:12].upper()

    db = get_db()
    try:
        db.execute(
            "INSERT INTO payment_transactions (student_id, gateway_txn_id, amount, method, status) VALUES (?,?,?,?,?)",
            (session["user_id"], gateway_txn_id, amount, method, "initiated")
        )
        db.commit()
        return jsonify({
            "success": True,
            "gateway_txn_id": gateway_txn_id,
            "amount": amount,
            "message": "Payment initiated. Awaiting user confirmation."
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        db.close()


@app.route("/api/payment/verify", methods=["POST"])
def payment_verify():
    """Step 2: After user submits payment details, simulate gateway verification."""
    if session.get("user_role") != "student":
        return jsonify({"success": False, "message": "Not logged in"})

    data = request.get_json()
    gateway_txn_id = data.get("gateway_txn_id")
    # In a real gateway: this would contain an encrypted token from the payment page.
    # For testing we accept any non-empty submission and mark it success.
    simulate_fail = data.get("simulate_fail", False)  # can force a failure for demo

    if not gateway_txn_id:
        return jsonify({"success": False, "message": "Missing transaction ID"})

    db = get_db()
    try:
        txn = db.execute(
            "SELECT * FROM payment_transactions WHERE gateway_txn_id=? AND student_id=?",
            (gateway_txn_id, session["user_id"])
        ).fetchone()

        if not txn:
            return jsonify({"success": False, "message": "Transaction not found"})
        if txn["status"] != "initiated":
            return jsonify({"success": False, "message": f"Transaction already {txn['status']}"})

        if simulate_fail:
            db.execute(
                "UPDATE payment_transactions SET status='failed', updated_at=CURRENT_TIMESTAMP WHERE gateway_txn_id=?",
                (gateway_txn_id,)
            )
            db.commit()
            return jsonify({"success": False, "message": "Payment declined by gateway (test failure)"})

        # Simulate SUCCESS — credit wallet
        db.execute(
            "UPDATE payment_transactions SET status='success', wallet_credited=1, updated_at=CURRENT_TIMESTAMP WHERE gateway_txn_id=?",
            (gateway_txn_id,)
        )
        db.execute(
            "UPDATE users SET balance = balance + ? WHERE id=?",
            (txn["amount"], session["user_id"])
        )
        db.commit()

        student = db.execute("SELECT balance FROM users WHERE id=?", (session["user_id"],)).fetchone()
        return jsonify({
            "success": True,
            "gateway_txn_id": gateway_txn_id,
            "amount": txn["amount"],
            "method": txn["method"],
            "balance": student["balance"],
            "message": f"₹{txn['amount']:.2f} added to wallet via {txn['method'].title()}!"
        })
    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "message": str(e)})
    finally:
        db.close()


@app.route("/api/payment/history")
def payment_history():
    """Fetch student's payment gateway transaction history."""
    if session.get("user_role") != "student":
        return jsonify([])
    db = get_db()
    txns = db.execute(
        "SELECT * FROM payment_transactions WHERE student_id=? ORDER BY created_at DESC LIMIT 20",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return jsonify([dict(t) for t in txns])


# ─── CANTEEN DASHBOARD ────────────────────────────────────────────────────────

@app.route("/canteen")
def canteen_dashboard():
    if session.get("user_role") != "canteen":
        return redirect(url_for("index"))
    db = get_db()
    vendor = db.execute("SELECT * FROM vendors WHERE id=?", (session["user_id"],)).fetchone()
    menu_items = db.execute("SELECT * FROM menu_items WHERE vendor_id=? ORDER BY category, name", (session["user_id"],)).fetchall()
    orders = db.execute("""
        SELECT o.*, u.name as student_name, u.phone as student_phone
        FROM orders o JOIN users u ON o.student_id = u.id
        WHERE o.vendor_id=? AND o.order_type='canteen'
        ORDER BY o.created_at DESC LIMIT 50
    """, (session["user_id"],)).fetchall()
    db.close()
    return render_template("canteen_dashboard.html", vendor=vendor, menu_items=menu_items, orders=orders)

@app.route("/api/food-image/<path:filename>")
def serve_food_image(filename):
    """Serve uploaded food item images."""
    return send_from_directory(FOOD_IMAGE_FOLDER, filename)

@app.route("/api/canteen/menu/add", methods=["POST"])
def add_menu_item():
    if session.get("user_role") != "canteen":
        return jsonify({"success": False})
    # Accept multipart/form-data (with optional image) OR JSON
    if request.content_type and "application/json" in request.content_type:
        data = request.get_json()
        image_url = None
    else:
        data = request.form
        image_url = None
        if "image" in request.files:
            stored = save_food_image(request.files["image"])
            if stored:
                image_url = "/api/food-image/" + stored
    db = get_db()
    try:
        db.execute(
            "INSERT INTO menu_items (vendor_id, name, description, price, category, stock, image_emoji, image_url) VALUES (?,?,?,?,?,?,?,?)",
            (session["user_id"], data["name"], data.get("description", ""), float(data["price"]),
             data.get("category", "Food"), int(data.get("stock", 50)), data.get("emoji", "🍽️"), image_url)
        )
        item_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.commit()
        item = db.execute("SELECT * FROM menu_items WHERE id=?", (item_id,)).fetchone()
        return jsonify({"success": True, "item": dict(item)})
    finally:
        db.close()

@app.route("/api/canteen/menu/update/<int:item_id>", methods=["POST"])
def update_menu_item(item_id):
    if session.get("user_role") != "canteen":
        return jsonify({"success": False})
    # Accept multipart/form-data (with optional image) OR JSON
    if request.content_type and "application/json" in request.content_type:
        data = request.get_json()
        new_image_url = None
        update_image = False
    else:
        data = request.form
        new_image_url = None
        update_image = False
        if "image" in request.files:
            stored = save_food_image(request.files["image"])
            if stored:
                new_image_url = "/api/food-image/" + stored
                update_image = True
    db = get_db()
    try:
        if update_image:
            db.execute(
                "UPDATE menu_items SET name=?, description=?, price=?, category=?, stock=?, is_available=?, image_emoji=?, image_url=? WHERE id=? AND vendor_id=?",
                (data["name"], data.get("description", ""), float(data["price"]),
                 data.get("category", "Food"), int(data.get("stock", 50)),
                 int(data.get("is_available", 1)), data.get("emoji", "🍽️"), new_image_url,
                 item_id, session["user_id"])
            )
        else:
            db.execute(
                "UPDATE menu_items SET name=?, description=?, price=?, category=?, stock=?, is_available=?, image_emoji=? WHERE id=? AND vendor_id=?",
                (data["name"], data.get("description", ""), float(data["price"]),
                 data.get("category", "Food"), int(data.get("stock", 50)),
                 int(data.get("is_available", 1)), data.get("emoji", "🍽️"),
                 item_id, session["user_id"])
            )
        db.commit()
        return jsonify({"success": True})
    finally:
        db.close()

@app.route("/api/canteen/menu/delete/<int:item_id>", methods=["DELETE"])
def delete_menu_item(item_id):
    if session.get("user_role") != "canteen":
        return jsonify({"success": False})
    db = get_db()
    db.execute("DELETE FROM menu_items WHERE id=? AND vendor_id=?", (item_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/canteen/order/status/<int:order_id>", methods=["POST"])
def update_canteen_order_status(order_id):
    if session.get("user_role") != "canteen":
        return jsonify({"success": False})
    status = request.get_json().get("status")
    db = get_db()
    db.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND vendor_id=?",
               (status, order_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/canteen/orders/live")
def live_canteen_orders():
    if session.get("user_role") != "canteen":
        return jsonify([])
    db = get_db()
    orders = db.execute("""
        SELECT o.*, u.name as student_name, u.phone as student_phone,
               GROUP_CONCAT(mi.name || ' x' || oi.quantity, ', ') as items_summary
        FROM orders o 
        JOIN users u ON o.student_id = u.id
        LEFT JOIN order_items oi ON o.id = oi.order_id
        LEFT JOIN menu_items mi ON oi.menu_item_id = mi.id
        WHERE o.vendor_id=? AND o.order_type='canteen'
        GROUP BY o.id
        ORDER BY o.created_at DESC LIMIT 30
    """, (session["user_id"],)).fetchall()
    db.close()
    return jsonify([dict(o) for o in orders])

@app.route("/api/canteen/toggle", methods=["POST"])
def toggle_canteen():
    if session.get("user_role") != "canteen":
        return jsonify({"success": False})
    db = get_db()
    vendor = db.execute("SELECT is_open FROM vendors WHERE id=?", (session["user_id"],)).fetchone()
    new_state = 0 if vendor["is_open"] else 1
    db.execute("UPDATE vendors SET is_open=? WHERE id=?", (new_state, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"success": True, "is_open": bool(new_state)})

# ─── PRINT SHOP DASHBOARD ─────────────────────────────────────────────────────

@app.route("/printshop")
def print_dashboard():
    if session.get("user_role") != "print_shop":
        return redirect(url_for("index"))
    db = get_db()
    vendor = db.execute("SELECT * FROM vendors WHERE id=?", (session["user_id"],)).fetchone()
    pricing = db.execute("SELECT * FROM print_pricing WHERE vendor_id=?", (session["user_id"],)).fetchone()
    orders = db.execute("""
        SELECT o.*, u.name as student_name, u.phone as student_phone,
               pj.original_filename, pj.page_count, pj.copies, pj.print_type, pj.total_pages, pj.stored_filename,
               pj.ticket_number
        FROM orders o 
        JOIN users u ON o.student_id = u.id
        LEFT JOIN print_jobs pj ON o.id = pj.order_id
        WHERE o.vendor_id=? AND o.order_type='print'
        ORDER BY pj.total_pages ASC, o.created_at ASC
    """, (session["user_id"],)).fetchall()
    db.close()
    return render_template("print_dashboard.html", vendor=vendor, pricing=pricing, orders=orders)

@app.route("/api/print/order/status/<int:order_id>", methods=["POST"])
def update_print_order_status(order_id):
    if session.get("user_role") != "print_shop":
        return jsonify({"success": False})
    status = request.get_json().get("status")
    db = get_db()
    db.execute("UPDATE orders SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=? AND vendor_id=?",
               (status, order_id, session["user_id"]))
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/print/pricing/update", methods=["POST"])
def update_print_pricing():
    if session.get("user_role") != "print_shop":
        return jsonify({"success": False})
    data = request.get_json()
    db = get_db()
    db.execute(
        "UPDATE print_pricing SET bw_price_per_page=?, color_price_per_page=?, updated_at=CURRENT_TIMESTAMP WHERE vendor_id=?",
        (float(data["bw"]), float(data["color"]), session["user_id"])
    )
    db.commit()
    db.close()
    return jsonify({"success": True})

@app.route("/api/print/download/<filename>")
def download_print_file(filename):
    if session.get("user_role") != "print_shop":
        return redirect(url_for("index"))
    return send_from_directory(UPLOAD_FOLDER, filename, as_attachment=True)

@app.route("/api/print/orders/live")
def live_print_orders():
    if session.get("user_role") != "print_shop":
        return jsonify([])
    db = get_db()
    orders = db.execute("""
        SELECT o.*, u.name as student_name,
               pj.original_filename, pj.page_count, pj.copies, pj.print_type, pj.total_pages, pj.stored_filename,
               pj.ticket_number
        FROM orders o 
        JOIN users u ON o.student_id = u.id
        LEFT JOIN print_jobs pj ON o.id = pj.order_id
        WHERE o.vendor_id=? AND o.order_type='print'
        ORDER BY pj.total_pages ASC, o.created_at ASC
    """, (session["user_id"],)).fetchall()
    db.close()
    return jsonify([dict(o) for o in orders])

if __name__ == "__main__":
    init_db()
    start_cleanup_thread()
    print("\n" + "="*55)
    print("  CAMPUS EXPRESS - Starting Web Server")
    print("="*55)
    print("  Open your browser at: http://127.0.0.1:5000")
    print("="*55 + "\n")
    app.run(debug=True, port=5000, use_reloader=False)
