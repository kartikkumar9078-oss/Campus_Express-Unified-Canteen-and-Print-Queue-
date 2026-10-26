import os
import heapq
import uuid
import mysql.connector
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="Campus Express Backend Engine")

# --- STORAGE SETUP FOR PRINT FILES ---
PRINT_STORAGE_DIR = "uploaded_prints"
os.makedirs(PRINT_STORAGE_DIR, exist_ok=True)

# --- OS LOGIC: SJF PRINT SPOOLER ---
class PrintSpooler:
    def __init__(self):
        # Queue stores tuples: (page_count, tie_breaker_counter, job_data)
        self.job_queue = []
        self.counter = 0

    def add_job(self, page_count: int, student_name: str, original_filename: str, stored_filename: str):
        self.counter += 1
        job_id = str(uuid.uuid4())[:8]
        job_data = {
            "job_id": job_id,
            "student_name": student_name,
            "original_filename": original_filename,
            "stored_filename": stored_filename,
            "page_count": page_count,
            "file_path": os.path.join(PRINT_STORAGE_DIR, stored_filename)
        }
        # Heap prioritizes smallest page_count first
        heapq.heappush(self.job_queue, (page_count, self.counter, job_data))
        return job_data

    def pop_job(self):
        if not self.job_queue:
            return None
        _, _, job_data = heapq.heappop(self.job_queue)
        return job_data

spooler = PrintSpooler()

# --- DATABASE CONNECTION ---
def get_db_connection():
    return mysql.connector.connect(
        host="localhost",
        user="root",
        password="ansht1@2#",
        database="campus_express"
    )

# --- CANTEEN VENDOR ENDPOINTS ---
class CanteenOrder(BaseModel):
    student_id: int
    item_id: int
    quantity: int

@app.post("/api/canteen/order")
def place_canteen_order(order: CanteenOrder):
    """Processes food orders with ACID row-level locks on inventory."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        conn.start_transaction()
        
        # Row-level lock (FOR UPDATE) prevents race conditions across concurrent orders
        cursor.execute(
            "SELECT stock_count, price, vendor_id FROM Inventory WHERE item_id = %s FOR UPDATE", 
            (order.item_id,)
        )
        item = cursor.fetchone()
        
        if not item or item['stock_count'] < order.quantity:
            raise HTTPException(status_code=400, detail="Insufficient stock")
        
        new_stock = item['stock_count'] - order.quantity
        cursor.execute(
            "UPDATE Inventory SET stock_count = %s WHERE item_id = %s", 
            (new_stock, order.item_id)
        )
        
        total_price = item['price'] * order.quantity
        cursor.execute(
            "INSERT INTO Orders (student_id, vendor_id, order_type, total_amount) VALUES (%s, %s, 'canteen', %s)",
            (order.student_id, item['vendor_id'], total_price)
        )
        order_id = cursor.lastrowid
        
        conn.commit()
        return {
            "status": "success",
            "order_id": order_id,
            "total_price": total_price,
            "remaining_stock": new_stock
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        cursor.close()
        conn.close()

@app.get("/api/canteen/orders/{vendor_id}")
def get_vendor_canteen_orders(vendor_id: int):
    """Allows canteen vendors to pull active pending orders."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM Orders WHERE vendor_id = %s AND order_type = 'canteen' ORDER BY created_at DESC", 
            (vendor_id,)
        )
        orders = cursor.fetchall()
        return {"status": "success", "orders": orders}
    finally:
        cursor.close()
        conn.close()

# --- PRINT SHOP ENDPOINTS ---
@app.post("/api/print/upload")
async def upload_print_job(
    student_name: str = Form(...),
    page_count: int = Form(...),
    file: UploadFile = File(...)
):
    """Student endpoint: Saves binary PDF to disk and adds metadata to SJF Queue."""
    file_ext = os.path.splitext(file.filename)[1]
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    file_path = os.path.join(PRINT_STORAGE_DIR, unique_filename)

    # Write file content to server disk
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    job = spooler.add_job(
        page_count=page_count,
        student_name=student_name,
        original_filename=file.filename,
        stored_filename=unique_filename
    )

    return {
        "status": "queued",
        "message": f"File '{file.filename}' successfully uploaded and spooled.",
        "job_id": job["job_id"],
        "page_count": page_count,
        "queue_length": len(spooler.job_queue)
    }

@app.get("/api/print/next")
def fetch_next_print_job():
    """Print shop daemon/app endpoint: Pops the shortest job from SJF Spooler."""
    job = spooler.pop_job()
    if not job:
        return {"status": "empty", "message": "No print jobs in queue"}
    
    return {
        "status": "ready",
        "job_id": job["job_id"],
        "student_name": job["student_name"],
        "filename": job["original_filename"],
        "page_count": job["page_count"],
        "download_url": f"http://127.0.0.1:8000/api/print/download/{job['stored_filename']}"
    }

@app.get("/api/print/download/{filename}")
def download_print_file(filename: str):
    """Print shop machine endpoint: Downloads the raw PDF for automated printing."""
    file_path = os.path.join(PRINT_STORAGE_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found on server")
    
    return FileResponse(path=file_path, filename=filename, media_type='application/pdf')