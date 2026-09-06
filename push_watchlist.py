#!/usr/bin/env python3
"""
最近成交币种指标推送 (Watchlist)
2026-09-06 起：币池自动更新为 OKX 近 7 天成交过的 USDT 永续币（orders-history 枚举，每天 08/16 点推送时实时拉取）；
API 失败/为空时回退读取 FIXED_SYMBOLS.txt。
推送每个币种的指标情况：方向(1H/4H/1D) + SRSI(1H/4H/1D) + ADX(4H) + ATR(1H)%
"""
import requests, time, os
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"
# OKX 私有 API 凭据（读成交记录枚举近7天成交币）：env 优先，缺省回退与 okx_monitor.py 一致的只读 Key
OKX_API_KEY = os.environ.get("OKX_API_KEY", "6d758f5a-4ea7-44d1-bc56-5b8659263b1a")
OKX_SECRET = os.environ.get("OKX_SECRET", "760BEBD659B861D17B5DE6DF7112E5CF")
OKX_PASSPHRASE = os.environ.get("OKX_PASSPHRASE", "1qaz2wsxcJJ!")
import hmac as _hmac, base64 as _b64, hashlib as _hashlib

def _okx_sign(ts, method, path, body=""):
    return _b64.b64encode(_hmac.new(OKX_SECRET.encode(), (ts+method+path+body).encode(), _hashlib.sha256).digest()).decode()

def _okx_req(method, path, params=None):
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    qs = "?" + "&".join(f"{k}={v}" for k, v in (params or {}).items()) if params else ""
    h = {"OK-ACCESS-KEY": OKX_API_KEY, "OK-ACCESS-SIGN": _okx_sign(ts, method, path+qs),
         "OK-ACCESS-TIMESTAMP": ts, "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
         "Content-Type": "application/json"}
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}{path}{qs}", headers=h, timeout=15)
            return r.json()
        except Exception:
            time.sleep(1)
    return {}

def fetch_recent_traded_symbols(days=7, max_pages=5):
    """枚举 OKX 近 N 天成交过的 USDT 永续币种（orders-history 不带 instId，分页拉全）。
    返回去重后的 instId 列表（如 ['ORDI-USDT-SWAP', ...]）；失败返回 []。"""
    end_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    begin_ts = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)
    syms = []
    seen = set()
    after = None
    for _ in range(max_pages):
        params = {"instType": "SWAP", "state": "filled",
                  "begin": str(begin_ts), "end": str(end_ts), "limit": "100"}
        if after:
            params["after"] = str(after)
        data = _okx_req("GET", "/api/v5/trade/orders-history", params)
        if data.get("code") != "0" or not data.get("data"):
            break
        batch = data["data"]
        for o in batch:
            inst = o.get("instId", "")
            if "USDT-SWAP" in inst and inst not in seen:
                seen.add(inst)
                syms.append(inst)
        if len(batch) < 100:
            break
        after = batch[-1].get("ordId")
        time.sleep(0.12)
    return syms

def get_candles(inst, bar, limit=100):
    for _ in range(3):
        try:
            r = requests.get(f"{OKX}/api/v5/market/candles",params={"instId":inst,"bar":bar,"limit":limit},timeout=12)
            d = r.json()
            if d.get("code")=="0":
                candles = []
                for c in d["data"]:
                    candles.append({"h":float(c[2]),"l":float(c[3]),"c":float(c[4]),"o":float(c[1]),"v":float(c[5])})
                candles.reverse()
                return candles
        except: time.sleep(0.5)
    return None

def calc_rsi(closes, period=14):
    n=len(closes)
    if n<period+1: return None
    gains,losses=[],[]
    for i in range(1,n):
        d=closes[i]-closes[i-1]
        gains.append(max(d,0));losses.append(max(-d,0))
    ag=sum(gains[:period])/period;al=sum(losses[:period])/period
    rv=[100 if al==0 else 100-100/(1+ag/al)]
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period;al=(al*(period-1)+losses[i])/period
        rv.append(100 if al==0 else 100-100/(1+ag/al))
    return rv

def calc_stoch_rsi(closes,rsi_period=14,stoch_period=14,sk=3):
    rsi=calc_rsi(closes,rsi_period)
    if not rsi or len(rsi)<stoch_period+sk:return None
    kr=[]
    for i in range(stoch_period-1,len(rsi)):
        w=rsi[i-stoch_period+1:i+1];lo,hi=min(w),max(w)
        kr.append(50 if hi==lo else (rsi[i]-lo)/(hi-lo)*100)
    kv=[]
    for i in range(sk-1,len(kr)):kv.append(sum(kr[i-sk+1:i+1])/sk)
    if len(kv)<4:return kv[-1] if kv else None
    d=sum(kv[-3:])/3
    return (kv[-1]+d)/2

def calc_adx(candles,period=14):
    n=len(candles)
    if n<period+1:return None,None,None
    h=[c["h"]for c in candles];l=[c["l"]for c in candles];cl=[c["c"]for c in candles]
    tr=[0]*n
    for i in range(1,n):tr[i]=max(h[i]-l[i],abs(h[i]-cl[i-1]),abs(l[i]-cl[i-1]))
    pd=[0]*n;md=[0]*n
    for i in range(1,n):
        u=h[i]-h[i-1];d=l[i-1]-l[i]
        if u>d and u>0:pd[i]=u
        if d>u and d>0:md[i]=d
    atrs=sum(tr[1:period+1])/period;sp=sum(pd[1:period+1])/period;sm=sum(md[1:period+1])/period
    dxv=[]
    for i in range(period+1,n):
        atrs=(atrs*(period-1)+tr[i])/period;sp=(sp*(period-1)+pd[i])/period;sm=(sm*(period-1)+md[i])/period
        p=sp/atrs*100 if atrs>0 else 0;m=sm/atrs*100 if atrs>0 else 0;s=p+m
        dxv.append(abs(p-m)/s*100 if s>0 else 0)
    if len(dxv)<period:return None,None,None
    av=sum(dxv[:period])/period
    for i in range(period,len(dxv)):av=(av*(period-1)+dxv[i])/period
    return av,sp/atrs*100 if atrs>0 else 0,sm/atrs*100 if atrs>0 else 0

def calc_atr(candles,period=14):
    n=len(candles)
    if n<period+1:return None
    h=[c["h"]for c in candles];l=[c["l"]for c in candles];cl=[c["c"]for c in candles]
    tr=[0]*n
    for i in range(1,n):tr[i]=max(h[i]-l[i],abs(h[i]-cl[i-1]),abs(l[i]-cl[i-1]))
    atr=sum(tr[1:period+1])/period
    for i in range(period+1,n):atr=(atr*(period-1)+tr[i])/period
    return atr

def fmt_p(p):
    if p>=1000:return f"{p:.0f}"
    if p>=1:return f"{p:.2f}"
    if p>=0.01:return f"{p:.4f}"
    return f"{p:.6g}"

def dcol(d):
    return "#27ae60" if d=="多" else ("#e74c3c" if d=="空" else "#999")

def scol(v):
    if v is None:return "N/A","#999"
    v=round(v,1)
    if v>=80:return f"{v:.0f}","#e74c3c"
    if v<=20:return f"{v:.0f}","#27ae60"
    return f"{v:.0f}","#333"

def main():
    proj=os.path.dirname(os.path.abspath(__file__))
    # 币池（2026-09-06 起）= OKX 近 7 天成交过的 USDT 永续币（自动更新）；API 失败/为空时回退 FIXED_SYMBOLS.txt
    symbols = fetch_recent_traded_symbols(days=7)
    src = "近7天成交"
    if not symbols:
        fixed_file=os.path.join(proj,"FIXED_SYMBOLS.txt")
        if os.path.exists(fixed_file):
            with open(fixed_file)as f:
                symbols=[l.strip()for l in f if l.strip()and not l.startswith('#')]
        src = "FIXED自选(API失败回退)"
    if len(symbols) > 50:
        symbols = symbols[:50]  # 防币过多扫描超时，保留最近成交的前 50 个
    print(f"Watchlist pool: {len(symbols)} symbols ({src})")

    now=datetime.now(timezone(timedelta(hours=8)))
    now_str=now.strftime("%m-%d %H:%M CST")

    rows=[]
    for sym in symbols:
        name=sym.replace("-USDT-SWAP","")
        c1h=get_candles(sym,"1H",30);c4h=get_candles(sym,"4H",100);c1d=get_candles(sym,"1D",100)
        if not c4h or not c1d:
            rows.append({"name":name,"err":True})
            continue
        a1,p1,m1=calc_adx(c1h) if c1h else (None,0,0)
        a4,p4,m4=calc_adx(c4h)
        ad,pd1,md1=calc_adx(c1d)
        d1="多"if(p1 and m1 and p1>m1)else("空"if(p1 and m1)else"N/A")
        d4="多"if p4>m4 else"空"
        dd="多"if pd1>md1 else"空"
        s1=calc_stoch_rsi([c["c"]for c in c1h])if c1h else None
        s4=calc_stoch_rsi([c["c"]for c in c4h])
        sd=calc_stoch_rsi([c["c"]for c in c1d])
        atr1h=calc_atr(c1h)if c1h else None
        atr_pct=atr1h/c4h[-1]["c"]*100 if atr1h else None
        px=c4h[-1]["c"]
        rows.append({"name":name,"px":px,"d1":d1,"d4":d4,"dd":dd,
                     "s1":s1,"s4":s4,"sd":sd,"adx4":round(a4,1)if a4 else None,
                     "atr":round(atr_pct,1)if atr_pct is not None else None})

    h='<div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:520px">'
    h+=f'<h3 style="margin:0 0 4px;color:#333">📊 {"最近成交" if src=="近7天成交" else "自选"}币种指标</h3>'
    h+=f'<p style="color:#999;font-size:11px;margin:0 0 8px">{now_str}</p>'
    h+='<table style="width:100%;border-collapse:collapse;font-size:12px">'
    h+='<tr style="background:#f5f6fa;font-weight:bold;color:#666">'
    h+='<td style="padding:5px 3px">币种</td><td style="text-align:center">现价</td>'
    h+='<td style="text-align:center">1H</td><td style="text-align:center">4H</td><td style="text-align:center">1D</td>'
    h+='<td style="text-align:center;color:#3498db">SRSI 1H/4H/1D</td>'
    h+='<td style="text-align:center">ADX</td><td style="text-align:center">ATR</td></tr>'
    for i,r in enumerate(rows):
        bg="#fff"if i%2==0 else"#fafbfc"
        if r.get("err"):
            h+=f'<tr style="background:{bg}"><td style="padding:5px 3px;font-weight:bold">{r["name"]}</td><td colspan="7" style="text-align:center;color:#999">数据获取失败</td></tr>'
            continue
        s1v,s1c=scol(r["s1"]);s4v,s4c=scol(r["s4"]);sdv,sdc=scol(r["sd"])
        srsis=f'{s1v}/{s4v}/{sdv}'
        adxv=f'{r["adx4"]:.0f}'if r["adx4"]is not None else"N/A"
        atrv=f'{r["atr"]:.1f}%'if r["atr"]is not None else"N/A"
        h+=f'<tr style="background:{bg}"><td style="padding:5px 3px;font-weight:bold">{r["name"]}</td>'
        h+=f'<td style="text-align:center">{fmt_p(r["px"])}</td>'
        h+=f'<td style="text-align:center;color:{dcol(r["d1"])};font-weight:bold">{r["d1"]}</td>'
        h+=f'<td style="text-align:center;color:{dcol(r["d4"])};font-weight:bold">{r["d4"]}</td>'
        h+=f'<td style="text-align:center;color:{dcol(r["dd"])};font-weight:bold">{r["dd"]}</td>'
        h+=f'<td style="text-align:center">{srsis}</td>'
        h+=f'<td style="text-align:center">{adxv}</td><td style="text-align:center">{atrv}</td></tr>'
    h+='</table>'
    h+='<p style="color:#999;font-size:10px;margin:6px 0 0">方向:DMI(+DI/-DI) | SRSI:Stochastic RSI | ADX:4H趋势强度 | ATR:1H波幅%</p>'
    h+='</div>'

    token=os.environ.get("PUSHPLUS_TOKEN","")
    if not token:
        tp=os.path.join(proj,".pushplus_token")
        if os.path.exists(tp):
            token=open(tp).read().strip()

    if token:
        pl={"token":token,"title":"Watchlist","content":h,"template":"html"}
        try:
            rp=requests.post("http://www.pushplus.plus/send",json=pl,timeout=10)
            print(f"Push: {'OK' if rp.json().get('code')==200 else rp.json()}")
        except Exception as e:
            print(f"Push error: {e}")
    else:
        print("no token, skip push")

if __name__=="__main__":
    main()
