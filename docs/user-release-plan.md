# 面向一般使用者的發布規畫

> 本文件記錄發布方向；Windows `onedir` 發布層已建立，正式對外版本仍須通過乾淨 Windows 環境驗收。

## 1. 發布目標

將目前的診所排班系統提供給非開發者直接使用。使用者不需要安裝 Python、Conda、虛擬環境或任何 Python 套件，只需準備排班輸入與設定檔，執行程式後取得 JSON、Excel 與 PDF 結果。

## 2. 現階段選擇 Windows 桌面封裝

第一個正式發布版本預計採用 **Windows 桌面封裝**，暫不優先開發 Web App，原因如下：

- 現有流程以本機 `config.json`、`input/` 與 `output/` 檔案操作為主，桌面版本可直接沿用。
- 排班資料可能包含姓名、請假與可排時段等個人資訊；本機運算可避免資料上傳至伺服器。
- OR-Tools CP-SAT 求解主要使用 CPU，讓使用者在本機執行可免除伺服器運算、佇列與維運成本。
- 目前使用情境偏向每月少量執行，不需要先承擔帳號、權限、儲存期限、網路安全與多人同時使用等 Web 系統複雜度。

Web App 仍可作為未來多人共用、集中管理或跨裝置使用時的選項，但不是第一階段發布目標。

## 3. 預計的使用者操作方式

1. 執行 `ClinicShiftSchedulerEditor.exe` 建立、編輯、驗證並儲存 `input/` 內的月份 JSON；進階使用者仍可直接編輯 JSON。
2. 在編輯器右上角「設定」選擇輸入檔並調整執行參數；進階使用者仍可直接編輯根目錄 `config.json`。
3. 執行 `ClinicShiftScheduler.exe`。
4. 在主控台查看排班進度、耗時與錯誤訊息。
5. 從 `output/` 取得正式 JSON、Excel、PDF，以及設定要求的候選班表。

輸入編輯器與排班執行檔共用正式文件契約，但保持獨立；編輯器不載入或呼叫 solver。

## 4. 預計的發布目錄

```text
ClinicShiftScheduler/
├─ ClinicShiftScheduler.exe
├─ ClinicShiftSchedulerEditor.exe
├─ config.json
├─ input/
│  └─ 排班輸入_YYYY-MM.json
├─ output/
├─ runtime/
├─ README.txt
└─ _internal/
   └─ PyInstaller 封裝的 Python、套件與原生程式庫
```

- `config.json`、`input/` 與 `output/` 是使用者會直接操作的項目。
- `runtime/` 是程式管理的中間資料，不應要求使用者手動維護。
- `_internal/` 是應用程式執行所需內容，使用者不應修改。
- `README.txt` 提供最短操作說明、輸入範例、錯誤處理方式與版本資訊。

## 5. 選擇 PyInstaller `onedir` 的理由

第一版預計使用 PyInstaller 的 `onedir` 模式：

- 不要求使用者安裝 Python 或 dependencies。
- 封裝與除錯流程相對直接，適合先建立可靠的 Windows 發布版本。
- 相較 `onefile`，啟動時不需先將全部內容解壓到暫存目錄。
- OR-Tools 的原生程式庫、JSON Schema 與字型等資源較容易檢查及排除遺漏問題。
- 本專案本來就需要外部的設定、輸入與輸出目錄，單一執行檔帶來的便利有限。

若未來有明確需求，可再評估 `onefile`、Nuitka 或安裝程式；不在第一版同時導入多種封裝方式。

## 6. 封裝注意事項

- **frozen 路徑處理**：執行檔不得依賴原始碼目錄位置；需明確區分應用程式內建資源與執行檔旁的使用者資料。
- **OR-Tools 原生依賴**：封裝時需完整收集 CP-SAT 所需的 DLL 與套件資料，並沿用已驗證穩定的 OR-Tools 版本。
- **內建資源**：版本化 JSON Schema 等唯讀資源應包入應用程式，且在 frozen 模式下仍能正確載入。
- **PDF 繁中字型**：發布包應使用可合法散布、結果一致的繁中文字型，不依賴每台電腦剛好安裝相同字型。
- **使用者資料保護**：更新或重新安裝程式時，不得覆蓋使用者修改過的 `config.json`、`input/` 或既有 `output/`。
- **中間與輸出資料**：`runtime/` 與 `output/` 應位於可寫入位置；不可寫入封裝內部的唯讀資源目錄。
- **發布包大小**：Python、OR-Tools、NumPy、Excel 與 PDF 相關套件會使發布包明顯大於原始碼，應以可直接執行與穩定性優先。
- **Windows 安全提示**：正式對外發布時需評估程式碼簽章與安裝程式，降低下載後的安全警告與使用疑慮。

## 7. 基本發布與驗收流程

1. 在乾淨、固定版本的 Windows 建置環境安裝專案正式依賴。
2. 使用受版本控制的 PyInstaller 設定建立 `onedir` 發布包。
3. 確認必要的 OR-Tools DLL、Schema、繁中字型與預設文件均已包含。
4. 在未安裝 Python、Conda 與開發工具的乾淨 Windows 電腦或虛擬機測試。
5. 使用輸入編輯器開啟匿名月份、正式驗證、另存並重開，確認 weekly JSON 語意等價。
6. 使用匿名月份範本完成一次完整排班，確認結果為 `OPTIMAL` 且 validation PASS。
7. 重新開啟並人工抽查 JSON、Excel 與 PDF，確認中文、表格、統計及檔案路徑正常。
8. 測試中文路徑、含空白路徑、既有輸出、錯誤輸入與中途停止等常見情境。
9. 發布前記錄應用程式版本、Schema 版本、依賴版本與驗收結果，再產生 ZIP 或安裝程式。

## 8. 預計支援平台

第一版暫時只考慮並正式驗收 **64 位元 Windows**。Windows 的最低支援版本應在實際封裝與乾淨環境測試後明確定案。

macOS 與 Linux 不能直接沿用 Windows 發布包；若未來需要支援，必須分別建置、處理平台原生依賴並執行完整驗收。Web 版本則待出現集中管理或多人使用的實際需求後再評估。
