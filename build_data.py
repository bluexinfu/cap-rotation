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
     "dim":"twse",                              # twse=證交所產業 / ai=AI 主題
     "series":[float,...],                      # 各日三大法人淨買超(億元)
     "idx":[float|null,...],                    # 類股指數收盤(AI 主題為 null)
     "rep":{"id":"2330","name":"台積電"},        # 區間成交金額最大之龍頭股
     "ohlc":[[o,h,l,c]|null,...]},              # 龍頭股每日 OHLC
    {"sector":"散熱/液冷","dim":"ai",            # AI 主題板塊(用上市+上櫃個股按主題加總)
     "series":[...], "idx":[null,...], "rep":{...}, "ohlc":[...],
     "members":[{"id":"3017","name":"奇鋐","ohlc":[[o,h,l,c]|null,...],
                 "flow":[float,...]}, ...],   # 成員股 OHLC + 每日法人淨買(億)，供 K 線+資金流疊加
     "note":"<偏大個股提示>"|null}
  ],
  "market": {"name":"加權指數",                 # 大盤基準（可切換顯示）
     "ohlc":[[o,h,l,c]|null,...],               # 加權指數每日 OHLC
     "flow":[float,...]}                         # 全市場三大法人合計買賣超(億/日)
}
"""
import json, os, sys, time, datetime, urllib.request

NDAYS   = int(os.environ.get("NDAYS", "75"))     # 目標交易日數
UA      = {"User-Agent": "Mozilla/5.0 (compatible; tide-data-bot/1.0)"}
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType={t}&response=json"
MI_URL  = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
# 上櫃(TPEx/櫃買中心) — AI 主題成員有部分為上櫃股(群聯/旺矽/精測/雙鴻/威剛/聯亞)，需另抓
TPEX_INST  = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d}"
TPEX_QUOTE = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={d}"
def roc(ds):  # "20260616" -> "115/06/16"（民國年）
    return f"{int(ds[:4])-1911}/{ds[4:6]}/{ds[6:8]}"
# 大盤（加權指數）：發行量加權股價指數歷史 OHLC（月檔）＋ 三大法人買賣金額統計（每日合計）
TAIEX_HIST = "https://www.twse.com.tw/rwd/zh/TAIEX/MI_5MINS_HIST?date={d}&response=json"
BFI_URL    = "https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={d}&type=day&response=json"
def fetch_taiex_month(yyyymm01):
    """回傳 {民國日期: [o,h,l,c]}（該月每日加權指數）。"""
    d = fetch(TAIEX_HIST.format(d=yyyymm01)); out={}
    if d and d.get("stat")=="OK":
        for r in d.get("data",[]):
            out[str(r[0]).strip()] = [num(r[1]),num(r[2]),num(r[3]),num(r[4])]
    return out
def fetch_mkt_netbuy(ds):
    """全市場三大法人『合計』買賣差額（元）。"""
    d = fetch(BFI_URL.format(d=ds))
    if d and d.get("stat")=="OK":
        for r in d.get("data",[]):
            if str(r[0]).strip().startswith("合計"):
                return num(r[-1])
    return 0.0

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

# AI 主題分類（觀察用，非選股建議）。成員定義見 docs/ai-themes.md（v1 2026-06-18）。
# 各主題前三大個股；台積電(2330)獨立成一顆，不計入任何主題加總（量級獨大、跨多組）。
AI_THEMES = {
 "ASIC/IP設計": ["3661","3443","3035"],   # 世芯-KY、創意、智原
 "先進封裝/CoWoS": ["3711","6223","6510"], # 日月光投控、旺矽、精測
 "記憶體/儲存": ["2408","8299","3260"],    # 南亞科、群聯、威剛
 "ABF載板/PCB": ["3037","2368","2383"],   # 欣興、金像電、台光電
 "AI伺服器/ODM": ["2382","6669","2317"],  # 廣達、緯穎、鴻海
 "散熱/液冷": ["3017","3324","3653"],      # 奇鋐、雙鴻、健策
 "電源": ["2308","2301","6282"],           # 台達電、光寶科、康舒
 "CPO/光通訊": ["2345","3081","6442"],     # 智邦、聯亞、光聖
 "被動/連接器": ["2327","3665","3023"],    # 國巨、貿聯-KY、信邦
 "機構件/機殼": ["8210","2059","3013"],    # 勤誠、川湖、晟銘電
 "台積電": ["2330"],                        # 獨立觀察（定海神針）
}
AI_MEMBERS = set(c for codes in AI_THEMES.values() for c in codes)
BIG_SHARE = 0.5   # 某成員近20日|淨買|占該組比重超過此值 → 標「偏大個股」備註

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

def build_stock_sector(dates):
    """逐產業查 T86 建立 股票代號 -> 產業 對照。
    為避免「最新一日盤後資料尚未完整」而漏掉某些產業，會依序嘗試多個近日，
    把仍空缺的產業用前一日補齊（最新日優先，setdefault 保留最新分類）。
    dates: 近期交易日字串清單（最新在前）。"""
    m = {}
    filled = set()                       # 已成功取得資料的產業
    for ds in dates:
        if len(filled) >= len(SECTORS):
            break
        for code, name in SECTORS.items():
            if name in filled:
                continue                 # 此產業較新一日已補齊，跳過
            d = fetch(T86_URL.format(d=ds, t=code))
            time.sleep(0.5)
            if not d or d.get("stat") != "OK" or not d.get("data"):
                continue
            filled.add(name)
            for row in d["data"]:
                m.setdefault(row[0].strip(), name)
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

def fetch_otc(ds, want):
    """抓上櫃當日資料，只取 want 內代號。
    回傳 (nv{sid:三大法人買賣超股數}, oh{sid:[o,h,l,c]}, nm{sid:名稱})。"""
    rd = roc(ds); nv={}; oh={}; nm={}
    di = fetch(TPEX_INST.format(d=rd))
    if di and str(di.get("stat","")).lower()=="ok":
        for t in di.get("tables",[]):
            f=t.get("fields") or []
            if "三大法人買賣超股數合計" in f:
                ti=f.index("三大法人買賣超股數合計")
                for r in t.get("data",[]):
                    sid=str(r[0]).strip()
                    if sid in want:
                        nv[sid]=num(r[ti]); nm[sid]=str(r[1]).strip()
    dq = fetch(TPEX_QUOTE.format(d=rd))
    if dq and str(dq.get("stat","")).lower()=="ok":
        for t in dq.get("tables",[]):
            f=t.get("fields") or []
            if "收盤" in f and "代號" in f:
                ci=f.index("收盤");oi=f.index("開盤");hi=f.index("最高");li=f.index("最低")
                for r in t.get("data",[]):
                    sid=str(r[0]).strip()
                    if sid in want:
                        oh[sid]=[num(r[oi]),num(r[hi]),num(r[li]),num(r[ci])]
    return nv, oh, nm

# AI 主題成員中屬上櫃者（需向櫃買中心抓）= 全成員 − 上市能抓到的
OTC_WANT = AI_MEMBERS

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

def build_ai_sectors(days, names_all):
    """用每日個股資料(x['mv']=成員淨買金額, x['oh']=OHLC)按 AI 主題加總，
    產出 dim='ai' 的板塊清單：series=成員加總(億)、members=[{id,name,ohlc}]、note=偏大個股提示。"""
    def member_ohlc(c):
        oh=[]
        for x in days:
            v=x["oh"].get(c)
            oh.append([v[0],v[1],v[2],v[3]] if (v and len(v)>3 and v[3]>0) else None)
        return oh
    ai_out=[]
    last20=days[-20:] if len(days)>=20 else days
    for theme,codes in AI_THEMES.items():
        series=[round(sum(x["mv"].get(c,0) for c in codes)/1e8,2) for x in days]
        if not any(abs(v)>0 for v in series):     # 完全無資料的主題略過
            continue
        members=[{"id":c,"name":names_all.get(c,c),"ohlc":member_ohlc(c),
                  "flow":[round(x["mv"].get(c,0)/1e8,2) for x in days]} for c in codes]
        note=None
        if len(codes)>1:
            contrib={c:sum(abs(x["mv"].get(c,0)) for x in last20) for c in codes}
            tot=sum(contrib.values()) or 1
            big=max(contrib,key=contrib.get)
            if contrib[big]/tot>BIG_SHARE:
                note=f"{names_all.get(big,big)} 量級偏大（近20日約占{round(contrib[big]/tot*100)}%），看相對強度較公允"
        ai_out.append({"sector":theme,"dim":"ai","series":series,"idx":[None]*len(days),
                       "rep":{"id":members[0]["id"],"name":members[0]["name"]},
                       "ohlc":members[0]["ohlc"],"members":members,"note":note})
    ai_out.sort(key=lambda o:-sum(o["series"][-20:]))
    return ai_out

def main():
    last = latest_trading_day()
    print("最新交易日:", last, file=sys.stderr)
    # 近期數個交易日(最新在前)供建立對照表，缺漏產業自動往前補齊
    cand, dd = [], last
    while len(cand) < 8:
        if dd.weekday() < 5:
            cand.append(dd.strftime("%Y%m%d"))
        dd -= datetime.timedelta(days=1)
    stock_sector = build_stock_sector(cand)
    print("對應股票數:", len(stock_sector),
          "| 產業數:", len(set(stock_sector.values())), file=sys.stderr)

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
        sv = {}; mv = {}
        for r in t86["data"]:
            sid=r[0].strip(); val=num(r[-1])*close.get(sid,0)
            sec=stock_sector.get(sid)
            if sec: sv[sec]=sv.get(sec,0)+val
            if sid in AI_MEMBERS: mv[sid]=val      # AI 主題成員(上市)的當日淨買金額
        # 上櫃成員：股數×收盤=金額，OHLC 併入同一個 ohlc 表供成員 K 線使用
        onv, ooh, onm = fetch_otc(ds, OTC_WANT)
        time.sleep(0.4)
        names_all.update(onm)
        for sid, sh in onv.items():
            c = ooh.get(sid,[0,0,0,0])[3]
            mv[sid] = sh*c
        for sid, v in ooh.items():
            ohlc[sid] = v
        mkt = fetch_mkt_netbuy(ds); time.sleep(0.3)   # 大盤三大法人合計買賣差額(元)
        days.append({"date":ds,"sv":sv,"mv":mv,"ix":idx,"oh":ohlc,"mkt":mkt})
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
        out.append({"sector":sec,"dim":"twse","series":series,"idx":idx,
                    "rep":{"id":rep,"name":names_all.get(rep,"")} if rep else None,
                    "ohlc":ohlc})
    out.sort(key=lambda o:-sum(o["series"][-20:]))

    # ===== AI 主題維度（dim=ai）：用同一批個股資料按主題加總，附成員股 OHLC 與偏大備註 =====
    ai_out = build_ai_sectors(days, names_all)

    # ===== 大盤（加權指數）：OHLC（月檔合併）＋ 每日三大法人合計買賣超（億） =====
    taiex = {}
    for m in sorted({x["date"][:6]+"01" for x in days}):
        taiex.update(fetch_taiex_month(m)); time.sleep(0.3)
    mk_ohlc = [(taiex.get(roc(x["date"])) if (taiex.get(roc(x["date"])) and taiex.get(roc(x["date"]))[3]>0) else None) for x in days]
    mk_flow = [round(x.get("mkt",0)/1e8,2) for x in days]
    market = {"name":"加權指數","ohlc":mk_ohlc,"flow":mk_flow}

    res={"updated":dates[-1],"dates":dates,"sectors":out+ai_out,"market":market}

    here=os.path.dirname(os.path.abspath(__file__))
    path=os.path.join(here,"data.json")
    with open(path,"w",encoding="utf-8") as f:
        json.dump(res,f,ensure_ascii=False,separators=(",",":"))
    print("寫出", path, "| 交易日", len(dates), "| 產業", len(out), "| AI主題", len(ai_out), file=sys.stderr)

names_all={}
if __name__=="__main__":
    main()
