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
- 數值輸入框只包含可編輯的純數字，`節`、`份`、`秒`、`年`、`月`等單位以相鄰文字呈現；可選小數只顯示有效位數，不保留無意義的尾端零。
- 不以固定像素假設字型與顯示比例，驗收 100%、125%、150% Windows scaling。

## 4. 主視窗資訊架構

主視窗採左側導覽與右側內容區。

必要流程頁面順序：

1. 月份與診所設定
2. 每週人力需求
3. 特殊日期設定
4. 員工資料
5. 正職不可排
6. 兼職可排
7. 檢查與儲存

視窗頂部固定顯示：

- 目前月份。
- 目前檔名或完整路徑的精簡顯示。
- 「已儲存」或「尚未儲存」狀態。
- 儲存、另存等目前文件操作。
- 文件資訊旁的儲存、另存與儲存狀態。
- 與文件操作分隔、固定在右上角的設定按鈕。

「建立新月份／從上月建立／開啟既有月份」屬於流程入口，集中放在「月份與診所設定」頁最上方，以用途說明形成清楚的起始導覽，不與儲存及設定混在同一排工具列。鍵盤快捷鍵仍可保留。

齒輪開啟獨立設定 dialog。設定畫面區分「一般設定」與「候選班表設定」；既有候選搜尋、時間上限、候選輸出份數與格式保留在後者，不放進必要流程。比例與固定秒數兩種時間模式只顯示當下適用的欄位；停用候選處理時整區設定以 disabled 樣式呈現，但必須保留原有值。第一階段只維護 config，不觸發 solver。

按鈕、數字欄位與選項元件取得焦點時可顯示清楚提示；使用者點擊無關的畫面空白或說明區域後，應清除殘留焦點與文字選取，避免視覺上誤以為操作仍被選中。

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
- 可排資料仍由 `ScheduleDraft` 依 employee/date/period 管理正式的請假、不可排或兼職可排狀態；GUI 只提供較簡單的正職／兼職分流視圖。
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

- 頁面最上方提供建立新月份、從上月建立、開啟既有月份三個入口；建立月份預設為本機日期的下一個月。
- 顯示起訖日期，建立月份時固定為該月第一天至最後一天。
- 假日清單移至「特殊日期設定」集中顯示；假日屬日期綁定資料，只供假日班次統計與公平性使用，不會自動代表休診，也不由 v1 自行推定國定假日。
- 顯示固定三時段：早上、下午、晚上，不允許改名、增加或刪除。
- 顯示層不提供職務增刪或改名；第一版前端將正式文件既有職務視為固定設定。
- 顯示 authoring/schema version，但不讓一般使用者任意修改。

目前 weekly-v1 Schema 仍正式支援動態 `roles`，但第一版 GUI 不開放修改，以免一般使用者意外造成跨頁結構變更。開啟文件後仍依其正式 roles 顯示下列內容：

- 週間需求與日期例外的 role counts。
- 每位員工的職務。
- 兼職 available slot 的角色限制。

所有完整日期選擇共用月份限定的 `QCalendarWidget` 封裝：隱藏週次與原生 navigation bar，以「年份→月份」顯示目前月份；不得切換到前後月份，前後月補位日期使用灰底且不可選，所選日期使用實心高對比底色及邊框並在 dialog 下方再次顯示。

### 7.2 每週人力需求

- 以平日、星期六、星期日為主要使用者視圖。
- 每種日期類型的早／午／晚各自提供時段開關，新月份預設全部開啟。
- 開啟時顯示所有動態職務的人數，新月份預設各職務 1 人。
- 關閉單一時段時，該時段所有職務需求轉為 0；三個時段均關閉時才正式寫為整日休診。
- 一般使用者單擊需求格，使數量在 1、2、3 間循環；正式資料仍維持明確整數與 0／缺漏區分。

Presenter 將這個三類視圖映射為涵蓋 monday 至 sunday 的正式 `weekly_demands`。若開啟的既有文件使用更細的星期分組且無法無損折疊為三類，GUI 必須保留其分組或切換到進階星期視圖，不能靜默改寫語意。

### 7.3 特殊日期設定

- 頁面分為主要的「特定日期」與次要的「假日標記」兩區；主畫面只保留必要規則說明，完整 domain 細節留在 tooltip 與規格文件。
- 假日標記區暫時以較小的灰色凍結區顯示輸入既有資料，第一版前端不提供修改；建立空白月份時不自行下載或推定假日。
- 顯示 override 清單，可新增、複製與刪除。
- 日期必須位於目前月份且不可重複。
- 每個日期的早／午／晚可各自設為「開啟／休診」，人數欄以單擊在 1、2、3 間循環，呈現與每週需求一致。
- 顯示原本週間模板值，方便使用者建立差異，但正式 override 仍保存完整 staffing。

### 7.4 員工資料

- 使用 `QTableView` 顯示姓名、正職／兼職、A/B 類、職務、班次模式與班次數摘要。
- 表格下方只顯示所選員工的唯讀詳細摘要，並以留白和獨立區塊與清單分隔。
- 「新增員工」及摘要標題旁的「編輯」皆開啟 modal editor；只有按下儲存才將暫存值套回 draft，取消不得留下半成品。
- 刪除員工只放在既有員工的編輯 dialog 內，不作為清單頁的平行主要操作。
- 畫面中文標籤：固定班次、班次範圍、目標班次。`fairness_group` 仍由正式資料保存，但不顯示給一般使用者；新員工或切換 A/B/PT 類別時由 GUI 配置安全預設值。
- EXACT 只顯示固定班次；RANGE 只顯示必填的最低／最高班次；TARGET 顯示目標班次及可勾選啟用的硬性最低／最高班次。非目前模式的條件列直接隱藏，不以停用欄位干擾使用者。
- 兼職不可選 TARGET；正職必須選 A 或 B；不合法組合在 draft 層立即提示，正式 validation 仍為最終依據。
- 員工刪除前提示將一併移除其休假、不可排與可排資料。

### 7.5 正職不可排

- 所有正職在同一張 `QTableView`，每位員工一列，只顯示姓名與不可排日期／時段清單。
- 雙擊任一員工開啟當月日號 dialog；年份與月份已由文件決定，不要求重複輸入。
- Dialog 分別輸入早、午、晚日號，可表達整日或單時段不可排。既有 `leave_requests` 與 `unavailable_slots` 在畫面上合併為一般人理解的「不可排」，正式儲存仍使用既有 Schema。
- 未變更的整日請假及備註應保留；正式 leave/unavailable 優先規則不變。

### 7.6 兼職可排

- 所有兼職在同一張 `QTableView`，每位員工一列，只顯示姓名與明確可排日期／時段清單。
- 雙擊後以相同日號 dialog 分別輸入早、午、晚可排日期；空白表示該時段沒有明確可排日期。
- GUI 編輯既有日期清單時，保留仍存在時段的職務限制；新增時段預設適用該員工全部職務。
- 兼職預設不可排與 `available_slots` 唯一允許集合的正式語意不變。

### 7.7 檢查與儲存

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
- 所有 PT available slots 清空，但保留 PT 本人的職務與班次模式資料。
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
      │  ├─ availability_table_model.py
      │  └─ availability_summary_table_model.py
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
- 執行頁能持續顯示目前階段與耗時，長時間求解時主視窗不凍結。
- 執行前固定使用目前已驗證並儲存的月份；GUI 不以 `config.json` 中其他檔名取代目前文件。
- 取消排班可合作式停止 CP-SAT；正式輸出完成後取消候選處理不得刪除既有結果。
- 鍵盤可完成主要欄位移動、表格編輯、驗證與儲存。
- PyInstaller `onedir` GUI smoke test 通過。
- 既有 console 排班入口與完整測試仍通過。

## 17. 後續延展

第二階段已在既有主視窗加入「執行排班」流程。Editor 透過 `QProcess` 啟動獨立 Scheduler worker，以版本化 JSON-lines 傳遞 typed progress、完成結果與結構化錯誤；GUI 不直接匯入 solver 或 exporters。執行頁顯示目前月份、階段、耗時、訊息、正式狀態、validation 與輸出路徑，並可取消及開啟輸出資料夾。既有命令列入口維持獨立可用。

後續若擴充結果預覽，應讀取已落盤的正式 result model，不得在 GUI 重算排班規則或統計。

## 18. 實作進度

目前輸入編輯器已完成文件生命週期，以及月份、每週需求、特定日期、員工、正職不可排、
兼職可排、正式驗證與儲存頁面的主要功能。Validation 問題可定位到對應員工、需求格或
日期清單；正職與兼職頁皆以所有同類員工一覽及當月日號 dialog 編輯，文件操作亦提供標準鍵盤
快捷鍵。月份建立入口已集中於首個流程頁，完整日期選擇共用月份限定日曆；員工頁採唯讀摘要
搭配新增／編輯 dialog。右上角設定頁已接入正式 `config.json` 契約，可編輯輸入檔、執行顯示與候選
處理參數，並保留說明欄位及參考預設值後原子儲存。獨立 GUI `onedir` 與自動 smoke
test 已完成。第二個 milestone 另完成獨立 worker、執行進度、合作式取消、正式結果摘要與輸出資料夾入口；
執行頁已將正式排班的「終止排班」與正式輸出後的「終止候選處理」分開，
後者不會降級或刪除已完成班表。剩餘工作以 Windows 實機 High DPI、封裝後 GUI 啟動
worker 與人工操作檢查為主。
