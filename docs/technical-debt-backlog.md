# Technical Debt Backlog

本文件只記錄目前尚待處理的技術債、已確認的行為風險，以及需要正式決策的產品問題。最近一次完整盤點日期為 2026-09-15。

處理原則：

- 每完成並驗證一項，就直接從本文件刪除整個對應項目，不保留已完成清單；完成歷史由 Git 記錄。
- 項目前綴用來區分 `[行為修正]`、`[架構重構]`、`[純重構]`、`[產品決策]`、`[文件]` 與 `[效能實驗]`。
- 純重構不得改變既有 v1 排班規則、正式最佳化順序、狀態語意、objective vector 或輸出契約。
- 涉及 solver、metrics 與 validator 的調整，必須維持三者計算定義一致，並執行完整測試。
- 產品決策與可能改變既有行為的項目，必須先確認規格，不能混在重構中順便修改。
- 文件中的行號與程式規模會隨開發變動；判斷是否完成應以責任邊界與完成條件為準。

## 高優先：可靠性與架構邊界

### [產品決策] 明確界定 GUI 能編輯的正式輸入能力

目前 GUI 的簡化操作未完整呈現 authoring schema 的所有能力：

- 正職 schema 可明確提供 `available_slots`，但 GUI 主要採「預設可排，只編輯不可排」，開啟既有資料時可能無法忠實呈現這類限制。
- 純 GUI 建立或從上月複製時會清空假日，而假日標記區目前不可編輯，因此無法只靠 GUI 啟用假日公平性資料。
- 兼職 availability 可帶職務範圍，但簡化的日期／時段介面未必能完整編輯 role-scoped availability。

需要先決定：正式支援這些欄位的編輯、以唯讀方式保留並提示，或在 GUI 開啟時明確拒絕無法無損編輯的文件。不可默默遺失或改寫使用者原有語意。

完成條件：決策寫入前端文件，並以 round-trip 測試證明 GUI 對所有宣稱支援的輸入都能無損重新開啟與儲存；不支援的資料有明確且不破壞原檔的處理方式。

## 中優先：可維護性與契約

### [純重構] 拆分最佳化大型模組與求解協調流程

`optimization.py` 同時負責模型指標、正式目標、conditional benchmark、嚴格分階段求解、進度回報、中止保留與同品質候選搜尋。主要大型函式包括 `build_optimization_model()`、`_formal_objective_specs()`、`_discover_preference_benchmarks()`、`solve_lexicographic()` 及其內部 `execute_specs()`。

預計依既有 contract 拆成：

- Optimization model builder：只建立核心變數、硬限制與可重用指標。
- CP-SAT stage runner：只負責單次求解、進度、取消與 solver statistics。
- Lexicographic session：只負責 stage／benchmark 次序、最佳值鎖定與整體狀態。
- Equivalent solution service：只負責正式結果完成後的同品質候選處理。
- 集中的 stage result factory：消除多個建構分支重複填寫欄位。

完成條件：正式 policy 順序、每階段結果、objective vector、最終 assignment、進度事件、取消語意及完整測試結果保持不變；新模組均有單一清楚責任。

### [純重構] 拆分 metrics、獨立 validator、precheck 與 runner 的責任

`recompute_schedule_metrics()`、`validate_schedule_result()`、`run_prechecks()` 與 `run_schedule_file()` 都承擔多種不同工作，閱讀與局部測試成本偏高。

預計處理：

- metrics 依個人、類別／群組、整體與 objective metrics 分段計算，再由單一入口組合。
- validator 依需求覆蓋、資格與互斥、可排性、班次界限、每日模式及 locked objectives 分成獨立 validation passes。
- precheck 依總容量、個人容量、日期／時段角色匹配分成可單獨測試的 checks。
- runner 拆出正式流程協調、正式輸出提交與候選處理協調。

獨立 validator 必須繼續只依 assignment 與正規化輸入重算，不可為了減少重複而讀取 solver 的衍生變數。允許共享的只有正式政策常數、合法班型集合與比例 rounding 等純定義。

完成條件：每個子責任可獨立測試，完整測試與代表性月份結果不變，validator 的獨立性有測試保護。

### [純重構] 收斂 ExecutionPage 的 presentation patch stack

`execution_page.py` 已累積執行前、最佳化進度、中止保留、候選處理、完成與錯誤等多條更新路徑；同一批 label、可見性與捲動狀態由多個函式分別修補，容易再次出現資訊殘留或版面跳動。

預計處理：

- 建立純粹的 `ExecutionPresentation` 映射：由現有 execution snapshot／event 單向產生要顯示的文字、可見性、按鈕狀態及 metric rows。
- renderer 只套用 presentation，不保存新的業務狀態，也不另建第二套 execution state machine。
- 把 log 自動捲動、文字選取與外層頁面定位視為獨立 viewport policy。

完成條件：資料準備、最佳化、已有可行解、驗證、輸出、候選處理、完成、取消、中止保留與失敗皆有 presentation 測試；畫面不重複顯示總耗時或殘留前一 phase 指標。

### [架構重構] 明確化 Excel 與 PDF 的版面契約

PDF exporter 目前依賴 Excel 的固定 sheet 順序／名稱、固定儲存格及求解資訊文字標籤。這符合「PDF 由正式 Excel 月班表產生」的需求，但 Excel 版面微調容易意外破壞 PDF。

預計處理：

- 集中 sheet 名稱、必要區塊、儲存格位置與欄位標籤為 `WorkbookLayoutContract`。
- 為 workbook contract 加入明確版本及機器可讀 metadata；可評估 named ranges 或隱藏 metadata sheet。
- PDF exporter 只依契約定位，不散落硬編碼座標與顯示文字。

完成條件：Excel 版面契約有專門測試；調整非契約樣式不會破壞 PDF，而破壞必要結構時會得到明確錯誤。

### [架構重構] 移除 authoring model 與 parser 的反向匯入

`WeeklyAuthoringDocument.from_dict()` 目前透過函式內匯入呼叫 authoring parser，形成 model／parser 的隱性循環，也讓 domain model 同時承擔反序列化協調責任。

預計處理：

- 將 dict → document factory 留在 parser／codec／application 邊界。
- 若需保留便利 API，應由無循環依賴的 facade 提供，而不是 model 反向匯入 parser。

完成條件：model 模組不匯入 parser，既有正式 JSON 解析、錯誤訊息與 round-trip 測試不變。

### [文件] 對齊規格、README、前端規畫與目前實作

目前已確認的落差包括：

- 《診所排班系統.md》一處仍暗示正職可使用 TARGET，但正式規則與實作已是正職 EXACT／RANGE、兼職可使用 TARGET。
- 前端規畫仍有舊頁面名稱與只描述兩個設定分頁的內容；目前已有「正職不可排」、「兼職時段」及第三個「詳情」設定頁。
- README 仍有部分舊的前端流程／頁面名稱。
- README 仍可能讓人誤解 packaging config 保存版本號；目前正式唯一來源是 `packaging/version.txt`。

完成條件：上述文件都與程式及正式 schema 一致，且不新增另一套規則說法。

## 低優先：日常維護品質

### [純重構] 拆分大型測試模組

`tests/test_optimization.py`、runner 與部分 GUI 測試集中涵蓋多個責任，後續新增案例時不易定位與維護。

預計依 TARGET／PT、conditional preference、比例公平、整數公平、共同公平、進度與取消、同品質候選等責任拆分；同時保留 policy coverage 或測試收集檢查，避免搬移後靜默漏測。

### [純重構] 合併真正同語意的小型基礎功能

目前可評估的重複包括：

- JSON、Excel、PDF 與中間輸入的 temporary file＋replace 流程。
- app config、weekly authoring 與 canonical validation 的部分基本型別解析。

只抽取錯誤語意、生命週期與原子性要求完全相同的部分；不同媒介的驗證與提交規則不得被過度抽象掩蓋。

### [純重構] 清理過時命名與內部用語

目前仍可見 `implemented_objective_prefix_optimal`，以及內部「candidate diagnostic」與使用者介面「候選處理」並存的歷史名稱。

若涉及公開 JSON 欄位或既有 API，需先決定向後相容或版本策略；只處理內部名稱時應同步更新 docstring、測試與 CLI 訊息。

### [可靠性] 保存未預期錯誤的本機診斷資訊

execution worker 對未預期例外主要回傳字串。一般使用者需要簡短訊息，但維護者仍需要可追查的 traceback 與執行識別資訊。

預計加入不含敏感排班內容的本機診斷 log／correlation ID，並明確規定保存位置、輪替與隱私邊界。

### [工程化] 加入基本靜態品質檢查與 CI

目前主要依賴 pytest，尚未建立固定的 formatter／linter、型別檢查與持續整合流程。

預計採最小必要組合；型別檢查優先覆蓋 contracts、models、application service 與 execution protocol。CI 至少執行完整 pytest、靜態檢查及 packaging contract tests；Windows native 封裝 smoke test 可使用獨立、較低頻率工作。

### [發布] 改善依賴重建的可重現性

版本號已集中由 `packaging/version.txt` 管理，不再是待處理問題。目前剩餘風險是部分 dependencies 只限制版本範圍，同一發布版日後重建時可能取得不同套件版本。

預計為正式發布保存 tested constraints／lock 或完整 dependency manifest，同時維持 `pyproject.toml` 作為專案依賴宣告，並驗證 OR-Tools、PySide6、openpyxl、ReportLab 與 PyInstaller 的實際封裝組合。

### [維護] 隔離已知版本相容 workaround

TARGET 絕對偏差包含針對 OR-Tools 9.12 `AddAbsEquality` 的避錯寫法；入口亦包含供 VS Code 直接執行單檔的 bootstrap。這些都有實際用途，不應直接刪除。

預計維持針對性 regression test；升級 OR-Tools 時重新驗證 workaround；將入口／封裝特例限制在 adapter 層，不進入 application service 或 domain core。

## 效能實驗清單

下列項目不是已證實的缺陷，也不得直接改變正式求解政策。每次實驗都必須使用代表性月份，比較完整 objective vector、validation、狀態、時間及可重現性。

### [效能實驗] 建立可比較的 stage profiling 基準

- 保存非敏感問題規模：天數、人數、正兼職數、assignment variables、availability ratio、demand units。
- 保存 hard feasibility、各 benchmark、各正式 stage、首次可行解與完整最佳化時間。
- 先找出真正耗時的 benchmark／stage，再決定優化位置；不要優先微調 JSON、GUI 或已低於毫秒／秒級的前處理。

### [效能實驗] 評估 CP-SAT 多 worker

目前正式求解偏向單 worker。可用同一批月份比較 1、2、4、8 workers 的時間、記憶體與穩定性。多 worker 可能改變同品質 assignment 與重現性，不能只看速度就直接成為正式預設。

### [效能實驗] 評估分階段 solution hints

後續 lexicographic stage 可嘗試以前一階段 assignment 作為 hint。驗收時必須確認 objective vector 與 validation 完全一致，並明確接受或拒絕代表性同品質班表可能改變的影響。

### [效能實驗] 依 profiling 評估延遲建立目標衍生變數

目前目標衍生變數相對核心 assignment model 的增量有限，預期不是第一優先。只有 profiling 證明特定指標建立或搜尋造成顯著成本時，才評估按 stage 延遲建立，避免為小幅收益增加模型生命週期複雜度。

## 不應誤當成技術債的既有設計

- 嚴格 lexicographic optimization 需要多次 CP-SAT 求解與逐層鎖定；這是正式需求，不應為縮短時間任意合併目標。
- 獨立結果 validator 不依賴 solver 衍生狀態，是必要的可信度邊界；重構時必須保留。
- GUI 透過獨立 process 執行排班，可避免 Qt event loop 被 solver 阻塞，方向正確。
- 正式班表完成後才進行同品質候選處理，使候選工作可以獨立停止，方向正確。
- output model 維持媒介無關，Excel／JSON／PDF 邏輯留在 exporters，方向正確。
- 單一檔案目前已採原子寫入；待補的是多媒介輸出組合的交易性，不應重寫已正常運作的單檔機制。
