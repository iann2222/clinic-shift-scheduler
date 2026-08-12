診所排班系統 {{VERSION}}（Windows 64 位元）

使用方式：
1. 雙擊 ClinicShiftSchedulerEditor.exe，建立或開啟 input 資料夾內的月份資料。
2. 在編輯器完成輸入檢查並儲存 JSON；也可以不使用編輯器，直接修改 JSON。
3. 確認 config.json 的「輸入檔名」與要排班的 input 檔名相同。
4. 雙擊 ClinicShiftScheduler.exe 開始正式排班。
5. 等待主控台顯示正式狀態與輸出路徑。
6. 到 output 資料夾取得 JSON、Excel 與 PDF。

直接雙擊執行時，排班完成或發生錯誤後視窗會保留，閱讀訊息後按 Enter 才會關閉。從 PowerShell 或其他既有終端執行時不會額外等待。

注意事項：
- 整個資料夾必須一起保留，請勿刪除或移動 _internal。
- ClinicShiftSchedulerEditor.exe 只負責輸入、驗證與儲存，不會開始排班。
- input、output 與 config.json 可能含有個人資料，請妥善保管。
- 發布包內的月份資料是匿名範例，可直接用於首次測試。
- 若已有自己的 config、input 或 output，更新版本前請先備份；不要直接以新 ZIP 覆蓋既有資料夾。
- 正式檔案產生後才會開始候選處理；此時可按 Ctrl+C 結束候選處理，不影響正式結果。

發生錯誤時，請保留主控台訊息、使用的 config.json 與匿名化後的輸入資料供維護者檢查。
