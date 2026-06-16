# 資金輪動 · 台股板塊趨勢

每天追蹤三大法人資金流向，用動態象限圖看資金正在輪動到哪些板塊，並對照各產業龍頭股 K 線。
資料來源：臺灣證券交易所公開資料（三大法人買賣超 T86＋每日收盤行情 MI_INDEX）。
僅供參考，不構成投資建議。

> 📋 **專案治理文件**在 [`docs/`](docs/)：產品定位、PRD、變更治理、流程範本、ROADMAP、決策紀錄。
> 變更紀錄見 [`CHANGELOG.md`](CHANGELOG.md)。要加/改功能前請先看 [`docs/README.md`](docs/README.md)。

## 專案結構

```
.
├── index.html                  # 主程式（單檔前端，載入 data.json）
├── data.json                   # 資料快照（由 Actions 每日自動更新）
├── build_data.py               # 抓取＋計算腳本（純 Python 標準庫，無相依）
└── .github/workflows/
    └── update.yml              # 每交易日收盤後自動更新 data.json
```

`index.html` 內含一份資料當作離線備援，所以直接用瀏覽器打開檔案也能看；
部署到網路後則會優先讀取同目錄的 `data.json`（每日更新的版本），右上 🔄 可手動重新整理。

## 部署到 GitHub Pages（免費、自動每日更新）

1. **建立 repo**：在 GitHub 新建一個 **public** 儲存庫（私有 repo 的 Pages 需付費方案）。
2. **上傳檔案**：把本資料夾（`tide-deploy`）內的所有內容放到 repo **根目錄**，
   確認根目錄有 `index.html`、`data.json`、`scripts/`、`.github/`，然後 commit、push。
   - 用網頁拖拉上傳也可以，但 `.github/workflows/update.yml` 的資料夾結構要保留。
3. **開啟 Pages**：repo → **Settings → Pages** →
   Source 選 **Deploy from a branch** → Branch 選 `main`、資料夾 `/ (root)` → Save。
   稍候 1～2 分鐘，網址會是 `https://<你的帳號>.github.io/<repo 名>/`。
4. **允許 Actions 寫入**：repo → **Settings → Actions → General** →
   最下方 **Workflow permissions** 選 **Read and write permissions** → Save。
   （這樣排程才能把更新後的 `data.json` commit 回 repo。）
5. **跑第一次更新**：repo → **Actions** 分頁 → 左側 **update-data** → **Run workflow**。
   完成後 `data.json` 會更新到最新交易日；之後每個交易日 **台灣時間約 18:30** 會自動更新。

> 排程時間可在 `.github/workflows/update.yml` 的 `cron` 調整（時間為 UTC，台灣 = UTC+8）。
> GitHub 排程偶爾會延遲數十分鐘，屬正常現象。

## 本機預覽（選用）

直接雙擊 `index.html` 即可（用內嵌備援資料）。
若要在本機測試讀取外部 `data.json`，需用簡易伺服器（瀏覽器對 `file://` 會擋 fetch）：

```bash
cd tide-deploy
python3 -m http.server 8000
# 瀏覽器開 http://localhost:8000
```

## 手動更新資料

```bash
python3 build_data.py        # 產生最新 data.json（預設抓約 75 個交易日）
NDAYS=120 python3 build_data.py   # 想拉更長歷史可調 NDAYS
```

## 指標說明

- **位置（X 軸）**：近 5 日三大法人淨買超金額（億元），右＝流入、左＝流出。
- **位置（Y 軸）**：資金加速度＝近 5 日日均 − 前 5 日日均（億/天），上＝加速、下＝放緩。
- **泡泡大小**：近 20 日累計淨買超金額。
- **四象限**：漲潮（加速流入）／輪動（流入但放緩）／觀望（沉寂）／退潮（流出）。
- **產業 K 線**：個股模式為該產業「成交金額最大龍頭股」的真實 OHLC；指數模式為類股指數收盤走勢（類股指數無 OHLC，故為走勢線）。
