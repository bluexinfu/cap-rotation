#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
資金輪動 data.json builder
從臺灣證券交易所(TWSE)公開資料計算各產業三大法人資金流、類股指數、龍頭股 OHLC。
只用 Python 標準庫，無第三方相依。GitHub Actions 每日收盤後執行。

輸出 data.json schema:
{
  "updated": "YYYYMMDD",
  "dates":   ["YYYYMMDD", ...],                # 由舊到新
  "sectors": [
    {"sector":"半導體",
     "series":[float,...],                      # 各日三大法人淨買超(億元)
     "idx":[float|null,...],                    # 類股指數收盤
     "rep":{"id":"2330","name":"台積電"},        # 區間成交金額最大之龍頭股
     "ohlc":[[o,h,l,c]|null,...]}               # 龍頭股每日 OHLC
  ]
}
"""
import json, os, sys, time, datetime, urllib.request

NDAYS   = int(os.environ.get("NDAYS", "75"))     # 目標交易日數
UA      = {"User-Agent": "Mozilla/5.0 (compatible; tide-data-bot/1.0)"}
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType={t}&response=json"
MI_URL  = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"

# 上市產業別代碼（T86 selectType）
SECTORS = {
 "01":"水泥","02":"食品","03":"塑膠","04":"紡織纖維","05":"電機機械","06":"電器電纜",
 "08":"玻璃陶瓷","09":"造紙","10":"鋼鐵","11":"橡膠","12":"汽車","14":"建材營造",
 "15":"航運","16":"觀光餐旅","17":"金融保險","18":"貿易百貨","19":"綜合","20":"其他",
 "21":"化學","22":"生技醫療","23":"油電燃氣","24":"半導體","25":"電腦及週邊","26":"光電",
 "27":"通信網路","28":"電子零組件","29":"電子通路","30":"資訊服務","31":"其他電子",
 "32":"文化創意","33":"農業科技","34":"電子商務","35":"綠能環保","36":"數位雲端",
 "37":"運動休閒","38":"居家生活",
}

def fetch(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            time.sleep(2 + i)          # 遇 307/限流時退避
    return None

def num(s):
    if s is None: return 0.0
    s = str(s).replace(",", "").strip()
    if s in ("", "--", "---", "X", "x"): return 0.0
    try: return float(s)
    except: return 0.0

def build_stock_sector(date):
    """以最新交易日逐產業查 T86，建立 股票代號 -> 產業 對照。"""
    m = {}
    for code, name in SECTORS.items():
        d = fetch(T86_URL.format(d=date, t=code))
        time.sleep(0.6)
        if not d or d.get("stat") != "OK":
            continue
        for row in d.get("data", []):
            m[row[0].strip()] = name
    return m

def parse_mi(mi):
    """回傳 (ohlc{ id:[o,h,l,c,turnover] }, close{id:c}, names{id:name}, idx{產業:收盤})"""
    ohlc, close, names, idx = {}, {}, {}, {}
    if not mi or mi.get("stat") != "OK":
        return None
    for t in mi.get("tables", []):
        f = t.get("fields") or []
        if "收盤價" in f and "證券代號" in f:
            ci=f.index("收盤價"); oi=f.index("開盤價"); hi=f.index("最高價"); li=f.index("最低價")
            idi=f.index("證券代號"); ni=f.index("證券名稱"); ti=f.index("成交金額")
            for r in t["data"]:
                sid=r[idi].strip(); c=num(r[ci])
                ohlc[sid]=[num(r[oi]),num(r[hi]),num(r[li]),c,num(r[ti])]
                close[sid]=c; names[sid]=r[ni].strip()
        if "收盤指數" in f and "指數" in f:
            for r in t["data"]:
                nm=r[0].strip()
                if nm.endswith("類指數"): idx[nm[:-3]]=num(r[1])
    return ohlc, close, names, idx

def latest_trading_day():
    """從今天往回找第一個有 T86 資料的交易日。"""
    d = datetime.date.today()
    for _ in range(15):
        ds = d.strftime("%Y%m%d")
        r = fetch(T86_URL.format(d=ds, t="ALL"))
        time.sleep(0.4)
        if r and r.get("stat") == "OK":
            return d
        d -= datetime.timedelta(days=1)
    raise SystemExit("找不到最近交易日資料")

def main():
    last = latest_trading_day()
    print("最新交易日:", last, file=sys.stderr)
    stock_sector = build_stock_sector(last.strftime("%Y%m%d"))
    print("對應股票數:", len(stock_sector), file=sys.stderr)

    days = []                 # [{date, sv, ix, oh}]
    d = last
    guard = 0
    while len(days) < NDAYS and guard < NDAYS*3 + 40:
        guard += 1
        ds = d.strftime("%Y%m%d")
        d -= datetime.timedelta(days=1)
        if datetime.datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        t86 = fetch(T86_URL.format(d=ds, t="ALL"))
        time.sleep(0.4)
        if not t86 or t86.get("stat") != "OK":
            continue
        mi = parse_mi(fetch(MI_URL.format(d=ds)))
        time.sleep(0.4)
        if not mi:
            continue
        ohlc, close, names, idx = mi
        sv = {}
        for r in t86["data"]:
            sid=r[0].strip(); sec=stock_sector.get(sid)
            if sec: sv[sec]=sv.get(sec,0)+num(r[-1])*close.get(sid,0)
        days.append({"date":ds,"sv":sv,"ix":idx,"oh":ohlc})
        names_all.update(names)
        print("  ok", ds, "累計", len(days), file=sys.stderr)

    days.sort(key=lambda x:x["date"])
    dates=[x["date"] for x in days]

    # 各股總成交金額 -> 選龍頭
    turn={}
    for x in days:
        for sid,v in x["oh"].items():
            turn[sid]=turn.get(sid,0)+(v[4] if len(v)>4 else 0)
    sec_stocks={}
    for sid,sec in stock_sector.items(): sec_stocks.setdefault(sec,[]).append(sid)

    idx_names=set()
    for x in days: idx_names|=set(x["ix"].keys())
    def idx_for(sec):
        if sec in idx_names: return sec
        c=[n for n in idx_names if n.startswith(sec)]
        if c: return sorted(c,key=len)[0]
        c=[n for n in idx_names if sec.startswith(n)]
        if c: return sorted(c,key=len,reverse=True)[0]
        return None

    out=[]
    for sec in sorted(sec_stocks.keys()):
        series=[round(x["sv"].get(sec,0.0)/1e8,2) for x in days]
        if not any(abs(v)>0 for v in series):     # 無資料產業略過
            continue
        ino=idx_for(sec)
        idx=[(x["ix"].get(ino) if ino else None) for x in days]
        cands=[s for s in sec_stocks[sec] if s in turn]
        rep=max(cands,key=lambda s:turn[s]) if cands else None
        ohlc=[]
        if rep:
            for x in days:
                v=x["oh"].get(rep)
                ohlc.append([v[0],v[1],v[2],v[3]] if (v and v[3]>0) else None)
        out.append({"sector":sec,"series":series,"idx":idx,
                    "rep":{"id":rep,"name":names_all.get(rep,"")} if rep else None,
                    "ohlc":ohlc})
    out.sort(key=lambda o:-sum(o["series"][-20:]))
    res={"updated":dates[-1],"dates":dates,"sectors":out}

    here=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path=os.path.join(here,"data.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump(res,f,ensure_ascii=False,separators=(",",":"))
    print("寫出", path, "| 交易日", len(dates), "| 產業", len(out), file=sys.stderr)

names_all={}
if __name__=="__main__":
    main()
