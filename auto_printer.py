import os
import time
import requests
import subprocess

API_BASE_URL = "http://127.0.0.1:8000"
POLL_INTERVAL = 10  # Checks the queue every 10 seconds
LOCAL_PRINT_DIR = "vendor_downloads"

# Ensure the download folder exists on the vendor's machine
os.makedirs(LOCAL_PRINT_DIR, exist_ok=True)

def check_and_print():
    try:
        # 1. Ask FastAPI for the next job (SJF logic handled by backend)
        response = requests.get(f"{API_BASE_URL}/api/print/next")
        if response.status_code != 200:
            return

        data = response.json()
        
        if data.get("status") == "empty":
            return  # Silently wait if there are no jobs

        # 2. Extract job metadata
        job_id = data["job_id"]
        filename = data["filename"]
        download_url = data["download_url"]
        student = data["student_name"]
        pages = data["page_count"]

        print(f"\n[+] NEW JOB INCOMING: '{filename}' for {student} ({pages} pages)")
        print(f"[*] Downloading file from server...")

        # 3. Download the binary file
        file_resp = requests.get(download_url)
        local_file_path = os.path.join(LOCAL_PRINT_DIR, f"{job_id}_{filename}")
        
        with open(local_file_path, "wb") as f:
            f.write(file_resp.content)

        print(f"[*] Download complete. Sending to OS Print Spooler...")

        # 4. Trigger the hardware print natively (macOS)
        # Bypasses all popups and prints silently
        subprocess.run(["lpr", local_file_path])
        
        print(f"[SUCCESS] Hardware print triggered for {filename}!")

    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")

if __name__ == "__main__":
    print("==============================================")
    print(" 🖨️  CENTRAL PRINT HUB - AUTO DAEMON ACTIVE  ")
    print("==============================================")
    print("Listening for incoming print jobs...")
    
    while True:
        check_and_print()
        time.sleep(POLL_INTERVAL)