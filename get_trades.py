#!/usr/bin/env python3
"""
获取 OKX 最近成交币种 + 当前持仓，输出到 recent_trades.txt
用于同步自选币种列表
"""
import requests, time, hmac, base64, hashlib, json, os
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"
KEY = os.environ.get("OKX_API_KEY", "6e4089f9-f101-4211-b4a2-624b3707eb0a")
SECRET = os.environ.get("OKX_SECRET_KEY", "1676210D1CE6AB14C2F1CB5A584D1418")
PASS = os.environ.get("OKX_PASSPHRASE", "1qaz2wsxcJJ@")

def sign(ts, method, path, body=""):
    return base64.b64encode(hmac.new(SECRET.encode(), (ts+method+path+body).encode(), hashlib.sha256).digest()).decode()

def req(method, path, params=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    qs = "?" + "&".join(f"{k}={v}" for k,v in (params or {}).items()) if params else ""
    h = {"OK-ACCESS-KEY":KEY,"OK-ACCESS-SIGN":sign(ts,method,path+qs),
         "OK-ACCESS-TIMESTAMP":ts,"OK-ACCESS-PASSPHRASE":PASS,"Content-Type":"application/json"}
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}{path}{qs}", headers=h, timeout=15)
            return r.json()
        except: time.sleep(1)
    return {}

def main():
    end = int(datetime.now(timezone.utc).timestamp()*1000)
    begin = int((datetime.now(timezone.utc)-timedelta(days=30)).timestamp()*1000)
    r = req("GET", "/api/v5/trade/orders-history",
            {"instType":"SWAP","state":"filled","begin":str(begin),"end":str(end),"limit":"100"})

    trades = {}
    if r.get("code")=="0":
        for o in r.get("data",[]):
            inst = o.get("instId","")
            if "USDT" in inst:
                nm = inst.replace("-USDT-SWAP","").replace("-USDT","")
                trades[nm] = trades.get(nm,0)+1
    else:
        print(f"orders-history error: {r}")

    positions = []
    r2 = req("GET", "/api/v5/account/positions", {"instType":"SWAP"})
    if r2.get("code")=="0":
        for p in r2.get("data",[]):
            pos = float(p.get("availPos",0) or 0)
            if abs(pos) > 0:
                nm = p["instId"].replace("-USDT-SWAP","").replace("-USDT","")
                positions.append(nm)

    result = []
    for nm in positions:
        result.append((nm, trades.get(nm,0), "持仓"))
    for nm, cnt in sorted(trades.items(), key=lambda x:-x[1]):
        if nm not in positions:
            result.append((nm, cnt, f"{cnt}笔"))

    print("=== 最近30天交易币种 + 持仓 ===")
    for nm, cnt, tag in result:
        print(f"  {nm:<10} {tag}")

    proj = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(proj, "recent_trades.txt")
    with open(out, "w") as f:
        for nm, cnt, tag in result:
            f.write(f"{nm}-USDT-SWAP\n")

    print("\n=== SWAP格式 ===")
    for nm, cnt, tag in result:
        print(f"{nm}-USDT-SWAP")

if __name__ == "__main__":
    main()
