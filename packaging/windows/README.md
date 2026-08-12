# Windows 發布層

本目錄負責建立不需安裝 Python 或 Conda 的 Windows 64 位元 portable 發布包，不包含任何排班規則。

## 建置設定

所有發布設定集中在 [`../config_packaging.json`](../config_packaging.json)：

- `application.version`：本次發布版本號，也是資料夾與 ZIP 檔名的一部分。
- `application.name`／`target`／`entry_point`：排班執行檔與目標平台。
- `editor.name`／`entry_point`：無主控台視窗的輸入編輯器執行檔。
- `build`：測試、smoke test、PyInstaller 版本及產物路徑。
- `release_content`：使用者設定、匿名範例與說明文件來源。
- `font`：固定 Noto Sans TC 來源、SHA-256 與輸出字重。

正式建置前先啟用專案 Conda environment，然後在 repository root 執行：

```powershell
.\packaging\windows\build.ps1
```

若環境尚未同步 release dependencies：

```powershell
python -m pip install -e ".[test,release]"
```

## 建置流程與產物

建置器會依序執行完整測試、下載並驗證固定版本字型、建立 Regular／Bold 靜態字重、執行 PyInstaller、加入匿名輸入與使用說明，再分別驗證輸入編輯器 round-trip 與正式排班 smoke test，最後建立：

```text
release/
└─ ClinicShiftScheduler-VERSION-win-x64/
   ├─ ClinicShiftScheduler-VERSION-win-x64.zip
   ├─ ClinicShiftScheduler-VERSION-win-x64.zip.sha256
   └─ ClinicShiftScheduler-VERSION-win-x64.build-manifest.json
```

可執行的 onedir 只存在於被忽略的 `build/release-staging/`，完成 smoke test 與 ZIP 後即刪除；需要檢查時直接解壓 ZIP。ZIP 的 SHA-256 必須放在 ZIP 外，因為把 ZIP 自身的校驗碼加入內容會再次改變 ZIP 的校驗碼。

`build/`、`dist/`、`release/` 與 `runtime/packaging-cache/` 都是本機產物，不得提交 Git。發布包只納入匿名範例，不會複製根目錄 `input/` 或 `output/` 中的真實排班資料。

如需對既有 ZIP 重新執行 smoke test：

```powershell
.\packaging\windows\smoke-test.ps1 -ReleasePath .\release\ClinicShiftScheduler-VERSION-win-x64\ClinicShiftScheduler-VERSION-win-x64.zip
```

smoke test 會把 ZIP 解壓到 `runtime/packaging-smoke/`，移除 Conda、virtual environment 與 Python 的環境提示，並把 `PATH` 限制為 Windows 系統目錄後啟動封裝程式，避免開發環境意外補上漏掉的 DLL。它會先用 `ClinicShiftSchedulerEditor.exe` 開啟匿名輸入、正式驗證、另存並等價重開，再由 `ClinicShiftScheduler.exe` 驗證完整排班。驗證完畢後會刪除整個暫存解壓目錄。

## 驗收重點

最終發布仍需在沒有 Python／Conda 的乾淨 Windows 64 位元環境解壓縮測試。使用者必須能用 `ClinicShiftSchedulerEditor.exe` 維護 `input/`，也能直接修改 JSON；執行 `ClinicShiftScheduler.exe` 後則必須在 `output/` 取得通過驗證的 JSON、Excel 與 PDF。
