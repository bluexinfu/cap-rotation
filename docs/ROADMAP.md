# 待辦藍圖 ROADMAP

> **這份文件的角色**：接下來可能做的事，依價值與正確性排序（排序原則見 [流程 §2](03-workflow-and-templates.md#2-怎麼決定優先級)）。這不是承諾，是一個會持續調整的清單。多數條目源自已歸檔的 [圖表系統審查報告](archive/圖表系統審查報告.md)。

- 最後更新：2026-07-06（v0.5.0 發版時同步；先前停在 06-18 與實況脫節，已補齊）

優先級：🔴 P0 必做　🟠 P1 高　🟡 P2 中　🟢 P3 低/長期

---

## ✅ 已完成（v0.5.0 · 2026-07-06）

「從看圖到做決策的最後一哩」三案（規格討論見專案資料夾「優化提案_四方向_2026-07-05.md」）：

| # | 項目 | 紀錄 |
|---|---|---|
| B案 | 當日變化列（換象限/逆勢名單進出/潮汐翻轉，純狀態紀錄）＋排行榜「連續天數」欄＋資訊卡「象限停留第 N 天」 | CHANGELOG v0.5.0 |
| A案 | 法人拆解視角（合計/外資/投信切換；data.json 增 series_fi/series_it、flow_fi/flow_it） | CHANGELOG v0.5.0 |
| ~~R9~~/C案 | 量價背離觀察標記 ⇄（資金進價未跟／價漲資金退；預設關閉；紅線寫死） | [ADR-0011](decisions/ADR-0011-divergence-observation.md) |
| 管線 | 每日更新改增量（治本 build 卡數小時）＋ T86 短列防衛 | CHANGELOG v0.5.0 |

## ✅ 已完成（v0.4.0 · 2026-06-27）

| # | 項目 | 紀錄 |
|---|---|---|
| R8 | 中性門檻改用各板塊自身波動 σ（1σ） | [ADR-0008](decisions/ADR-0008-neutral-threshold-sigma.md) |
| R14 | 逆勢強勢加最低 1σ 門檻 | [ADR-0009](decisions/ADR-0009-counter-tide-sigma-floor.md) |
| R13 | 「市場相對」第 3 種座標尺度 | [ADR-0010](decisions/ADR-0010-market-relative-scale.md) |
| R6 | 四象限卡方位標更清楚（含手機） | CHANGELOG v0.4.0 |
| R10 | 更新停擺自動通知（workflow 失敗寄信） | CHANGELOG v0.4.0 |
| R15 | PRD 補齊 v0.3.0 功能 F-V15~18 | CHANGELOG v0.4.0 |

## ✅ 已完成（v0.3.0 / v0.2.x）

| # | 項目 | 紀錄 |
|---|---|---|
| AI主題 | AI 主題分群維度＋成員 K 線＋資金流疊加；上櫃資料源 | [ADR-0006](decisions/ADR-0006-ai-theme-dimension.md)、[ai-themes.md](ai-themes.md) |
| 大盤/逆勢 | 加權指數基準卡；大盤潮汐；逆勢強勢高亮 | [ADR-0007](decisions/ADR-0007-counter-tide-strength.md) |
| R7 | Y 軸動能 EMA(span=3) 輕平滑（翻轉率 30.6%→24.5%） | [ADR-0005](decisions/ADR-0005-ema-smoothing-momentum.md) |
| R12 | X 軸改近5日日均（與 Y 同單位） | [ADR-0004](decisions/ADR-0004-x-axis-daily-average.md) |
| R11 | workflow actions 升級 Node 24 | CHANGELOG v0.2.1 |
| R1~R5 | 審查報告全部發現（時間基準/方位/相對強度/軸名/圖例） | [ADR-0002](decisions/ADR-0002-time-base-alignment.md)、[ADR-0003](decisions/ADR-0003-relative-strength-normalization.md) |

---

## 待辦 / 待評估

| # | 項目 | 優先 | 備註 |
|---|---|---|---|
| D案 | 串接 V2 持股巡檢：V2 端 `daily_review.py` 讀本專案 `data.json`，每日報告加「持股所屬板塊象限＋停留天數」一節 | 🟠 P1 | **改的是 V2 端、本專案零改動**；規格見「優化提案_四方向_2026-07-05.md」§D。holdings.json 加 `rotation_map` 欄位、演算法鏡像 ADR-0005/0008（該處變更需同步） |
| — | 靈敏度切換（標準 1σ ↔ 敏感 0.5σ） | 🟢 長期 | 2026-06-27 討論結論：早期跡象看「位置漂移＋動能 Y＋20日累計」即可，門檻只管顏色不管位置，暫不做 |
| — | AI 主題的量價背離（成員股價替代類股指數） | 🟢 長期 | ADR-0011 v2 議題：成員僅 3 檔、易被單一個股綁架，需先解決代表性 |
| — | 法人拆解 v2：AI 主題成員資金流疊加也拆法人別 | 🟢 長期 | v1 成員 flow 維持合計；視使用頻率再評估 |

---

## 刻意不做（守住非目標）

以下需求若出現，預設**拒絕**，除非寫 ADR 推翻對應[非目標](00-product-brief.md#6-非目標明確不做的事)：

- 買賣訊號/選股建議、個股層級輪動圖、盤中即時資料、使用者帳號/雲端同步、付費資料源。
- **ADR-0011 新增的預設拒絕清單**：「背離＋漲潮＝提示」組合條件、背離推播、背離排行榜、把 ⇄ 上多空色。
