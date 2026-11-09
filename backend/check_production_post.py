import requests

url = (
    "https://worksphere-lead-generation.onrender.com"
    "/api/reports/ae86fd7d-d13f-41bc-a6d2-cb0625fc4d95/process"
)

headers = {
    "Origin": "https://worksphere-lead-generation.vercel.app",
    "Content-Type": "application/json",
}

try:
    response = requests.post(
        url,
        headers=headers,
        json={},
        timeout=120
    )

    print("STATUS:", response.status_code)

    print("\nRESPONSE HEADERS:")
    for key, value in response.headers.items():
        print(f"{key}: {value}")

    print("\nRESPONSE BODY:")
    print(response.text)

except requests.RequestException as error:
    print("CONNECTION ERROR:", error)