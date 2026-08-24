# Desktop Frontend Plan

本文件記錄診所排班系統 Windows 桌面前端目前的產品範圍、架構邊界與交付前仍需完成的工作。早期 milestone 的逐項開發紀錄不再保留；正式排班規則、資料契約與最佳化順序仍以排班規格文件為準。

## 1. 產品目標與目前狀態

桌面前端的目標是讓一般使用者不必直接編輯 JSON 或操作 Python 環境，也能完成一次排班。現行主要流程已接通：

```text
建立／開啟月份
→ 編輯月份需求與員工條件
→ 檢查並安全儲存
→ 執行排班
→ 查看進度與終止控制
→ 確認正式狀態及驗證結果
→ 取得 JSON、Excel、PDF 與候選班表
```

目前前端已具備：

- 建立新月份、從上月建立及開啟既有 `weekly-v1` JSON。
- 編輯每週需求、特殊日期、員工、正職不可排及兼職可排資料。
- 編輯並原子儲存 `config.json`。
- 正式輸入 validation、錯誤定位、儲存／另存與未儲存變更保護。
- 以獨立背景程序執行完整排班，顯示階段、訊息與耗時。
- 分開處理「終止排班」與正式輸出後的「終止候選處理」。
- 顯示正式狀態、獨立驗證結果與 JSON、Excel、PDF 路徑，並可開啟輸出資料夾。

GUI 不取代命令列入口；不使用前端時，仍可直接編輯 JSON／config 並獨立執行排班。

## 2. 技術與視覺原則

- 技術：Python 3.12、PySide6、Qt Widgets。
- 平台：第一版只支援 Windows 64-bit。
- UI：Python 程式化建立，搭配少量集中式 QSS。
- 表格：使用 `QTableView + QAbstractTableModel`，不以 `QTableWidget` 保存 domain state。
- 封裝：PyInstaller `onedir`，發布時提供 ZIP。
- 風格：乾淨、低彩度、清楚的 Windows 行政工具；不使用動畫、漸層、玻璃效果或大型 dashboard。
- 可讀性：文字不能只靠顏色表意，並需在 Windows 100%、125%、150% 顯示縮放下驗收。
- 輸入：數值欄只保存純數字，單位顯示在欄位外；不顯示無意義的小數尾零。

## 3. 資訊架構

主視窗採左側流程導覽與右側內容區，依序包含：

1. 月份與診所設定
2. 每週人力需求
3. 特殊日期設定
4. 員工資料
5. 正職不可排
6. 兼職可排
7. 檢查與儲存
8. 執行排班

文件標頭顯示目前月份、檔案、儲存狀態及儲存操作；設定按鈕獨立置於右上角。建立、從上月建立及開啟月份集中在第一頁，不與日常儲存操作混在一起。

設定 dialog 分為「一般設定」與「候選班表設定」。候選處理停用時保留原設定值，但以 disabled 樣式呈現；固定時間與排班時間比例只顯示目前模式需要的欄位。

## 4. GUI 與後端責任分界

輸入資料固定經過以下流程：

```text
正式 weekly/config document
→ mutable UI draft
→ Qt widgets / table models
→ presenter 組回正式資料
→ authoring/config application service
→ 正式 parser 與 validation
→ atomic save
```

責任原則：

- Widgets 只呈現狀態及收集操作，不直接讀寫 JSON。
- Draft 是可修改的 UI state，不是第二套資料契約。
- Presenter 負責正式 document 與 draft 的雙向映射，以及 domain path 與畫面位置的對應。
- Authoring／config application service 負責建立月份、開啟、驗證、儲存與另存。
- 正式 parser、Schema 與 typed document 是唯一資料真相來源。
- GUI 不自行展開逐日 demands，不重算排班規則、統計或最佳化結果。
- GUI 程序不直接載入 CP-SAT、optimizer 或 exporters。

執行排班時，GUI 使用 `QProcess` 啟動獨立 worker，透過版本化 JSON-lines 協定接收進度、診斷及完成結果。worker 可在沒有 GUI 的情況下獨立運作，因此後續演算法調整不應要求重寫 widgets。

## 5. 輸入與文件生命週期

### 月份與需求

- 新月份預設為本機日期的下一個月。
- 固定使用早上、下午、晚上三個時段。
- 每週需求以平日、星期六、星期日呈現，每個時段可獨立開診或休診。
- 特定日期只有在需求與週間模板不同時才新增。
- 假日標記只影響統計與公平性，不自動代表休診；目前前端只顯示、不提供修改。
- 職務由正式文件提供，第一版 GUI 不開放增刪或改名。

### 員工與可排條件

- `employee_id` 由系統建立並永久保留，改姓名不得改 ID。
- 員工資料以摘要清單配合新增／編輯 dialog 操作。
- 班次模式顯示為固定班次、班次範圍、目標班次，且只顯示該模式適用欄位。
- 正職預設可排，前端只編輯不可排日期與時段。
- 兼職預設不可排，前端只編輯明確可排日期與時段。
- `fairness_group` 由正式資料保留，但不顯示給一般使用者。

### 從上月建立

保留員工、employee ID、類別、職務、班次模式與每週需求模板；改為新月份的起訖日期，並清除假日、特殊日期、休假、不可排與兼職可排等日期綁定資料。新文件一律標記為尚未儲存，班次數及兼職可排時段需重新確認。

### 儲存安全

- 開啟新檔、建立月份及關閉視窗前處理未儲存變更。
- Validation 失敗或寫檔失敗不得清除 draft。
- 只有 atomic save 成功後才能標記為已儲存。
- 預設月份檔名為 `排班輸入_YYYY-MM.json`。
- GUI 不寫入 `runtime/expanded-input/`；該資料夾只由正式排班流程產生。
- 儲存後重新開啟必須與原 draft 語意等價，config 的 `__...__` 說明欄亦須保留。

## 6. 檢查、執行與結果

### 輸入檢查

「檢查與儲存」執行正式 weekly parser、normalization 與 `INPUT_INVALID` validation。問題保留 code、path、phase、severity 與 details，已知問題可定位至相關頁面、員工、日期或需求格。

輸入檢查通過只代表資料格式與明訂條件有效，不保證整月一定可排。容量、匹配與求解可行性由執行排班時的 precheck 與 solver 判定。

### 執行排班

- 執行前驗證並儲存目前文件，且明確顯示載入的 config 與輸入檔。
- 正式求解期間可「終止排班」並放棄結果；找到合法班表後，可改用「終止排班並保留當前最佳班表」。後者須通過獨立驗證，另存為明確標示未完成最佳化的 `FEASIBLE` 暫存結果，不得冒充正式 `OPTIMAL` 班表。
- 暫存結果的 JSON／Excel／PDF 格式由一般設定控制；若目標檔案不可寫，保留按鈕不得中止 solver。
- 進入 validation、輸出或候選處理後停用保留功能；候選處理仍只開放「終止候選處理」。
- 正式輸出完成後再終止候選處理，不得刪除或降級正式結果。
- 執行狀態固定於內容上方；執行訊息與頁面內容具有各自獨立的捲動區域。
- 排班進行中隱藏正式結果並讓訊息區使用剩餘高度；完成後顯示正式結果並自動定位。
- JSON、Excel、PDF 必須分別顯示；缺少任何預期媒介時明確標示「未產生」。

### 獨立驗證

獨立驗證由後端根據最終 assignment 與正規化輸入重新計算硬性規則、每日模式、統計及鎖定目標，不依賴 CP-SAT 內部衍生變數。只有正式狀態符合要求且驗證為 `PASS`，才可輸出正式班表；驗證失敗時不得將結果標示為可使用。

## 7. 主要程式邊界

```text
src/clinic_shift_scheduler/
├─ authoring_application.py      # 月份文件建立、開啟、驗證與儲存
├─ config_application.py         # config 文件生命週期
├─ application.py                # 完整排班 application service
├─ execution_protocol.py         # GUI/worker JSON-lines 協定
├─ execution_worker.py           # 無介面的背景排班入口
└─ gui/
   ├─ main.py / main_window.py
   ├─ execution_controller.py    # QProcess 生命週期與合作式終止
   ├─ drafts/                    # mutable UI state
   ├─ presenters/                # document/draft 映射
   ├─ models/                    # Qt table models
   ├─ pages/                     # 八個流程頁
   ├─ dialogs/ / widgets/
   └─ styles/                    # palette 與集中式 QSS
```

新增功能時不得把 JSON I/O、排班計算或輸出媒介邏輯塞進 page/widget；執行協定新增欄位時須維持版本檢查並補 decoder 測試。

## 8. 測試與發布驗收

自動測試至少涵蓋：

- document/draft round-trip、月份複製及 config 語意等價。
- table model flags、編輯、disabled cell 與 change signals。
- validation path 到頁面、entity 與欄位的定位。
- 開啟、dirty、save、save as、discard、cancel 與 close。
- worker 協定、長時間進度、正式取消、候選終止及輸出保留。
- 正式結果狀態、獨立驗證與 JSON、Excel、PDF 路徑呈現。
- GUI import boundary 不載入 OR-Tools、openpyxl 或 ReportLab。
- 既有 solver、validator、exporter 與 console 完整回歸。

Windows 發布前仍須完成：

- 在乾淨 Windows 64-bit 環境解壓縮 onedir ZIP，且不依賴 Python／Conda。
- GUI 啟動 worker 並完成一份匿名月份的完整排班。
- OR-Tools native dependencies、Excel、PDF 與繁中字型正常。
- 100%、125%、150% High DPI 下主視窗、表格、dialog 與捲動可用。
- 長時間排班時 GUI 保持回應，終止與關閉流程沒有殘留 worker。

## 9. 交付前尚待補齊

以下是目前仍具產品層級價值的工作，依優先順序排列：

1. **結構化執行失敗診斷**：將 `PRECHECK_INFEASIBLE`、`INFEASIBLE`、`UNKNOWN`、`VALIDATION_FAILED` 等狀態轉為清楚中文摘要，並盡量由問題清單跳回相關需求、員工或可排頁面。執行失敗不得清除使用者資料。
2. **結果快速入口**：完成後提供直接開啟 PDF、Excel 及候選班表資料夾的操作；JSON 保留為機器可讀結果，不必作為主要入口。
3. **人工操作驗收**：確認失敗後修正再執行、重複執行與覆寫、終止後按鈕恢復、完成後修改輸入及舊結果標示等流程。
4. **正式封裝驗收**：重新建置包含最新 GUI 的發布包，執行乾淨 Windows／High DPI／長時間排班 smoke test。

後續若新增結果預覽，必須讀取已落盤的正式 result model，不得在 GUI 重新計算排班規則或統計。
