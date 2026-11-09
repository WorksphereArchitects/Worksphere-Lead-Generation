import requests

BASE_URL = "https://worksphere-lead-generation.onrender.com"
REPORT_ID = "15b8da70-d006-4dab-9de1-7080aee65121"

url = f"{BASE_URL}/api/reports/{REPORT_ID}/status"

headers = {
    "Origin": "https://worksphere-lead-generation.vercel.app"
}

try:
    response = requests.get(url, headers=headers, timeout=60)

    print("STATUS:", response.status_code)
    print("HEADERS:", dict(response.headers))
    print("BODY:", response.text)

except requests.RequestException as error:
    print("ERROR:", error)