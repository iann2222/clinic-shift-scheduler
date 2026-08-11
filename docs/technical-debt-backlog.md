# Technical Debt Backlog

本文件只記錄目前尚待處理的技術債，作為進入使用者前端開發前的整理清單。

處理原則：

- 每完成並驗證一項，就直接從本文件刪除該項，不保留已完成清單。
- 重構不得改變既有 v1 排班規則、正式最佳化順序或輸出結果契約，除非另有明確的規格決策。
- 涉及 solver、metrics 與 validator 的調整，必須維持三者重算結果一致，並執行完整測試。
- 不必為了開始前端而先清除所有低優先項目，但「前端開發前置項目」應先完成。

## 前端開發前置項目

### 建立共用 application service

目前 `src/run_scheduler.py` 會把已解析的 config 重新轉成 CLI arguments，再交由 argparse 與 runner 執行；`run_schedule_file()` 也同時負責讀檔、展開、驗證、precheck、求解、輸出、計時、候選處理與目錄管理。

預計處理：

- 建立 CLI、未來 GUI 與封裝入口共同使用的 application service。
- 讓 CLI 與 GUI 都只是 adapter，不互相呼叫。
- 消除 runner 與 solver 重複執行 precheck 的情況。
- 將執行要求、成功結果與失敗結果改成明確型別。
- 保留目前手動編輯 JSON／config 並執行的方式。

### 建立正式的使用者輸入模型與讀寫邊界

目前使用者維護的 `weekly-v1` 由 `authoring.py` 直接操作原始 mapping，缺少獨立的 typed model、JSON Schema 與穩定 serializer；現有 Schema 只描述展開後的 canonical v1。

預計處理：

- 為 weekly authoring input 建立版本化資料模型與 Schema。
- 為 `config.json` 建立版本化 Schema 或等價的正式欄位契約。
- 提供 `from_dict()`、`to_dict()`、讀檔與原子寫檔功能。
- round-trip 時保留 `notes` 等使用者資料。
- 統一 Schema 與 runtime validation，避免兩套規則漂移。
- 前端只編輯使用者輸入與 config，不直接編輯 `runtime/expanded-input`。

### 統一結構化錯誤與進度事件

目前 canonical validation、weekly authoring、config、precheck、runner 與 CLI 使用不同的錯誤形式；進度回呼則是純文字，CLI 依文字前綴判斷是否覆寫同一行。

預計處理：

- 統一欄位路徑、錯誤代碼、訊息、階段與嚴重程度等結構。
- weekly input 與 config validation 應能一次回報多項欄位錯誤。
- runner 不應把結構化 precheck 診斷壓平成單一字串。
- 將進度改為 typed events，再由 CLI／GUI 各自決定呈現方式。
- 評估正式最佳化的取消介面，避免 GUI 只能強制終止程序。

### 降低套件入口的 eager import 與原生依賴耦合

目前 package `__init__.py` 會一次匯入 solver、exporter、runner、OR-Tools、openpyxl 與 ReportLab；metrics、validator 與 output contract 也直接依賴 `optimization.py` 的型別。

預計處理：

- 縮小 package root 的公開 API，避免匯入設定功能時載入全部重型 dependencies。
- 將 objective stage、fairness metric、result records 等契約型別移到輕量模組。
- 讓純輸入編輯與驗證畫面不必先載入 OR-Tools native runtime。
- 視需要採明確子模組 import 或 lazy import。

## 高優先技術債

### 移除舊版最佳化路徑與無效模型變數

`optimization.py` 同時保留正式 conditional benchmark／regret 流程與先前的 legacy objective，並暴露 `build_phase_four_model()` 相容名稱。部分已非正式目標的 global consecutive、class quality 與舊 stage 結構仍存在於模型或 result metrics。

預計處理：

- 確認沒有仍需支援的外部舊 API。
- 移除 `_solve_lexicographic_legacy()`、舊 objective specs 與相容 alias。
- 移除正式求解不再使用的 CP-SAT 變數、metrics 欄位與 stage 值。
- 將正式 stage 與內部 fairness metric bucket 使用不同型別。
- 比較清理前後模型規模、求解結果與測試結果。

### 拆分過大的核心函式與模組

目前主要複雜點包括：

- `build_optimization_model()` 約 766 行。
- `recompute_schedule_metrics()` 約 610 行。
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

### 統一 config 的預設值來源

目前預設值同時存在於 dataclass、argparse 與 `config.json` 的「預設設定」區塊；「預設設定」只供查閱、不參與執行，部分值與程式預設並不相同。

預計處理：

- 指定唯一的 executable defaults 來源。
- 由該來源產生範例或還原預設設定。
- 明確區分「實際生效設定」與「範例／還原用設定」。
- 前端的「還原預設」不得自行複製另一套常數。

### 整理測試結構與未執行的 legacy tests

`tests/test_optimization.py` 已超過 2,000 行，且有多個 `_legacy_` 方法不符合 pytest 收集命名，因此看似測試但實際不會執行。

預計處理：

- 刪除已失效的 legacy tests，或將仍有價值的案例改寫成目前正式政策測試。
- 依 TARGET、類別偏好、比例公平、整數公平、共同公平與候選解拆分測試模組。
- 加入測試收集數或明確的 policy coverage，避免測試被改名後靜默失效。

### 移除未使用 dependency 並改善發布可重現性

目前 `pandas` 已列在 `pyproject.toml` 與發布 manifest，但程式碼沒有使用；部分發布 dependencies 只限制版本範圍，重建同一版本時可能取得不同套件版本。

預計處理：

- 移除確認未使用的 `pandas`。
- 確認 PyInstaller 產物與 smoke test 不受影響。
- 評估為正式發布保存 tested lock／constraints 或完整 dependency manifest。
- 統一 `pyproject.toml` 與 packaging config 的版本來源或加入一致性檢查。

## 低優先技術債

### 合併重複的小型基礎功能

目前可見的重複包括：

- CLI 與 runner 的秒數／分鐘格式化。
- JSON、Excel、PDF 與中間輸入的 temporary file＋replace 流程。
- app config、weekly authoring 與 canonical validation 的基本型別解析工具。
- precheck 與 optimization 的硬性班次上下界 helper。

應只抽出具有相同語意的部分，避免建立過度抽象的通用工具。

### 清理過時命名與註解

目前仍有 `build_phase_four_model`、`implemented_objective_prefix_optimal`、phase-one／phase-three docstring，以及「候選診斷／候選處理」混用等歷史名稱。

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

## 進入使用者前端的條件

開始製作實際畫面前，至少應完成：

1. 共用 application service。
2. weekly input／config 的正式模型、Schema 與原子讀寫器。
3. 結構化 validation、precheck、執行錯誤與 progress events。
4. 輕量 package import 邊界，避免設定畫面啟動時強制載入 solver 與 exporters。

完成以上項目後，前端可直接維護使用者輸入 JSON 與 `config.json`，並呼叫同一套正式排班流程；原本手動編輯 JSON／config 的方式繼續保留。
