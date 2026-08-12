# Desktop Frontend Implementation Plan

本文件定義診所排班系統第一版 Windows 桌面前端的實作邊界。第一個 GUI milestone 只處理使用者輸入、正式驗證與安全儲存，不呼叫 solver，不顯示排班進度、結果預覽或輸出檔案。

## 1. 目標與第一階段範圍

第一階段要讓一般使用者不必直接編輯 weekly JSON，即可完成：

- 建立一個全新月份。
- 從既有月份複製建立新月份。
- 開啟既有 `weekly-v1` JSON。
- 完整編輯 weekly-v1 正式輸入。
- 編輯並安全儲存 `config.json`。
- 執行即時基本檢查與完整正式 validation。
- 從錯誤清單定位至對應頁面、人員、日期或欄位。
- 原子儲存、另存與重新開啟等價資料。
- 保護尚未儲存的修改。

本階段明確不包含：

- 呼叫 CP-SAT、precheck 或任何最佳化流程。
- 排班進度、候選處理與取消求解。
- 結果預覽、統計、Excel、PDF 或輸出資料夾操作。
- 修改 v1 Schema、排班規則或最佳化順序。

第一階段完成後，可建立第一個 GUI milestone tag。這個 tag 代表輸入編輯器達到可驗收狀態，不代表完整 GUI 已取代既有正式排班入口。

## 2. 技術選型

- UI framework：`PySide6`。
- UI toolkit：Qt Widgets，不使用 QML。
- 支援平台：64-bit Windows。
- UI 建立方式：Python 程式化建立，不以執行期載入 `.ui` 檔為核心。
- 資料表格：優先使用 `QTableView + QAbstractTableModel`。
- 樣式：少量集中式 QSS，不在各 widget 散落 style string。
- 封裝：延續 PyInstaller `onedir`。
- 測試：draft、presenter、application service 以純 Python 單元測試為主；Qt model、navigation 與主要視窗流程補 GUI integration tests。

PySide6 應加入一般 application dependency，並在目前 Windows + Python 3.12 + PyInstaller 環境完成驗證後固定至已測試版本。發布包需包含 Qt／PySide6 的授權與第三方聲明。

## 3. 視覺與互動原則

整體風格是乾淨、簡潔、低彩度的 Windows 行政工具：

- 使用淺灰白背景、低彩度藍色或藍綠色作為主要操作色。
- 不使用動畫、漸層、玻璃效果、大型 dashboard 或不必要圖表。
- 以清楚的標題、表格分組、留白與一致間距建立層次。
- 成功、警告與錯誤除了顏色，也必須使用文字與圖示區分。
- 員工顏色不作為整個輸入 UI 的主要導航機制。
- 字型優先順序為 `Segoe UI`、`Microsoft JhengHei UI`、`Microsoft JhengHei`、sans-serif。
- 支援鍵盤導覽、合理 tab order，避免只能使用滑鼠操作。
- 不以固定像素假設字型與顯示比例，驗收 100%、125%、150% Windows scaling。

## 4. 主視窗資訊架構

主視窗採左側導覽與右側內容區。

必要流程頁面順序：

1. 月份與診所設定
2. 每週人力需求
3. 特定日期調整
4. 員工資料
5. 休假與可排
6. 檢查與儲存

視窗頂部固定顯示：

- 目前月份。
- 目前檔名或完整路徑的精簡顯示。
- 「已儲存」或「尚未儲存」狀態。
- 建立月份、從上月建立、開啟、儲存、另存等文件操作。
- 右上角齒輪設定按鈕。

齒輪開啟獨立設定 dialog。設定畫面區分「一般設定」與「進階設定」；既有候選搜尋、時間上限、候選輸出份數與格式保留在此處，不放進必要流程。第一階段只維護 config，不觸發 solver。

不在第一階段主導覽放置假的「執行排班」或「排班結果」頁。後續階段會在不改寫既有輸入頁的情況下擴充主視窗 navigation model。

## 5. GUI 與 domain 責任分界

正式資料流固定為：

```text
weekly/config document
        ↓
presenter 建立 mutable UI draft
        ↓
widgets / table models 編輯 draft
        ↓
presenter 組回正式 document payload
        ↓
application façade 呼叫正式 parser / validation
        ↓
atomic save
```

責任分界：

- Widgets 只顯示資料、收集操作與呈現錯誤，不接觸 solver。
- Qt table models 管理列欄、editor、disabled cell、排序與變更通知。
- Drafts 是可修改的純 Python UI state，不依賴 PySide6，也不是第二套正式輸入契約。
- Presenters 負責 document 與 draft 的雙向映射、人類可讀標籤、欄位 path 與畫面位置映射。
- `application.py` 提供建立、複製月份、開啟、驗證、儲存與另存的公開 façade；內部可委派輕量 authoring service，避免持續放大單一模組。
- `authoring.py`、`app_config.py` 與既有 typed documents 仍是正式解析與驗證來源。
- GUI 不直接建立 canonical demands，不寫入 `runtime/expanded-input/`。
- GUI 不匯入 CP-SAT、optimizer、metrics 或 exporters。

Draft 不得成為新的 JSON contract。所有成功儲存的資料都必須能通過正式 parser，並由既有 `write_*_document()` 原子寫入。

## 6. Draft 與 presenter 設計

預計建立下列 mutable draft：

- `ScheduleDraft`：月份、角色、週間需求、日期例外、人員、休假與不可排的聚合狀態。
- `EmployeeDraft`：人員基本資料、資格、班次模式、數值與兼職可排時段。
- `WeeklyDemandDraft`：星期集合、營業狀態及動態職務需求。
- `DateOverrideDraft`：日期、營業狀態及當日需求。
- `AvailabilityDraft`：依 employee/date/period 管理休假、不可排或兼職可排狀態。
- `ConfigDraft`：一般與進階執行設定。

Draft 需保留足以做等價 round-trip 的資訊，包括可選欄位是否原本有宣告、notes 與 config 的 `__...__` 說明。Presenter 必須有下列純函式或 service 操作：

- document → draft。
- draft → raw mapping／正式 document。
- `DiagnosticIssue.path` → `FieldLocation`。
- domain enum／key → 中文顯示標籤。
- role rename／delete 的跨 draft 一致性更新。

新員工 ID 使用不含職別語意的穩定 ID，例如 `EMP-` 加隨機唯一值。既有 `FT001`／`PT001` 等 ID 原樣保留。變更姓名、職別或 A/B/PT 類別都不得改變 employee ID。

## 7. 各頁功能

### 7.1 月份與診所設定

- 顯示起訖日期，建立月份時固定為該月第一天至最後一天。
- 編輯假日清單；假日屬日期綁定資料。
- 顯示固定三時段：早上、下午、晚上，不允許改名、增加或刪除。
- 管理動態職務清單。
- 顯示 authoring/schema version，但不讓一般使用者任意修改。

目前 weekly-v1 Schema 正式支援動態 `roles`，因此 GUI 可新增、改名與刪除職務。這些操作必須由 presenter/application transaction 同步處理：

- 週間需求與日期例外的 role counts。
- 每位員工的職務資格。
- 兼職 available slot 的角色限制。

刪除或改名時先顯示影響範圍並要求確認。刪除仍被使用的職務時，不允許留下懸空參照或缺漏 demand 欄位。

### 7.2 每週人力需求

- 以平日、星期六、星期日為主要使用者視圖。
- 每種日期類型提供營業開關。
- 開診時顯示早／午／晚及所有動態職務的人數。
- 休診時需求格 disabled，正式資料不寫入 staffing。
- 數量只接受非負整數，0 與缺漏不可混淆。

Presenter 將這個三類視圖映射為涵蓋 monday 至 sunday 的正式 `weekly_demands`。若開啟的既有文件使用更細的星期分組且無法無損折疊為三類，GUI 必須保留其分組或切換到進階星期視圖，不能靜默改寫語意。

### 7.3 特定日期調整

- 顯示 override 清單，可新增、複製與刪除。
- 日期必須位於目前月份且不可重複。
- 可指定該日休診，或指定完整早午晚與職務需求。
- 顯示原本週間模板值，方便使用者建立差異，但正式 override 仍保存完整 staffing。

### 7.4 員工資料

- 使用 `QTableView` 顯示姓名、正職／兼職、A/B 類、職務資格、公平分組、班次模式與班次數摘要。
- 詳細 editor 顯示備註、min/max/target 等條件欄位。
- 畫面中文標籤：固定班次、班次範圍、目標班次、公平分組。
- EXACT 只啟用固定班次；RANGE 啟用 min/max；TARGET 啟用 target 與可選硬性 min/max。
- 兼職不可選 TARGET；正職必須選 A 或 B；不合法組合在 draft 層立即提示，正式 validation 仍為最終依據。
- 員工刪除前提示將一併移除其休假、不可排與可排資料。

### 7.5 休假與可排

- 先選人員，再以當月日期 × 早午晚矩陣編輯。
- 正職預設可排：可標記整日請假、單時段請假／不可排。
- 兼職預設不可排：只勾選明確 available slots，並可限制該時段角色。
- leave/unavailable 在畫面上必須優先於 available，不能呈現互相矛盾的有效狀態。
- 整日請假使用明確狀態，不以三個獨立時段勾選偷偷推導。
- 可使用人員、日期與狀態篩選，但資料排序不得改變 employee ID 參照。

### 7.6 檢查與儲存

- 顯示尚未完成的基本欄位問題。
- 執行完整 weekly parser、canonical normalization 與 INPUT_INVALID validation。
- 依 severity、頁面、人員或日期顯示錯誤清單。
- 點擊錯誤後切換頁面、選取對應 entity 並聚焦欄位。
- 驗證失敗不清除 draft、不覆寫檔案，也不把狀態標記為 clean。
- 驗證通過後提供儲存與另存；成功才顯示 clean。

本階段的「完整 validation」不包含 precheck 或 CP-SAT feasibility，因為第一階段明確不呼叫 solver。畫面必須使用「輸入資料檢查通過」而不是「班表一定可排」等誤導文字。

## 8. Validation UX 與錯誤定位

驗證分兩層：

1. Draft 基礎檢查：必填、型別、數字範圍、disabled field、日期是否落在月份等立即可判斷問題。
2. 正式 validation：由 application façade 組回正式 document，呼叫既有 parser 與 canonical validation。

正式 `DiagnosticIssue` 必須保留 code、path、phase、severity 與 details。Presenter 使用獨立 `FieldLocation`，至少包含：

- page ID。
- entity ID（employee ID、date 或 weekly group）。
- field key／table cell。
- 可供一般使用者閱讀的訊息。

無法精確定位的 cross-field 問題仍顯示在檢查頁，並導向最相關頁面。中文訊息由集中 catalog 按 issue code 翻譯；未知 code 使用正式 message fallback，不能吞掉錯誤。

## 9. 從上個月建立新月份

月份複製是 application／authoring 層的正式操作，不由 GUI 複製 JSON。

輸入為來源 document 與目標年月，輸出為尚未儲存的新 draft/document。複製規則：

保留：

- `authoring_version`、`schema_version` 與固定 periods。
- 動態 roles。
- weekly demands 模板。
- 員工、employee ID、姓名、A/B/PT 類別、資格與 fairness group。
- shift mode、required/target/min/max 與 notes；這些值先沿用，並在檢查頁提醒使用者確認新月份工作量。
- 可沿用的 config 設定；輸入檔名改為新月份預設檔名。

重建或清除：

- period 改為目標月第一日至最後一日。
- holidays 清空。
- date overrides 清空。
- leave requests 清空。
- unavailable slots 清空。
- 所有 PT available slots 清空，但保留 PT 本人的職務資格與班次模式資料。
- 所有其他帶有舊月份日期的資料均不得複製。

目標月份與來源月份相同時拒絕建立。建立後狀態為 unsaved，使用者必須檢查班次數與 PT 可排時段，通過 validation 後才可儲存。

## 10. 未儲存狀態

Document 與 config 分別追蹤 dirty state，主視窗彙整顯示：

- 已儲存。
- 尚未儲存。
- 尚未建立檔案。

下列操作若有未儲存修改，必須顯示「儲存／放棄／取消」：

- 開啟其他檔案。
- 建立新月份或從上月建立。
- 關閉主視窗。
- 重新載入目前檔案。

儲存失敗或 validation failed 時留在原 draft，dirty state 不變。只有 atomic replace 成功後，才更新 current path、clean snapshot 與視窗狀態。

Dirty 判定以 draft 的穩定 normalized snapshot 或明確 command tracking 為準，不依賴 widget 是否曾收到 edit signal，避免改回原值後仍永久顯示 dirty。

## 11. 檔案開啟與儲存策略

- 預設從 application root 的 `input/` 開啟與儲存 monthly weekly JSON。
- 可讀取其他位置的 JSON 作為匯入來源，但要成為正式執行輸入時，另存至 `input/` 並同步 config 的輸入檔名。
- 建立月份的預設檔名為 `排班輸入_YYYY-MM.json`。
- 不允許以 GUI 寫入 `runtime/expanded-input/`。
- 開啟時先完整解析至 typed document，成功後才替換目前 draft。
- 儲存時由 draft 組回正式 document，正式驗證成功後使用現有原子寫入。
- 另存不得在失敗時改變目前路徑或 clean state。
- 覆寫既有檔案前顯示確認；原子 replace 只處理已明確確認的 target。
- config 的 `__...__` 說明與預設設定區必須 round-trip 保留。

## 12. Application façade

第一階段預計在輕量 application boundary 提供：

- `create_month(year, month, roles/default template)`。
- `create_month_from_previous(source, year, month)`。
- `open_authoring_document(path)`。
- `validate_authoring_draft(draft)`。
- `save_authoring_draft(path, draft, overwrite)`。
- `save_authoring_draft_as(path, draft)`。
- config 對應的 open／validate／save。

公開 façade 放在或由 `application.py` 匯出；具體 authoring 操作可放在獨立輕量 service，避免 `application.py` 與既有排班 orchestration 繼續膨脹。所有介面不得匯入 OR-Tools 或 exporters。

## 13. 預計檔案結構

```text
src/
├─ run_gui.py
└─ clinic_shift_scheduler/
   ├─ application.py                 # 公開 input application façade
   ├─ authoring_application.py       # 建立、複製、驗證、儲存實作
   └─ gui/
      ├─ __init__.py
      ├─ main.py
      ├─ main_window.py
      ├─ navigation.py
      ├─ dialogs/
      │  ├─ settings_dialog.py
      │  └─ unsaved_changes_dialog.py
      ├─ drafts/
      │  ├─ schedule_draft.py
      │  ├─ employee_draft.py
      │  ├─ availability_draft.py
      │  └─ config_draft.py
      ├─ presenters/
      │  ├─ schedule_presenter.py
      │  ├─ config_presenter.py
      │  ├─ validation_presenter.py
      │  └─ field_location.py
      ├─ models/
      │  ├─ weekly_demand_table_model.py
      │  ├─ date_override_table_model.py
      │  ├─ employee_table_model.py
      │  └─ availability_table_model.py
      ├─ pages/
      │  ├─ month_clinic_page.py
      │  ├─ weekly_demand_page.py
      │  ├─ date_override_page.py
      │  ├─ employee_page.py
      │  ├─ availability_page.py
      │  └─ review_save_page.py
      ├─ widgets/
      │  ├─ navigation_sidebar.py
      │  ├─ document_header.py
      │  ├─ validation_list.py
      │  └─ role_selector.py
      ├─ styles/
      │  ├─ palette.py
      │  └─ application.qss
      └─ resources/
         └─ icons/

tests/
├─ test_authoring_application.py
├─ test_gui_drafts.py
├─ test_gui_presenters.py
├─ test_gui_table_models.py
├─ test_gui_validation_navigation.py
└─ test_gui_document_lifecycle.py

packaging/windows/
├─ ClinicShiftSchedulerEditor.spec
└─ smoke-test-gui.ps1
```

實作時可依責任合併過小檔案，但不得把 document mapping、validation translation 或檔案 I/O 塞回 widgets。

## 14. Windows、High DPI 與封裝注意事項

- Qt 6 使用 device-independent pixels；避免依賴硬編碼尺寸與螢幕解析度。
- 在 100%、125%、150% scaling 驗證主視窗、table editor、dialog 與錯誤提示。
- 最小視窗尺寸應可在常見筆電解析度使用，表格超出時使用 scroll，不截斷主要操作。
- 圖示使用可封裝資源並提供文字 tooltip，不使用 emoji 作核心 icon。
- 第一階段新增獨立 GUI entry point；GUI executable 使用 windowed mode，不開 console。
- 第一階段 GUI 尚不能執行排班，因此不取代既有正式 `ClinicShiftScheduler.exe`。過渡發布若要同時提供，GUI 使用清楚的 editor 名稱；後續接入完整流程後再決定主 executable 命名。
- PyInstaller spec 明確收集 PySide6 所需 Qt plugins、styles、platforms 與 icon resources。
- 既有 OR-Tools、Schema、PDF 字型與 user data 路徑仍須保持可用；GUI spec 不得破壞現有 console release。
- frozen 模式使用 `application_root()` 尋找外部 `config.json`、`input/`，不可把使用者檔案寫入 `_internal/`。
- 發布包保留 PySide6／Qt 及其他第三方授權聲明。

## 15. 測試策略

- Draft／presenter／月份複製使用不啟動 Qt 的純 Python 測試。
- Table model 測試 row/column、flags、data、setData、disabled cells 與 change signals。
- Navigation 測試 issue path 對應頁面與欄位。
- Lifecycle 測試開啟、dirty、save、save as、discard、cancel 與 close。
- Atomic save failure 測試原檔保留、draft 保留、clean state 不變。
- Round-trip 比較 `document.to_dict()` 的語意等價，不依賴 JSON whitespace 或 key order。
- 既有完整 175 項測試持續執行，確保 GUI dependency 與 façade 不改變 solver／output。
- Windows onedir smoke test 至少啟動 GUI、開啟匿名 weekly JSON、驗證、另存、關閉並以重新開啟確認等價。

## 16. 第一個 GUI Milestone 驗收標準

功能驗收：

- 可建立指定年月的 weekly-v1 document。
- 可從上月建立，保留穩定資料並清除所有日期綁定資料。
- 可開啟既有 weekly-v1 JSON。
- 可完整編輯目前正式 Schema 支援的輸入欄位。
- 可新增、改名、刪除動態職務且所有參照保持一致。
- 新員工取得唯一穩定 ID；改姓名不改 ID。
- 正職與兼職可排語意在 UI 正確分流。
- 可執行完整輸入 validation 並一次顯示多項錯誤。
- 可由錯誤清單定位至對應頁面與 entity；可定位欄位的錯誤必須聚焦欄位。
- Validation failed 不丟失 draft。
- 可原子儲存與另存；失敗不破壞既有檔案。
- 新建、開啟、切換與關閉時能保護未儲存修改。
- 儲存後重新開啟，weekly document 與 config 語意等價。

架構驗收：

- GUI modules 不匯入 OR-Tools、optimizer、metrics 或 exporters。
- Widgets 不直接讀寫 JSON，也不持有分散修改的正式 frozen document。
- 文件操作均經 presenter 與 application façade。
- GUI import boundary 測試不載入 OR-Tools、openpyxl 或 ReportLab。

視覺與平台驗收：

- Windows 64-bit 的 100%、125%、150% scaling 可正常使用。
- 主流程不出現尚未實作的 solver／結果功能干擾。
- 鍵盤可完成主要欄位移動、表格編輯、驗證與儲存。
- PyInstaller `onedir` GUI smoke test 通過。
- 既有 console 排班入口與完整測試仍通過。

## 17. 後續延展

第二階段可直接在既有主視窗加入「執行排班」流程，透過 `ScheduleApplicationRequest`、typed progress events 與 background worker 呼叫 application service；第三階段再加入結果摘要與開啟輸出功能。既有輸入 drafts、presenters、pages 與文件 lifecycle 不需重寫。

## 18. 實作進度

目前輸入編輯器已完成文件生命週期，以及月份、每週需求、特定日期、員工、休假與
可排、正式驗證與儲存頁面的主要功能。Validation 問題可定位到對應員工、需求格或
日期時段；休假與可排頁提供星期／狀態篩選及安全批次設定，文件操作亦提供標準鍵盤
快捷鍵。第一個 milestone 剩餘工作以 Windows 實機 High DPI 操作檢查與獨立 GUI
`onedir` smoke test 為主；solver 執行按鈕、背景工作與結果顯示仍明確保留在後續階段。
