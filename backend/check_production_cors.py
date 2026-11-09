import requests

url = (
    "https://worksphere-lead-generation.onrender.com"
    "/api/reports/ae86fd7d-d13f-41bc-a6d2-cb0625fc4d95/process"
)

headers = {
    "Origin": "https://worksphere-lead-generation.vercel.app",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type,authorization",
}

try:
    response = requests.options(
        url,
        headers=headers,
        timeout=60
    )

    print("\nSTATUS:", response.status_code)
    print("\nRESPONSE HEADERS:")

    for key, value in response.headers.items():
        print(f"{key}: {value}")

    print("\nRESPONSE BODY:")
    print(response.text)

except requests.RequestException as error:
    print("CONNECTION ERROR:", error)