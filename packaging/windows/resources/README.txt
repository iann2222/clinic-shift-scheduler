診所排班系統 {{VERSION}}（Windows 64 位元）

使用方式：
1. 修改本資料夾中的 config.json。
2. 將月份排班輸入 JSON 放入 input 資料夾。
3. 雙擊 ClinicShiftScheduler.exe。
4. 等待主控台顯示正式狀態與輸出路徑。
5. 到 output 資料夾取得 JSON、Excel 與 PDF。

注意事項：
- 整個資料夾必須一起保留，請勿刪除或移動 _internal。
- input、output 與 config.json 可能含有個人資料，請妥善保管。
- 發布包內的月份資料是匿名範例，可直接用於首次測試。
- 若已有自己的 config、input 或 output，更新版本前請先備份；不要直接以新 ZIP 覆蓋既有資料夾。
- 正式檔案產生後才會開始候選處理；此時可按 Ctrl+C 結束候選處理，不影響正式結果。

發生錯誤時，請保留主控台訊息、使用的 config.json 與匿名化後的輸入資料供維護者檢查。
