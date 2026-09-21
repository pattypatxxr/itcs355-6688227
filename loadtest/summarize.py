import csv, sys, glob, re
print("file,rps,p50,p95,p99,fail")
for f in sorted(glob.glob(sys.argv[1]), key=lambda s: [int(x) for x in re.findall(r"\d+", s)]):
    r = next(x for x in csv.DictReader(open(f)) if x["Name"] == "Aggregated")
    print(f.split("/")[-1], round(float(r["Requests/s"]), 1), r["50%"], r["95%"], r["99%"], r["Failure Count"], sep=",")
