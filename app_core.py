import heapq
import threading
import time


order_lock = threading.Lock()
canteen_stock = {"Samosa": 5}

def process_canteen_order(student_name, item, qty):
    """Prevents race conditions when two students order simultaneously."""
    global canteen_stock
    
    with order_lock:
        print(f"\n[LOCK ACQUIRED] Processing order for {student_name}...")
        if canteen_stock.get(item, 0) >= qty:
            time.sleep(0.5) # Simulating DB/processing delay
            canteen_stock[item] -= qty
            print(f"[SUCCESS] {qty} {item}(s) assigned to {student_name}. Remaining: {canteen_stock[item]}")
            return True
        else:
            print(f"[FAILED] Out of stock for {student_name}!")
            return False


class PrintSpooler:
    """SJF Queue: Priority given to documents with fewer pages."""
    def __init__(self):
        self.job_queue = [] # Min-Heap priority queue

    def add_job(self, student_name, file_name, page_count):
        # Tuple format: (page_count, student_name, file_name)
        heapq.heappush(self.job_queue, (page_count, student_name, file_name))
        print(f"[SPOOLER] Added '{file_name}' ({page_count} pages) for {student_name}")

    def execute_next_job(self):
        if not self.job_queue:
            print("[SPOOLER] No pending print jobs.")
            return None
        
        pages, student, file = heapq.heappop(self.job_queue)
        print(f"\n[PRINTING NOW] SJF Selected: '{file}' ({pages} pages) for {student}")
        return file


if __name__ == "__main__":
    # Test Mutex
    t1 = threading.Thread(target=process_canteen_order, args=("Shivansh", "Samosa", 3))
    t2 = threading.Thread(target=process_canteen_order, args=("Kartik", "Samosa", 3))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    spooler = PrintSpooler()
    spooler.add_job("Manasvi", "Lab_Report_100pg.pdf", 100)
    spooler.add_job("Gursehaj", "Receipt_1pg.pdf", 1)
    spooler.add_job("Shivansh", "Assignment_5pg.pdf", 5)

    spooler.execute_next_job()
    spooler.execute_next_job()
    spooler.execute_next_job()
