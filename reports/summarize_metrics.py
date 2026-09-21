import json, sys
d = json.load(open(sys.argv[1]))
rows = []
for ts in d["value"][0]["timeseries"]:
    rev = ts["metadatavalues"][0]["value"]
    for p in ts["data"]:
        if p.get("total"):
            rows.append((p["timeStamp"], rev, int(p["total"])))
print("time (UTC)            revision                         requests")
for t, rev, n in sorted(rows):
    print(f"{t}  {rev:32s} {n}")
