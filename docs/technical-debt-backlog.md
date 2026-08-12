# Technical Debt Backlog

本文件只記錄目前尚待處理的技術債，作為進入使用者前端開發前的整理清單。

處理原則：

- 每完成並驗證一項，就直接從本文件刪除該項，不保留已完成清單。
- 重構不得改變既有 v1 排班規則、正式最佳化順序或輸出結果契約，除非另有明確的規格決策。
- 涉及 solver、metrics 與 validator 的調整，必須維持三者重算結果一致，並執行完整測試。
- 其餘項目可依風險與開發節奏處理，不必為了開始前端先全部清除。

## 高優先技術債

### 拆分過大的核心函式與模組

目前主要複雜點包括：

- `build_optimization_model()` 約 598 行。
- `recompute_schedule_metrics()` 約 493 行。
- `validate_schedule_result()` 約 436 行。
- `solve_lexicographic()` 約 256 行。
- `run_schedule_file()` 約 250 行。
- `run_prechecks()` 約 204 行。

預計依責任拆分模型指標建立、類別偏好、個人公平、共同公平、求解控制、結果重算、硬性驗證與應用流程；避免只把程式搬成更多大型 helper 而沒有形成清楚邊界。

### 集中宣告正式最佳化政策

目前正式 stage 順序、A/B 指標、fairness group 指標、共同公平權重及 objective 重算規則分散在 optimizer、metrics、validator 與 output。

預計處理：

- 建立不依賴 CP-SAT 的 declarative policy module。
- 集中正式 stage 順序、類別適用 metric、方向、權重與顯示名稱。
- solver 與獨立 metrics 各自實作計算，但共用同一份不可變政策定義。
- 保留 validator 不讀取 CP-SAT 衍生變數的獨立性。

### 讓正式輸出成為整組交易

目前 JSON、Excel、PDF 各自原子寫入，但三份正式檔案依序提交；後一種媒介失敗時可能留下不完整或不同版本的輸出組合。

預計處理：

- 先在 staging directory 產生並驗證全部正式檔案。
- 全部成功後才替換正式輸出。
- 失敗時清理暫存產物並保留上一組完整結果。
- 候選班表輸出採用相同策略或明確標示部分成功狀態。

## 中優先技術債

### 明確化 Excel 與 PDF 的版面契約

PDF exporter 目前依賴固定 sheet 名稱、固定儲存格座標與求解資訊文字標籤。這符合 PDF 由正式 Excel 產生的需求，但 Excel 版面微調容易意外破壞 PDF。

預計處理：

- 集中 sheet 名稱、區塊位置與必要欄位定義。
- 為 workbook contract 加入版本或 metadata。
- PDF 讀取結構化定位資訊，避免散落固定座標。

### 拆分大型最佳化測試模組

`tests/test_optimization.py` 集中涵蓋多個不同責任，後續新增案例時不易定位與維護。

預計處理：

- 依 TARGET、類別偏好、比例公平、整數公平、共同公平與候選解拆分測試模組。
- 加入測試收集數或明確的 policy coverage，避免測試被改名後靜默失效。

### 改善發布依賴的可重現性

部分發布 dependencies 只限制版本範圍，重建同一版本時可能取得不同套件版本。目前封裝版本與專案版本已有一致性測試及建置前檢查，但仍分別儲存在兩份設定中。

預計處理：

- 確認 PyInstaller 產物與 smoke test 不受影響。
- 評估為正式發布保存 tested lock／constraints 或完整 dependency manifest。
- 評估讓 `pyproject.toml` 與 packaging config 改由單一來源產生版本值。

## 低優先技術債

### 合併重複的小型基礎功能

目前可見的重複包括：

- JSON、Excel、PDF 與中間輸入的 temporary file＋replace 流程。
- app config、weekly authoring 與 canonical validation 的基本型別解析工具。

應只抽出具有相同語意的部分，避免建立過度抽象的通用工具。

### 清理過時命名與註解

目前仍有 `implemented_objective_prefix_optimal`，以及內部「候選診斷」與使用者訊息「候選處理」混用等歷史名稱。

預計處理：

- 統一目前完整 v1 的正式名稱。
- 更新 package description、docstrings、README 與 CLI help。
- 若涉及公開 JSON 欄位或 API，需先決定相容與版本策略。

### 加入基本靜態品質檢查與 CI

目前主要依賴 pytest，尚未配置格式、lint、型別檢查與持續整合。

預計處理：

- 選擇並配置最小必要的 formatter／linter。
- 評估 Pyright 或 Mypy，優先覆蓋 contracts、models 與 application service。
- CI 至少執行完整 pytest、靜態檢查及必要的 packaging contract tests。
- Windows 封裝與 native smoke test 可保留為獨立、較低頻率工作。

### 隔離已知版本相容 workaround

TARGET 絕對偏差目前包含針對 OR-Tools 9.12 `AddAbsEquality` 的已知避錯寫法；runner 也包含供 VS Code 直接執行單檔的 bootstrap。

這些特例目前都有實際用途，不應直接刪除，但應：

- 保留針對性 regression test。
- 在未來升級 OR-Tools 時重新驗證是否仍需要 workaround。
- 將 VS Code／封裝入口特例限制在 adapter 層，不進入 application service 或 domain core。
