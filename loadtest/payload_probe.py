import json, os, time, statistics, urllib.request
BASE = os.environ["BASE_URL"]
ROW = {"temp_c": 0, "vibration_mm_s": 0, "pressure_kpa": 0,
       "hours_since_service": 0, "load_pct": 0, "ambient_humidity": 0}  # แก้เป็นค่า valid
KEY = "rows"   # แก้ตาม service/schemas.py (ถ้า body เป็น list ล้วนให้ตั้ง None)

def call(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data, {"Content-Type": "application/json"})
    t = time.perf_counter(); out = urllib.request.urlopen(req).read()
    return (time.perf_counter() - t) * 1000, len(data or b""), len(out)

call("/ready")
rtt = statistics.median(call("/health")[0] for _ in range(20))
print(f"baseline /health median: {rtt:.0f} ms")
print("rows,bytes_in,bytes_out,median_ms,ms_per_row")
for n in (1, 10, 25, 50, 100):
    rows = [ROW] * n
    body = rows if KEY is None else {KEY: rows}
    res = [call("/predict/batch", body) for _ in range(20)]
    med = statistics.median(r[0] for r in res)
    print(n, res[0][1], res[0][2], round(med), round(med / n, 1), sep=",")
