#!/usr/bin/env python3
"""
获取 OKX 最近成交币种 + 当前持仓，输出到 recent_trades.txt
"""
import requests, time, hmac, base64, hashlib, json, os
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"
KEY = "d7f911a9-11aa-4c0c-8f3f-e389f86a77fc"
SECRET = "6A8C3666FE205E97B27132BF9921EEAA"
PASS = "1qaz2wsxcJJ@"
PASS_CANDIDATES = ["1qaz2wsxcJJ@", "1qaz2wsxcJJ!", "1qaz2wsxcJJ", "1qaz2wsxcJJ＠"]

def sign(ts, method, path, body=""):
    return base64.b64encode(hmac.new(SECRET.encode(), (ts+method+path+body).encode(), hashlib.sha256).digest()).decode()

def req(method, path, params=None, simulated=False, dbg=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00","Z")
    qs = "?" + "&".join(f"{k}={v}" for k,v in (params or {}).items()) if params else ""
    prehash = ts + method + path + qs
    sig = sign(ts, method, path + qs)
    if dbg is not None:
        dbg.append(f"ts={ts}")
        dbg.append(f"KEY={KEY[:10]} SECRET={SECRET[:10]}")
        dbg.append(f"prehash={prehash[:100]}")
        dbg.append(f"sig={sig[:44]}")
    last_resp = {}
    for p in PASS_CANDIDATES:
        h = {"OK-ACCESS-KEY":KEY,"OK-ACCESS-SIGN":sig,
             "OK-ACCESS-TIMESTAMP":ts,"OK-ACCESS-PASSPHRASE":p,"Content-Type":"application/json"}
        if simulated:
            h["x-simulated-trading"] = "1"
        for _ in range(2):
            try:
                r = requests.get(f"{OKX}{path}{qs}", headers=h, timeout=15)
                last_resp = r.json()
                code = last_resp.get("code")
                if code == "0":
                    if dbg is not None:
                        dbg.append(f"passphrase OK: {p!r}")
                    return last_resp
                if code != "50105":
                    return last_resp
                break
            except: time.sleep(1)
    if dbg is not None:
        dbg.append(f"all passphrase failed, last={last_resp}")
    return last_resp

def main():
    end = int(datetime.now(timezone.utc).timestamp()*1000)
    begin = int((datetime.now(timezone.utc)-timedelta(days=30)).timestamp()*1000)
    params = {"instType":"SWAP","state":"filled","begin":str(begin),"end":str(end),"limit":"100"}

    trades = {}
    debug_lines = []

    r = req("GET", "/api/v5/trade/orders-history", params, dbg=debug_lines)
    debug_lines.append(f"[orders-history 实盘] code={r.get('code')} msg={r.get('msg')}")
    if r.get("code")=="0":
        for o in r.get("data",[]):
            inst = o.get("instId","")
            if "USDT" in inst:
                nm = inst.replace("-USDT-SWAP","").replace("-USDT","")
                trades[nm] = trades.get(nm,0)+1
    else:
        r = req("GET", "/api/v5/trade/orders-history", params, simulated=True, dbg=debug_lines)
        debug_lines.append(f"[orders-history 模拟盘] code={r.get('code')} msg={r.get('msg')}")
        if r.get("code")=="0":
            for o in r.get("data",[]):
                inst = o.get("instId","")
                if "USDT" in inst:
                    nm = inst.replace("-USDT-SWAP","").replace("-USDT","")
                    trades[nm] = trades.get(nm,0)+1

    positions = []
    r2 = req("GET", "/api/v5/account/positions", {"instType":"SWAP"}, dbg=debug_lines)
    debug_lines.append(f"[positions 实盘] code={r2.get('code')} msg={r2.get('msg')}")
    if r2.get("code")!="0":
        r2 = req("GET", "/api/v5/account/positions", {"instType":"SWAP"}, simulated=True, dbg=debug_lines)
        debug_lines.append(f"[positions 模拟盘] code={r2.get('code')} msg={r2.get('msg')}")
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

    for l in debug_lines:
        print(l)
    print("=== 结果 ===")
    for nm, cnt, tag in result:
        print(f"  {nm:<10} {tag}")

    proj = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(proj, "recent_trades.txt")
    with open(out, "w") as f:
        f.write("\n".join(debug_lines) + "\n---\n")
        for nm, cnt, tag in result:
            f.write(f"{nm}-USDT-SWAP\n")

if __name__ == "__main__":
    main()
