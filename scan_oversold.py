#!/usr/bin/env python3
"""
Extreme SRSI Scanner v2.1 — OKX热门Top50
(4H<10+1D<10) OR (4H>90+1D>90) | NoSpikes | TrendAligned | ADX>15
"""
import requests, time, json, os
from datetime import datetime, timezone, timedelta

OKX = "https://www.okx.com"

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

def trend_ema(candles,fast=12,slow=26):
    cl=[c["c"]for c in candles];k=2/(fast+1);ef=sum(cl[:fast])/fast
    for p in cl[fast:]:ef=p*k+ef*(1-k)
    k2=2/(slow+1);es=sum(cl[:slow])/slow
    for p in cl[slow:]:es=p*k2+es*(1-k2)
    return "Long" if ef>es else "Short"

def wick(candles):
    ra=[];sp=0
    for c in candles[-20:]:
        body=max(abs(c["c"]-c["o"]),1e-10)
        uw=c["h"]-max(c["c"],c["o"]);lw=min(c["c"],c["o"])-c["l"]
        r=min((uw+lw)/body,10);ra.append(r)
        if r>4:sp+=1
    return sum(ra)/len(ra),sp

def fmt_p(p,inst):
    if "BTC" in inst or "ETH" in inst:return f"{p:.1f}"
    if p>=1:return f"{p:.2f}"
    if p>=0.01:return f"{p:.4f}"
    return f"{p:.6g}"

def main():
    r=requests.get(f"{OKX}/api/v5/market/tickers",params={"instType":"SWAP"},timeout=15)
    d=r.json()
    if d.get("code")!="0":print("Failed:",d);return
    items=[]
    for t in d["data"]:
        inst=t["instId"]
        if"USDT"not in inst or any(x in inst for x in["BRL","EUR","TRY","DAI","USDC","RUB"]):continue
        last=float(t.get("last",0));op24=float(t.get("open24h",0))
        chg24=abs(last-op24)/op24*100 if op24>0 else 0
        items.append((inst,chg24))
    items.sort(key=lambda x:-x[1])
    syms=[i[0]for i in items[:50]]
    print(f"Scan top {len(syms)} hot coins...")
    results=[]
    for s in syms:
        name=s.replace("-USDT-SWAP","")
        c4=get_candles(s,"4H",100);c1=get_candles(s,"1D",100)
        if not c4 or not c1:continue
        cl4=[c["c"]for c in c4];cl1=[c["c"]for c in c1]
        s4=calc_stoch_rsi(cl4);s1=calc_stoch_rsi(cl1)
        if s4 is None or s1 is None:continue
        ovs=s4<10 and s1<10;ovb=s4>90 and s1>90
        if not ovs and not ovb:continue
        adx4,_,_=calc_adx(c4);wa,ws=wick(c4);tr=trend_ema(c4)if adx4 and adx4>0 else"N/A"
        pr=cl4[-1];trq="Short"if ovs else"Long"
        ax=min(1,(adx4 or 0)/30)*0.35;ws_=max(0,1-wa/3)*0.25;ss_=max(0,1-ws*5/20)*0.15
        es=max(0,(10-s4)/10)*0.15+max(0,(10-s1)/10)*0.10 if ovs else max(0,(s4-90)/10)*0.15+max(0,(s1-90)/10)*0.10
        sc=round(ax+ws_+ss_+es,3);tok="OK"if(tr==trq and adx4 and adx4>15)else("WARN"if adx4 and adx4>10 else"NO")
        results.append({"name":name,"s4":round(s4,1),"s1":round(s1,1),"adx4":round(adx4,1)if adx4 else 0,"price":pr,"trend":tr,"trend_ok":tok,"dir":"OVER"if ovs else"BOUNC","wick":round(wa,1),"spikes":ws,"score":sc})
        time.sleep(0.05)
    results.sort(key=lambda x:-x["score"])
    clean=[r for r in results if r["wick"]<3 and r["spikes"]<=2 and r["adx4"]>15 and r["trend_ok"]=="OK"and r["score"]>0.4]
    token=os.environ.get("PUSHPLUS_TOKEN","")
    if not token:
        tp=os.path.join(os.path.dirname(os.path.abspath(__file__)),".pushplus_token")
        if os.path.exists(tp):
            with open(tp)as f:token=f.read().strip()
    if clean:
        print(f"\nCLEAN({len(clean)}):")
        for r in clean:print(f"  {r['name']}{r['dir']}SRSI={r['s4']}/{r['s1']}ADX={r['adx4']:.0f}")
    if token and clean:
        h='<div style="font-family:-apple-system,sans-serif;max-width:480px">'
        h+='<h3 style="margin:0 0 6px">Extreme SRSI (OKX热门)</h3>'
        for r in clean:
            e="🟢"if r["dir"]=="OVER"else"🔴";c="#27ae60"if r["dir"]=="OVER"else"#e74c3c"
            p=fmt_p(r["price"],f"{r['name']}-USDT-SWAP")
            h+=f'<div style="margin:6px 0;padding:6px;background:#fff;border-left:3px solid {c}">'
            h+=f'{e}<b>{r["name"]}</b><span style="color:{c}">{r["dir"]}</span>{p}<br>'
            h+=f'<span style="font-size:11px;color:#333">SRSI={r["s4"]}/{r["s1"]}|ADX={r["adx4"]:.0f}|{r["trend"]}</span>'
            h+='</div>'
        h+='</div>'
        pl={"token":token,"title":"ExtremeSRSI","content":h,"template":"html"}
        try:
            rp=requests.post("http://www.pushplus.plus/send",json=pl,timeout=10)
            rj=rp.json()
            print(f"\nPush:{'OK'if rj.get('code')==200 else rj}")
        except Exception as e:print(f"\nPush error:{e}")
    return results,clean

if __name__=="__main__":main()
