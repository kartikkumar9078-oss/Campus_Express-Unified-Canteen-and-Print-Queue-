# Campus Express 

**A Unified Canteen & Print Queue Management System**

Campus Express is a digital solution designed to eliminate the chaos of manual queues at university canteens and print shops during short breaks. By replacing physical lines with an organized digital queue, this system empowers students to pre-order food and submit print jobs directly from their classrooms, ensuring they have time to eat and prepare before their next class.

## Key Features

*   **Remote Ordering:** Order food and submit document print jobs via a unified Android mobile application.
*   **Vendor Dashboard:** A dedicated digital dashboard for canteen and print shop staff to manage incoming orders seamlessly.
*   **Smart Queueing (OS Integration):** Utilizes a Shortest Job First (SJF) scheduling algorithm for the print spooler queue to optimize wait times[cite: 2].
*   **Process Synchronization:** Implements Mutex locks to ensure multiple canteen workers do not process the exact same order simultaneously[cite: 2].
*   **Secure Transactions (DBMS Integration):** Powered by a robust SQL database enforcing ACID properties, ensuring money is never deducted for out-of-stock items[cite: 2].
*   **Digital Receipts:** Secure online payments integrated with digital receipts for quick, hassle-free pickups[cite: 2].

##  Technology Stack

*   **Frontend (Mobile App):** Java (Android)[cite: 2]
*   **Backend Logic & Scheduling:** Python[cite: 2]
*   **Database:** MySQL[cite: 2]
*   **Communication:** REST APIs[cite: 2]

##  System Architecture

1.  **Student App:** Users interface with the Android app to browse inventory, upload files, and process payments[cite: 2].
2.  **API Layer:** REST APIs route the frontend requests to the backend server[cite: 2].
3.  **Core Logic:** Python backend handles task scheduling (SJF) and Mutex lock synchronization[cite: 2].
4.  **Database:** MySQL tracks live inventory, handles wallet transactions, and logs order statuses[cite: 2].
5.  **Vendor Dashboard:** Real-time prioritized queue displayed on tablets/laptops for vendors to fulfill[cite: 2].

##  Installation & Setup 

*(Instructions will be updated as development progresses)*

1. Clone the repository:
   ```bash
   