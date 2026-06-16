# 變更治理機制

> **這份文件的角色**：定義「每次改動怎麼留下痕跡、版本怎麼編、重大決策怎麼記」。目標是讓任何一次修改都**可記錄、可追蹤、可回溯理由**。

- 最後更新：2026-06-16
- 維護者：單人

---

## 1. 三層紀錄，各管一件事

| 紀錄 | 回答 | 顆粒度 | 在哪 |
|---|---|---|---|
| **CHANGELOG** | 哪一版**改了什麼** | 每次發版 | [`../CHANGELOG.md`](../CHANGELOG.md) |
| **決策紀錄 ADR** | 某個設計**為什麼**這樣決定 | 每個重大岔路決定 | [`decisions/`](decisions/) |
| **版本號** | 這次改動**多大** | 每次發版 | CHANGELOG 標題 + 選用的 git tag |

三者搭配：版本號告訴你「改動量級」，CHANGELOG 告訴你「改了什麼」，ADR 告訴你「為什麼」。多數小改動只需動 CHANGELOG；只有「岔路決定」才寫 ADR。

---

## 2. 版本號規則（語意化版本，簡化版）

採 `MAJOR.MINOR.PATCH`（如 `1.2.0`），依本產品的性質定義：

| 位數 | 何時 +1 | 例子 |
|---|---|---|
| **MAJOR** | 改變產品定位、推翻[非目標](00-product-brief.md#6-非目標明確不做的事)、或 `data.json` schema 破壞性變更 | 從「板塊」改成「個股」輪動圖；schema 改欄位 |
| **MINOR** | 新增功能、新指標、UI 重大改版（不破壞既有資料契約） | 加入標準化指標；新增一個視圖 |
| **PATCH** | bug 修正、文字調整、視覺微調、文件更新 | 修時間基準 bug；縱軸正名；圖例補字 |

規則：
- **版本號是「人」決定的**，不是自動產生。發版時你判斷這次改動屬於哪一層。
- 起點是 `0.1.0`（產品已上線、但仍在收斂、尚未承諾穩定）。當你認為它「定型、可對外穩定」時再升 `1.0.0`。
- `0.x` 階段，破壞性變更可只升 MINOR（SemVer 對 0.x 的慣例）。

**版本號記在哪**：每次發版在 [CHANGELOG](../CHANGELOG.md) 開一個新版本區塊。若已接 git（見 §6），同步打一個 tag：`git tag v0.2.0`。

---

## 3. CHANGELOG 規範

採 [Keep a Changelog](https://keepachangelog.com/zh-TW/) 格式。每個版本一個區塊，底下用這幾類分組（沒有的類別就省略）：

- **Added** 新增的功能
- **Changed** 既有行為的改變
- **Fixed** bug 修正
- **Removed** 移除的功能
- **Docs** 文件/治理的變更（本產品額外加的類別，因為文件也版控）

頂端永遠保留一個 `[Unreleased]` 區塊，隨手把「已做但還沒發版」的改動往裡丟；發版時把它整段改名成新版本號 + 日期即可。

每條目寫法：**動詞開頭、一句話、必要時連到 PRD 功能編號或 ADR**。例如：

```
### Fixed
- 修正時間軸停在兩交易日之間時，泡泡位置與資訊卡象限不一致的問題（F-V3, F-V5；見 ADR-0002）
```

---

## 4. 決策紀錄（ADR — Architecture/Any Decision Record）

### 什麼時候要寫 ADR？

當一個決定符合以下任一條件——**未來的你可能會問「當初為什麼這樣？」**——就值得寫：

- 改變核心演算法或指標定義（視窗長度、標準化方式、象限切法）
- 換資料來源、改 `data.json` schema
- 推翻或新增一條[非目標](00-product-brief.md#6-非目標明確不做的事)
- 在兩個都合理的方案間做了取捨（例如本案的「停止播放時吸附整數日」vs「資訊卡改用內插值」）

一般 bug 修正、文字、視覺微調**不需要** ADR，記 CHANGELOG 即可。

### ADR 怎麼寫？

- 一個決定一個檔，放 [`decisions/`](decisions/)，命名 `ADR-NNNN-短標題.md`（編號遞增、不重用）。
- 用 [`03-workflow-and-templates.md`](03-workflow-and-templates.md#adr-範本) 的範本。
- 核心欄位：**背景 / 決定 / 理由 / 後果 / 替代方案**。
- ADR 一旦寫下就**不修改內容**，只改「狀態」。要改變一個舊決定 → 寫新 ADR，並在舊的標 `已被 ADR-XXXX 取代`。這樣決策的演變史本身也留得下來。

ADR 狀態：`提議中` → `已採納` → （日後可能）`已棄用` / `被 ADR-XXXX 取代`。

---

## 5. 完成的定義（Definition of Done）

一個改動要算「做完」，必須：

1. ☐ 功能照 [PRD](01-prd.md) 的驗收標準運作（手動驗過）。
2. ☐ 若改了資料層：本機跑 `python3 build_data.py` 能產出合法 `data.json`，前端讀得進去。
3. ☐ 若改了前端：`file://` 直開（用備援資料）與 HTTP 部署（讀外部 data.json）兩種情境都試過。
4. ☐ [CHANGELOG](../CHANGELOG.md) 的 `[Unreleased]` 已記上這筆。
5. ☐ 若屬重大決定：對應 ADR 已寫。
6. ☐ 若改了功能範圍：[PRD](01-prd.md) 已同步更新。

---

## 6. git 升級路徑（目前尚未啟用）

目前專案**還沒**初始化成本機 git repo，所以變更機制以 **CHANGELOG 為主**——它不依賴 git 也能完整運作。等你準備好接 GitHub（README 已寫好 GitHub Pages 部署步驟），再無痛升級：

1. 在 `tide-deploy/` 執行 `git init`、`git add .`、`git commit -m "chore: initial commit (v0.2.0)"`。
2. 之後 commit 訊息建議用慣例前綴，與 CHANGELOG 類別對齊：
   - `feat:` 新功能（→ Added）
   - `fix:` 修正（→ Fixed）
   - `refactor:`／`style:` 重構/樣式（→ Changed）
   - `docs:` 文件（→ Docs）
   - `data:` 資料更新（GitHub Actions 已在用這個前綴）
3. 發版時打 tag：`git tag v0.2.0 && git push --tags`。
4. CHANGELOG 仍是「給人看」的權威紀錄；git log 是「給機器/細節」的補充。兩者不衝突。

> 啟用 git 後，這份文件的 §6 改為「已啟用」，並可考慮用 GitHub Releases 對應 CHANGELOG 版本區塊。

---

## 7. 相關文件

- 流程與所有範本（CHANGELOG 條目、ADR、發版檢查清單）→ [`03-workflow-and-templates.md`](03-workflow-and-templates.md)
- 變更紀錄本體 → [`../CHANGELOG.md`](../CHANGELOG.md)
- 決策紀錄 → [`decisions/`](decisions/)
