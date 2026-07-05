#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
資金輪動 data.json builder
從臺灣證券交易所(TWSE)公開資料計算各產業三大法人資金流、類股指數、龍頭股 OHLC。
只用 Python 標準庫，無第三方相依。GitHub Actions 每日收盤後執行。

執行模式（2026-06-30 起）:
  * 預設「增量更新」(run): 讀現有 data.json，只抓比 updated 新的交易日接上去、
    丟掉最舊一天。每次只發數個請求 → 不會觸發 TWSE 限流，秒~分鐘級完成。
  * 「全量重建」(main): 重抓整個 NDAYS 視窗。僅在以下情況觸發：
      - 無 data.json / 資料不完整 / 落後過多（>10 交易日）
      - 既有資料缺「法人分項」欄位（A案 schema，2026-07 起）
      - 環境變數 FORCE_REBUILD=1（手動 workflow_dispatch 用）
    全量重建會重新挑選各板塊龍頭股(rep)與產業對照；增量模式沿用既有 rep（中長期觀察
    沿用龍頭較有連續性，需換龍頭時跑一次 FORCE_REBUILD 即可）。

法人分項（A案，2026-07 起）:
  除「三大法人合計」外，另存「外資」（外陸資＋外資自營商）與「投信」兩條分項序列，
  供前端切換觀察（合計會互相抵銷——外資賣、投信買的分歧日反而最值得注意）。
  自營商不獨立成列（含避險部位、雜訊高），仍隱含在合計內。
  欄位一律用資料源的 fields 名稱定位，不寫死索引。

輸出 data.json schema:
{
  "updated": "YYYYMMDD",
  "dates":   ["YYYYMMDD", ...],                # 由舊到新
  "sectors": [
    {"sector":"半導體",
     "dim":"twse",                              # twse=證交所產業 / ai=AI 主題
     "series":[float,...],                      # 各日三大法人淨買超(億元)
     "series_fi":[float,...],                   # 各日外資淨買超(億元)＝外陸資＋外資自營商
     "series_it":[float,...],                   # 各日投信淨買超(億元)
     "idx":[float|null,...],                    # 類股指數收盤(AI 主題為 null)
     "rep":{"id":"2330","name":"台積電"},        # 區間成交金額最大之龍頭股
     "ohlc":[[o,h,l,c]|null,...]},              # 龍頭股每日 OHLC
    {"sector":"散熱/液冷","dim":"ai",            # AI 主題板塊(用上市+上櫃個股按主題加總)
     "series":[...], "series_fi":[...], "series_it":[...],
     "idx":[null,...], "rep":{...}, "ohlc":[...],
     "members":[{"id":"3017","name":"奇鋐","ohlc":[[o,h,l,c]|null,...],
                 "flow":[float,...]}, ...],   # 成員股 OHLC + 每日法人淨買合計(億)，供 K 線+資金流疊加
     "note":"<偏大個股提示>"|null}
  ],
  "market": {"name":"加權指數",                 # 大盤基準（可切換顯示）
     "ohlc":[[o,h,l,c]|null,...],               # 加權指數每日 OHLC
     "flow":[float,...],                        # 全市場三大法人合計買賣超(億/日)
     "flow_fi":[float,...],                     # 全市場外資買賣超(億/日)
     "flow_it":[float,...]}                     # 全市場投信買賣超(億/日)
}
"""
import json, os, sys, time, datetime, urllib.request

NDAYS   = int(os.environ.get("NDAYS", "75"))     # 目標交易日數
FINMIND_TOKEN = os.environ.get("FINMIND_TOKEN", "").strip()  # FinMind 備援用（免費註冊取得；存成 GitHub secret）
UA      = {"User-Agent": "Mozilla/5.0 (compatible; tide-data-bot/1.0)"}
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType={t}&response=json"
# FinMind 全市場三大法人（T86 端點延遲/缺資料時的備援；全市場查詢需 token）
FINMIND_INST_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&start_date={s}&end_date={e}"
MI_URL  = "https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json"
# 上櫃(TPEx/櫃買中心) — AI 主題成員有部分為上櫃股(群聯/旺矽/精測/雙鴻/威剛/聯亞)，需另抓
TPEX_INST  = "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&o=json&se=EW&t=D&d={d}"
TPEX_QUOTE = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&d={d}"
def roc(ds):  # "20260616" -> "115/06/16"（民國年）
    return f"{int(ds[:4])-1911}/{ds[4:6]}/{ds[6:8]}"
# 大盤（加權指數）：發行量加權股價指數歷史 OHLC（月檔）＋ 三大法人買賣金額統計（每日合計/外資/投信）
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
    """全市場三大法人買賣差額（元）。
    回傳 {"tot":合計, "fi":外資(外資及陸資＋外資自營商), "it":投信}。
    以列名開頭比對（BFI82U 列：自營商(自行買賣)/自營商(避險)/投信/外資及陸資.../外資自營商/合計）。"""
    d = fetch(BFI_URL.format(d=ds))
    out = {"tot": 0.0, "fi": 0.0, "it": 0.0}
    if d and d.get("stat")=="OK":
        for r in d.get("data",[]):
            nm = str(r[0]).strip(); v = num(r[-1])
            if nm.startswith("合計"):   out["tot"] = v
            elif nm.startswith("外資"): out["fi"] += v      # 外資及陸資 + 外資自營商
            elif nm.startswith("投信"): out["it"] = v
    return out
# 上櫃個股歷史 OHLC：櫃買官方端點僅回最新日（不開放歷史），改用 FinMind 公開資料 API（含上市/上櫃歷史）
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice&data_id={sid}&start_date={s}&end_date={e}"
def fetch_finmind_ohlc(sid, s, e):
    """回傳 {YYYYMMDD: [o,h,l,c]}。"""
    d = fetch(FINMIND_URL.format(sid=sid, s=s, e=e)); out={}
    if d and d.get("status")==200:
        for r in d.get("data",[]):
            dt=str(r.get("date","")).replace("-","")
            out[dt]=[num(r.get("open")),num(r.get("max")),num(r.get("min")),num(r.get("close"))]
    return out

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

def t86_cols(t86):
    """定位 T86（或 FinMind 備援）每列的（三大法人合計, 外資欄位們, 投信）索引。
    - TWSE：用 response 的 fields 名稱比對（不寫死索引）。外資＝「外陸資買賣超股數(不含外資自營商)」
      ＋「外資自營商買賣超股數」兩欄加總；若來源只有合併欄（無「不含」拆分）則用合併欄，避免重複計算。
    - FinMind 備援：用其自帶 _cols。
    找不到時 tot 退回 -1（最後一欄，與舊版相容）、fi/it 回 None（該分項安全降級為 0）。"""
    if t86.get("_cols"):
        c = t86["_cols"]; return c["tot"], c["fi"], c["it"], c.get("nf")
    f = [str(x) for x in (t86.get("fields") or [])]
    su = [i for i, n in enumerate(f) if "買賣超" in n]
    fi = [i for i in su if ("外資" in f[i] or "外陸資" in f[i] or "陸資" in f[i])]
    split = [i for i in fi if "不含" in f[i] or "外資自營商" in f[i]]
    if split: fi = split
    it = [i for i in su if "投信" in f[i]]
    tot = [i for i in su if "三大法人" in f[i]]
    return (tot[0] if tot else -1), (fi or None), (it[0] if it else None), (len(f) or None)

def row_vals(r, cols):
    """依 t86_cols 的索引取出單列的（合計, 外資, 投信）淨買股數。
    防衛：實際列長與 fields 欄位數不符（T86 偶有短列）時，退回舊行為
    （最後一欄＝三大法人合計、分項略過為 0），確保永不 IndexError。"""
    tot_i, fi_is, it_i, nf = cols
    n = len(r)
    if not n:
        return 0.0, 0.0, 0.0
    if (nf and n != nf) or tot_i is None or tot_i == -1 or tot_i >= n:
        return num(r[-1]), 0.0, 0.0
    fi = sum(num(r[i]) for i in fi_is if i < n) if fi_is else 0.0
    it = num(r[it_i]) if (it_i is not None and it_i < n) else 0.0
    return num(r[tot_i]), fi, it

def fetch_t86_finmind(ds):
    """TWSE T86 端點延遲/缺資料時的備援。
    用 FinMind 全市場三大法人資料，重建成 T86 風格 dict：
        {"stat":"OK", "data":[[股票代號, "", 合計, 外資, 投信], ...],
         "_src":"finmind", "_cols":{"tot":2,"fi":[3],"it":4}}
    法人別歸類：name 以 Foreign 開頭（Foreign_Investor / Foreign_Dealer_Self）→ 外資；
    Investment_Trust → 投信；其餘（Dealer_self / Dealer_Hedging）只進合計。
    需 FINMIND_TOKEN（免費註冊）才能做「全市場」查詢；無 token 或查無資料回 None。"""
    if not FINMIND_TOKEN:
        return None
    s = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
    url = FINMIND_INST_URL.format(s=s, e=s) + f"&token={FINMIND_TOKEN}"
    d = fetch(url)
    if not d or d.get("status") != 200 or not d.get("data"):
        return None
    agg = {}   # 代號 -> [合計, 外資, 投信] 淨買股數
    for r in d["data"]:
        sid = str(r.get("stock_id", "")).strip()
        if not sid:
            continue
        net = num(r.get("buy")) - num(r.get("sell"))
        name = str(r.get("name", ""))
        a = agg.setdefault(sid, [0.0, 0.0, 0.0])
        a[0] += net
        if name.startswith("Foreign"):            a[1] += net
        elif name.startswith("Investment_Trust"): a[2] += net
    if not agg:
        return None
    rows = [[sid, "", v[0], v[1], v[2]] for sid, v in agg.items()]
    return {"stat": "OK", "data": rows, "_src": "finmind",
            "_cols": {"tot": 2, "fi": [3], "it": 4, "nf": 5}}

def fetch_t86(ds):
    """取某日 T86（三大法人）：先用 TWSE 官方端點，缺資料時改用 FinMind 備援。
    回傳與原 T86 相容的 dict（成功時 stat=='OK'）。"""
    r = fetch(T86_URL.format(d=ds, t="ALL"))
    if r and r.get("stat") == "OK" and r.get("data"):
        return r
    fb = fetch_t86_finmind(ds)
    if fb:
        print(f"  ⚠ T86 {ds} TWSE 端點缺資料，改用 FinMind 備援（{len(fb['data'])} 檔）", file=sys.stderr)
        return fb
    return r   # 原樣回傳（可能是 no-data，交由呼叫端判斷）

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
    回傳 (nv{sid:[三大法人合計, 外資, 投信] 買賣超股數}, oh{sid:[o,h,l,c]}, nm{sid:名稱})。
    外資/投信欄同樣用欄位名稱比對；優先用「不含外資自營商」拆分欄＋外資自營商欄加總。"""
    rd = roc(ds); nv={}; oh={}; nm={}
    di = fetch(TPEX_INST.format(d=rd))
    if di and str(di.get("stat","")).lower()=="ok":
        for t in di.get("tables",[]):
            f=[str(x) for x in (t.get("fields") or [])]
            if "三大法人買賣超股數合計" in f:
                ti=f.index("三大法人買賣超股數合計")
                su=[i for i,n in enumerate(f) if "買賣超" in n]
                fi=[i for i in su if ("外資" in f[i] or "陸資" in f[i])]
                split=[i for i in fi if "不含" in f[i] or "外資自營商" in f[i]]
                if split: fi=split
                it=[i for i in su if "投信" in f[i]]
                for r in t.get("data",[]):
                    sid=str(r[0]).strip()
                    if sid in want:
                        nv[sid]=[num(r[ti]),
                                 sum(num(r[j]) for j in fi) if fi else 0.0,
                                 num(r[it[0]]) if it else 0.0]
                        nm[sid]=str(r[1]).strip()
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
        r = fetch_t86(ds)
        time.sleep(0.4)
        if r and r.get("stat") == "OK":
            return d
        d -= datetime.timedelta(days=1)
    raise SystemExit("找不到最近交易日資料")

def build_ai_sectors(days, names_all):
    """用每日個股資料(x['mv']/=['mv_fi']/['mv_it']=成員淨買金額, x['oh']=OHLC)按 AI 主題加總，
    產出 dim='ai' 的板塊清單：series/series_fi/series_it、members=[{id,name,ohlc,flow}]、note=偏大個股提示。
    members 的 flow 維持三大法人合計（K 線疊加用；分項疊加 v2 再評估）。"""
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
        series_fi=[round(sum(x["mv_fi"].get(c,0) for c in codes)/1e8,2) for x in days]
        series_it=[round(sum(x["mv_it"].get(c,0) for c in codes)/1e8,2) for x in days]
        members=[{"id":c,"name":names_all.get(c,c),"ohlc":member_ohlc(c),
                  "flow":[round(x["mv"].get(c,0)/1e8,2) for x in days]} for c in codes]
        note=None
        if len(codes)>1:
            contrib={c:sum(abs(x["mv"].get(c,0)) for x in last20) for c in codes}
            tot=sum(contrib.values()) or 1
            big=max(contrib,key=contrib.get)
            if contrib[big]/tot>BIG_SHARE:
                note=f"{names_all.get(big,big)} 量級偏大（近20日約占{round(contrib[big]/tot*100)}%），看相對強度較公允"
        ai_out.append({"sector":theme,"dim":"ai","series":series,
                       "series_fi":series_fi,"series_it":series_it,
                       "idx":[None]*len(days),
                       "rep":{"id":members[0]["id"],"name":members[0]["name"]},
                       "ohlc":members[0]["ohlc"],"members":members,"note":note})
    ai_out.sort(key=lambda o:-sum(o["series"][-20:]))
    return ai_out

# ============================================================================
#  增量更新（incremental）相關
# ============================================================================
DATA_PATH   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")
SECMAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sector_map.json")
SECMAP_TTL_DAYS = 7   # 產業對照快取超過幾天就重建（產業歸屬鮮少變動）

def _save_sector_map(m):
    try:
        with open(SECMAP_PATH, "w", encoding="utf-8") as f:
            json.dump({"_built": datetime.date.today().strftime("%Y%m%d"), "map": m},
                      f, ensure_ascii=False, separators=(",", ":"))
    except Exception as e:
        print(f"  （sector_map 寫入失敗，可忽略：{e}）", file=sys.stderr)

def _get_sector_map(last):
    """取得 股票->產業 對照：優先用快取（7 天內），否則用近日 T86 重建並寫快取。"""
    try:
        if os.path.exists(SECMAP_PATH):
            with open(SECMAP_PATH, encoding="utf-8") as f:
                c = json.load(f)
            m = c.get("map") or {}
            built = c.get("_built", "")
            if m and built:
                age = (datetime.date.today() -
                       datetime.datetime.strptime(built, "%Y%m%d").date()).days
                if age <= SECMAP_TTL_DAYS:
                    print(f"  使用 sector_map 快取（{built}, {len(m)} 檔）", file=sys.stderr)
                    return m
    except Exception:
        pass
    cand, dd = [], last
    while len(cand) < 8:
        if dd.weekday() < 5:
            cand.append(dd.strftime("%Y%m%d"))
        dd -= datetime.timedelta(days=1)
    print("  重建 sector_map …", file=sys.stderr)
    m = build_stock_sector(cand)
    if m:
        _save_sector_map(m)
    return m

def _trading_days_between(cur_ds, last_date):
    """回傳 cur_ds（不含）之後到 last_date（含）之間的所有平日（YYYYMMDD）。"""
    out = []
    try:
        d = datetime.datetime.strptime(cur_ds, "%Y%m%d").date() + datetime.timedelta(days=1)
    except Exception:
        return out
    while d <= last_date:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += datetime.timedelta(days=1)
    return out

def fetch_day_bundle(ds, stock_sector):
    """抓單一交易日所需的原始資料並算好當日貢獻。無資料（假日/未出表）回 None。"""
    t86 = fetch_t86(ds); time.sleep(0.4)
    if not t86 or t86.get("stat") != "OK" or not t86.get("data"):
        return None
    mi = parse_mi(fetch(MI_URL.format(d=ds))); time.sleep(0.4)
    if not mi:
        return None
    ohlc, close, names, idx = mi
    names_all.update(names)
    cols = t86_cols(t86)
    sv = {}; sv_fi = {}; sv_it = {}; mv = {}; mv_fi = {}; mv_it = {}
    for r in t86["data"]:
        sid = r[0].strip(); px = close.get(sid, 0)
        tot, fi, it = row_vals(r, cols)
        val = tot * px; vfi = fi * px; vit = it * px
        sec = stock_sector.get(sid)
        if sec:
            sv[sec] = sv.get(sec, 0) + val
            sv_fi[sec] = sv_fi.get(sec, 0) + vfi
            sv_it[sec] = sv_it.get(sec, 0) + vit
        if sid in AI_MEMBERS:
            mv[sid] = val; mv_fi[sid] = vfi; mv_it[sid] = vit
    onv, _ooh, onm = fetch_otc(ds, OTC_WANT); time.sleep(0.4)
    names_all.update(onm)
    otc_ohlc = {}
    if onv:
        s = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        for sid in sorted(onv):
            fm = fetch_finmind_ohlc(sid, s, s); time.sleep(0.4)
            oh = fm.get(ds)
            px = oh[3] if oh else 0
            if oh:
                otc_ohlc[sid] = oh
            mv[sid] = onv[sid][0] * px       # 用當日收盤把「淨買股數」換算成金額
            mv_fi[sid] = onv[sid][1] * px
            mv_it[sid] = onv[sid][2] * px
    mkt = fetch_mkt_netbuy(ds); time.sleep(0.3)
    if not mkt["tot"] and t86.get("_src") == "finmind":
        # BFI82U 也可能與 T86 同步延遲；用全市場 Σ(淨買股數×收盤) 近似（合計/外資/投信各自加總）
        for r in t86["data"]:
            px = close.get(r[0].strip(), 0)
            tot, fi, it = row_vals(r, cols)
            mkt["tot"] += tot * px; mkt["fi"] += fi * px; mkt["it"] += it * px
    taiex = fetch_taiex_month(ds[:6] + "01")
    mk = taiex.get(roc(ds))
    mk_ohlc = mk if (mk and mk[3] > 0) else None
    return {"date": ds, "sv": sv, "sv_fi": sv_fi, "sv_it": sv_it,
            "mv": mv, "mv_fi": mv_fi, "mv_it": mv_it, "idx": idx, "ohlc": ohlc,
            "otc_ohlc": otc_ohlc, "mkt": mkt, "mk_ohlc": mk_ohlc}

def _idx_for(sec, idx_keys):
    if sec in idx_keys: return sec
    c = [n for n in idx_keys if n.startswith(sec)]
    if c: return sorted(c, key=len)[0]
    c = [n for n in idx_keys if sec.startswith(n)]
    if c: return sorted(c, key=len, reverse=True)[0]
    return None

def _member_ohlc_day(c, b):
    if c in b["otc_ohlc"]:
        return b["otc_ohlc"][c]
    v = b["ohlc"].get(c)
    return [v[0], v[1], v[2], v[3]] if (v and len(v) > 3 and v[3] > 0) else None

def append_day(data, b):
    """把單日 bundle b 接到既有 data 的每個陣列尾端（與全量重建的計算方式一致）。"""
    idx_keys = set(b["idx"].keys())
    for s in data["sectors"]:
        if s.get("dim") == "ai":
            members = s.get("members", [])
            codes = [m["id"] for m in members]
            s["series"].append(round(sum(b["mv"].get(c, 0) for c in codes) / 1e8, 2))
            s.setdefault("series_fi", []).append(round(sum(b["mv_fi"].get(c, 0) for c in codes) / 1e8, 2))
            s.setdefault("series_it", []).append(round(sum(b["mv_it"].get(c, 0) for c in codes) / 1e8, 2))
            s.setdefault("idx", []).append(None)
            for m in members:
                m.setdefault("ohlc", []).append(_member_ohlc_day(m["id"], b))
                m.setdefault("flow", []).append(round(b["mv"].get(m["id"], 0) / 1e8, 2))
            s.setdefault("ohlc", []).append(members[0]["ohlc"][-1] if members else None)
        else:
            sec = s["sector"]
            s["series"].append(round(b["sv"].get(sec, 0.0) / 1e8, 2))
            s.setdefault("series_fi", []).append(round(b["sv_fi"].get(sec, 0.0) / 1e8, 2))
            s.setdefault("series_it", []).append(round(b["sv_it"].get(sec, 0.0) / 1e8, 2))
            ino = _idx_for(sec, idx_keys)
            s.setdefault("idx", []).append(b["idx"].get(ino) if ino else None)
            rep = (s.get("rep") or {}).get("id")
            v = b["ohlc"].get(rep) if rep else None
            s.setdefault("ohlc", []).append(
                [v[0], v[1], v[2], v[3]] if (v and len(v) > 3 and v[3] > 0) else None)
    mk = data.get("market") or {"name": "加權指數", "ohlc": [], "flow": []}
    mk.setdefault("ohlc", []).append(b["mk_ohlc"])
    mk.setdefault("flow", []).append(round((b["mkt"]["tot"] or 0) / 1e8, 2))
    mk.setdefault("flow_fi", []).append(round((b["mkt"]["fi"] or 0) / 1e8, 2))
    mk.setdefault("flow_it", []).append(round((b["mkt"]["it"] or 0) / 1e8, 2))
    data["market"] = mk
    data.setdefault("dates", []).append(b["date"])
    data["updated"] = b["date"]

def recompute_ai_notes(data):
    """依（已修剪的）近20日成員資金流重算 AI 主題的「偏大個股」備註。"""
    for s in data["sectors"]:
        if s.get("dim") != "ai":
            continue
        members = s.get("members", [])
        if len(members) <= 1:
            s["note"] = None; continue
        contrib = {m["id"]: sum(abs(x) for x in (m.get("flow") or [])[-20:]) for m in members}
        tot = sum(contrib.values()) or 1
        big = max(contrib, key=contrib.get)
        if contrib[big] / tot > BIG_SHARE:
            bigname = next((m["name"] for m in members if m["id"] == big), big)
            s["note"] = f"{bigname} 量級偏大（近20日約占{round(contrib[big]/tot*100)}%），看相對強度較公允"
        else:
            s["note"] = None

def trim_all(data, n):
    """把所有逐日陣列修剪到最後 n 天，維持與 dates 對齊。"""
    def t(a): return a[-n:] if len(a) > n else a
    data["dates"] = t(data.get("dates", []))
    for s in data["sectors"]:
        for k in ("series", "series_fi", "series_it", "idx", "ohlc"):
            if isinstance(s.get(k), list):
                s[k] = t(s[k])
        for m in s.get("members", []):
            if isinstance(m.get("ohlc"), list): m["ohlc"] = t(m["ohlc"])
            if isinstance(m.get("flow"), list): m["flow"] = t(m["flow"])
    mk = data.get("market") or {}
    for k in ("ohlc", "flow", "flow_fi", "flow_it"):
        if isinstance(mk.get(k), list):
            mk[k] = t(mk[k])

def resort_sectors(data):
    """與全量重建相同：twse 與 ai 兩群各依近20日資金流由大到小排序，twse 在前。"""
    secs = data.get("sectors", [])
    tw = [s for s in secs if s.get("dim") != "ai"]
    ai = [s for s in secs if s.get("dim") == "ai"]
    tw.sort(key=lambda o: -sum((o.get("series") or [])[-20:]))
    ai.sort(key=lambda o: -sum((o.get("series") or [])[-20:]))
    data["sectors"] = tw + ai

def incremental_update():
    """增量更新主流程。成功更新回 True；無事可做回 False；需全量重建回 None。"""
    if not os.path.exists(DATA_PATH):
        print("無既有 data.json → 需全量重建", file=sys.stderr); return None
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"讀取 data.json 失敗（{e}）→ 需全量重建", file=sys.stderr); return None
    if (not data.get("dates") or len(data["dates"]) < 2 or not data.get("sectors")):
        print("既有資料不完整 → 需全量重建", file=sys.stderr); return None
    # A案 schema：缺法人分項（外資/投信）序列的舊資料無法增量接續，需全量重建一次補齊歷史
    n0 = len(data["dates"])
    if (not all(isinstance(s.get("series_fi"), list) and len(s["series_fi"]) == len(s.get("series", []))
                and isinstance(s.get("series_it"), list) for s in data["sectors"])
            or not isinstance((data.get("market") or {}).get("flow_fi"), list)):
        print("既有資料缺法人分項欄位（A案 schema）→ 需全量重建", file=sys.stderr); return None

    last = latest_trading_day()
    last_ds = last.strftime("%Y%m%d")
    cur = str(data.get("updated", ""))
    print(f"既有最新 {cur}，市場最新交易日 {last_ds}", file=sys.stderr)
    if last_ds <= cur:
        print("資料已是最新，無需更新", file=sys.stderr); return False
    gaps = _trading_days_between(cur, last)
    if not gaps:
        print("無新交易日", file=sys.stderr); return False
    if len(gaps) > 10:
        print(f"落後 {len(gaps)} 個交易日（過多）→ 需全量重建", file=sys.stderr); return None

    stock_sector = _get_sector_map(last)
    if not stock_sector:
        print("無法取得產業對照 → 需全量重建", file=sys.stderr); return None

    appended = 0
    for ds in gaps:
        b = fetch_day_bundle(ds, stock_sector)
        if not b:
            print(f"  {ds} 無資料（假日/未出表），略過", file=sys.stderr); continue
        append_day(data, b); appended += 1
        print(f"  已新增 {ds}（累計新增 {appended}）", file=sys.stderr)
    if appended == 0:
        print("沒有可新增的交易日（可能尚未出表，留待下個時段重試）", file=sys.stderr); return False

    trim_all(data, NDAYS)
    recompute_ai_notes(data)
    resort_sectors(data)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"增量更新完成 → updated={data['updated']}，交易日 {len(data['dates'])}，本次新增 {appended} 天",
          file=sys.stderr)
    return True

def run():
    """進入點：預設增量更新；必要時退回全量重建。"""
    if os.environ.get("FORCE_REBUILD") == "1":
        print("FORCE_REBUILD=1 → 全量重建", file=sys.stderr)
        return main()
    res = incremental_update()
    if res is None:        # 增量不適用 → 全量重建
        return main()
    # res True/False 都代表正常結束（True=有更新；False=本來就最新/尚未出表）

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
    if stock_sector:
        _save_sector_map(stock_sector)     # 全量重建時順手刷新產業對照快取
    print("對應股票數:", len(stock_sector),
          "| 產業數:", len(set(stock_sector.values())), file=sys.stderr)

    days = []                 # [{date, sv, sv_fi, sv_it, mv, mv_fi, mv_it, ix, oh, mkt, otc_sh}]
    otc_seen = set()          # 出現過的上櫃成員代號（之後用 FinMind 補歷史 OHLC）
    d = last
    guard = 0
    while len(days) < NDAYS and guard < NDAYS*3 + 40:
        guard += 1
        ds = d.strftime("%Y%m%d")
        d -= datetime.timedelta(days=1)
        if datetime.datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        t86 = fetch_t86(ds)
        time.sleep(0.4)
        if not t86 or t86.get("stat") != "OK":
            continue
        mi = parse_mi(fetch(MI_URL.format(d=ds)))
        time.sleep(0.4)
        if not mi:
            continue
        ohlc, close, names, idx = mi
        cols = t86_cols(t86)
        sv = {}; sv_fi = {}; sv_it = {}; mv = {}; mv_fi = {}; mv_it = {}
        for r in t86["data"]:
            sid=r[0].strip(); px=close.get(sid,0)
            tot, fi, it = row_vals(r, cols)
            val=tot*px; vfi=fi*px; vit=it*px
            sec=stock_sector.get(sid)
            if sec:
                sv[sec]=sv.get(sec,0)+val
                sv_fi[sec]=sv_fi.get(sec,0)+vfi
                sv_it[sec]=sv_it.get(sec,0)+vit
            if sid in AI_MEMBERS:                  # AI 主題成員(上市)的當日淨買金額
                mv[sid]=val; mv_fi[sid]=vfi; mv_it[sid]=vit
        # 上櫃成員：取「當日三大法人淨買股數（合計/外資/投信）」（官方）；股價(收盤)與 OHLC 稍後用 FinMind 補
        onv, _ooh, onm = fetch_otc(ds, OTC_WANT)
        time.sleep(0.4)
        names_all.update(onm)
        otc_seen.update(onv.keys())
        mkt = fetch_mkt_netbuy(ds); time.sleep(0.3)   # 大盤三大法人買賣差額(元)：合計/外資/投信
        # 大盤合計端點(BFI82U)也可能與 T86 同步延遲；若這天走 FinMind 備援且 BFI 拿不到，
        # 用「全市場 Σ(淨買股數×收盤)」近似三大法人買賣差額，避免大盤資金流當天空白。
        if not mkt["tot"] and t86.get("_src") == "finmind":
            for r in t86["data"]:
                px = close.get(r[0].strip(), 0)
                tot, fi, it = row_vals(r, cols)
                mkt["tot"] += tot*px; mkt["fi"] += fi*px; mkt["it"] += it*px
        days.append({"date":ds,"sv":sv,"sv_fi":sv_fi,"sv_it":sv_it,
                     "mv":mv,"mv_fi":mv_fi,"mv_it":mv_it,
                     "ix":idx,"oh":ohlc,"mkt":mkt,"otc_sh":dict(onv)})
        names_all.update(names)
        print("  ok", ds, "累計", len(days), file=sys.stderr)

    days.sort(key=lambda x:x["date"])
    dates=[x["date"] for x in days]

    # 上櫃成員：用 FinMind 補正確的每日 OHLC，並用「當日收盤」重算資金流金額（股數×當日收盤）
    if otc_seen and dates:
        s0=f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:8]}"
        s1=f"{dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:8]}"
        for sid in sorted(otc_seen):
            fm=fetch_finmind_ohlc(sid, s0, s1); time.sleep(0.5)
            print("  FinMind", sid, "天數", len(fm), file=sys.stderr)
            for x in days:
                oh=fm.get(x["date"])
                if oh: x["oh"][sid]=oh
                sh=x.get("otc_sh",{}).get(sid)
                if sh:
                    px=(oh[3] if oh else 0)
                    x["mv"][sid]=sh[0]*px
                    x["mv_fi"][sid]=sh[1]*px
                    x["mv_it"][sid]=sh[2]*px

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
        series_fi=[round(x["sv_fi"].get(sec,0.0)/1e8,2) for x in days]
        series_it=[round(x["sv_it"].get(sec,0.0)/1e8,2) for x in days]
        ino=idx_for(sec)
        idx=[(x["ix"].get(ino) if ino else None) for x in days]
        cands=[s for s in sec_stocks[sec] if s in turn]
        rep=max(cands,key=lambda s:turn[s]) if cands else None
        ohlc=[]
        if rep:
            for x in days:
                v=x["oh"].get(rep)
                ohlc.append([v[0],v[1],v[2],v[3]] if (v and v[3]>0) else None)
        out.append({"sector":sec,"dim":"twse","series":series,
                    "series_fi":series_fi,"series_it":series_it,"idx":idx,
                    "rep":{"id":rep,"name":names_all.get(rep,"")} if rep else None,
                    "ohlc":ohlc})
    out.sort(key=lambda o:-sum(o["series"][-20:]))

    # ===== AI 主題維度（dim=ai）：用同一批個股資料按主題加總，附成員股 OHLC 與偏大備註 =====
    ai_out = build_ai_sectors(days, names_all)

    # ===== 大盤（加權指數）：OHLC（月檔合併）＋ 每日三大法人買賣超（億：合計/外資/投信） =====
    taiex = {}
    for m in sorted({x["date"][:6]+"01" for x in days}):
        taiex.update(fetch_taiex_month(m)); time.sleep(0.3)
    mk_ohlc = [(taiex.get(roc(x["date"])) if (taiex.get(roc(x["date"])) and taiex.get(roc(x["date"]))[3]>0) else None) for x in days]
    mk_flow    = [round(x["mkt"]["tot"]/1e8,2) for x in days]
    mk_flow_fi = [round(x["mkt"]["fi"]/1e8,2) for x in days]
    mk_flow_it = [round(x["mkt"]["it"]/1e8,2) for x in days]
    market = {"name":"加權指數","ohlc":mk_ohlc,"flow":mk_flow,
              "flow_fi":mk_flow_fi,"flow_it":mk_flow_it}

    res={"updated":dates[-1],"dates":dates,"sectors":out+ai_out,"market":market}

    with open(DATA_PATH,"w",encoding="utf-8") as f:
        json.dump(res,f,ensure_ascii=False,separators=(",",":"))
    print("寫出", DATA_PATH, "| 交易日", len(dates), "| 產業", len(out), "| AI主題", len(ai_out), file=sys.stderr)

names_all={}
if __name__=="__main__":
    run()
