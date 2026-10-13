import streamlit as st
import requests
import time

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Campus Express", layout="wide")
st.title("🚀 Campus Express App")

tab1, tab2 = st.tabs(["🎓 Student App (Order & Pay)", "🍔 Canteen Dashboard"])


with tab1:
    st.info("💳 **Campus Wallet Balance:** ₹500.00")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("🍔 Order Canteen Food")
        with st.form("food_order_form"):
            student_id = st.number_input("Student ID", min_value=1, value=1)
            item_id = st.number_input("Item ID (1 for Samosa, 2 for Coffee)", min_value=1, value=1)
            qty = st.number_input("Quantity", min_value=1, value=1)
            
            submit_food = st.form_submit_button("Pay via Wallet & Order")
            
            if submit_food:
                with st.spinner("Processing Payment..."):
                    time.sleep(1) # Simulating payment gateway delay
                    res = requests.post(
                        f"{API_URL}/api/canteen/order", 
                        json={"student_id": student_id, "item_id": item_id, "quantity": qty}
                    )
                    
                if res.status_code == 200:
                    data = res.json()
                    st.success("✅ Payment Successful!")
                    # Digital Receipt
                    st.markdown(f"""
                    ### 🧾 DIGITAL RECEIPT
                    * **Order ID:** `#{data['order_id']}`
                    * **Amount Paid:** ₹{data['total_price']}
                    * **Status:** Sent to Kitchen
                    
                    *Show this Order ID at the canteen counter to collect your food.*
                    """)
                else:
                    st.error(res.json()["detail"])

    with col2:
        st.subheader("🖨️ Send to Print Shop")
        with st.form("print_upload_form"):
            student_name = st.text_input("Your Name", "Shivansh")
            pages = st.number_input("Total Pages", min_value=1, value=5)
            uploaded_file = st.file_uploader("Upload Document", type=["pdf"])
            
            submit_print = st.form_submit_button("Pay via Wallet & Print")
            
            if submit_print:
                if uploaded_file is None:
                    st.error("Please upload a file first!")
                else:
                    with st.spinner("Processing Payment & Uploading..."):
                        time.sleep(1)
                        # Send the actual physical file to FastAPI
                        files = {"file": (uploaded_file.name, uploaded_file.getvalue(), "application/pdf")}
                        data = {"student_name": student_name, "page_count": pages}
                        
                        res = requests.post(f"{API_URL}/api/print/upload", data=data, files=files)
                        
                    if res.status_code == 200:
                        data = res.json()
                        st.success("✅ Payment & Upload Successful!")
                        # Digital Receipt
                        st.markdown(f"""
                        ### 🎫 PRINT TICKET
                        * **Job ID:** `{data['job_id']}`
                        * **File:** {uploaded_file.name}
                        * **Queue Status:** Spooled
                        
                        *Your file will print automatically. Show this Job ID at the shop if asked.*
                        """)
                    else:
                        st.error("Failed to upload document.")

with tab2:
    st.subheader("🍳 Live Kitchen Queue (Main Canteen)")
    st.write("This dashboard pulls live, locked transactions from the MySQL database.")
    
    if st.button("🔄 Refresh Orders"):
        # Vendor ID 1 is the Main Canteen in our database
        res = requests.get(f"{API_URL}/api/canteen/orders/1")
        if res.status_code == 200:
            orders = res.json()["orders"]
            if not orders:
                st.success("No pending orders. Kitchen is caught up!")
            else:
                for order in orders:
                    st.info(f"**Order #{order['order_id']}** | Amount: ₹{order['total_amount']} | Status: {order['status'].upper()}")
        else:
            st.error("Could not connect to database.")
