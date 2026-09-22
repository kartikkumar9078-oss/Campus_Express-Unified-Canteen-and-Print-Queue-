import requests
with open("lab_report.pdf", "w") as f:
    f.write("This is a dummy PDF file for testing.")

url = "http://127.0.0.1:8000/api/print/upload"
data = {"student_name": "Shivansh", "page_count": 5}
files = {"file": open("lab_report.pdf", "rb")}

response = requests.post(url, data=data, files=files)
print("Student Upload Response:", response.json())