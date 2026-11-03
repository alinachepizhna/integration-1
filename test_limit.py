import json, urllib.request, urllib.error, os

token = os.environ["TOKEN"]
item = {
    "client_name": "Overflow",
    "gr_liv_area": 1500,
    "total_bsmt_sf": 800,
    "garage_area": 400,
    "year_built": 2000,
    "overall_qual": 6,
    "ms_zoning": "RL"
}
# Надсилаємо 51 елемент (більше за ліміт BATCH_MAX_ITEMS = 50)
req = urllib.request.Request(
    "http://localhost:8000/orders/batch",
    data=json.dumps([item] * 51).encode(),
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
)

try:
    urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    print(f"Status Code for 51 items: {e.code} {e.reason}")
    print(f"Response body: {e.read().decode()}")
