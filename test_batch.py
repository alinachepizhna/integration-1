import json, time, urllib.request, os

token = os.environ["TOKEN"]
item = {
    "client_name": "Batch User",
    "gr_liv_area": 1800,
    "total_bsmt_sf": 1000,
    "garage_area": 500,
    "year_built": 2005,
    "overall_qual": 7,
    "ms_zoning": "RL"
}
data = json.dumps([item] * 10).encode()

# 1. Один пакет з 10 замовленнями (конкурентно)
t0 = time.perf_counter()
req = urllib.request.Request(
    "http://localhost:8000/orders/batch",
    data=data,
    headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
)
with urllib.request.urlopen(req) as resp:
    res_batch = json.loads(resp.read().decode())
t_batch = (time.perf_counter() - t0) * 1000

# 2. 10 окремих послідовних пакетних запитів по 1 замовленню
single_data = json.dumps([item]).encode()
t1 = time.perf_counter()
for _ in range(10):
    req_s = urllib.request.Request(
        "http://localhost:8000/orders/batch",
        data=single_data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req_s) as resp_s:
        resp_s.read()
t_seq = (time.perf_counter() - t1) * 1000

print(f"Batch result total={res_batch['total']}, first item={res_batch['results'][0]}")
print(f"1 batch of 10 orders (parallel asyncio.gather): {t_batch:.2f} ms")
print(f"10 sequential requests of 1 order each:         {t_seq:.2f} ms")
print(f"Speedup:                                        {t_seq / t_batch:.2f}x faster")
