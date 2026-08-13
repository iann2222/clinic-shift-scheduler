診所排班系統（Windows 64 位元）
版本：{{VERSION}}

執行方式一：完整 UI（一般使用者首選）
1. 雙擊 clinic-shift-scheduler.exe。
2. 建立或開啟 input 資料夾內的月份資料，完成輸入檢查並儲存。
3. 按右上角「設定」調整執行與候選設定。
4. 到「執行排班」頁執行目前月份，並在畫面查看進度、耗時與輸出路徑。
5. 到 output 資料夾取得 JSON、Excel 與 PDF。

執行方式二：quick-runner.exe（熟悉檔案設定者）
1. 直接編輯 config.json，以及 config 指定之 input 資料夾內的月份 JSON。
2. 雙擊 quick-runner.exe；程式會依設定完成輸入檢查、求解與正式輸出。
3. 在主控台查看進度與錯誤，完成後到 output 資料夾取得結果。

直接雙擊執行時，排班完成或發生錯誤後視窗會保留，閱讀訊息後按 Enter 才會關閉。從 PowerShell 或其他既有終端執行時不會額外等待。

注意事項：
- 整個資料夾必須一起保留，請勿刪除或移動 _internal。
- clinic-shift-scheduler.exe 會以 quick-runner.exe 的獨立背景程序執行排班；介面本身不載入求解器，因此 quick-runner.exe 仍可單獨使用。
- input、output 與 config.json 可能含有個人資料，請妥善保管。
- 發布包內的月份資料是匿名範例，可直接用於首次測試。
- 若已有自己的 config、input 或 output，更新版本前請先備份；不要直接以新 ZIP 覆蓋既有資料夾。
- 正式檔案產生後才會開始候選處理；在編輯器可按「終止候選處理」，獨立主控台則按 Ctrl+C，均不影響已完成的正式結果。
- 第三方元件聲明、完整授權條款與 Qt LGPL 原始碼資訊集中在 licenses 資料夾。

發生錯誤時，請保留主控台訊息、使用的 config.json 與匿名化後的輸入資料供維護者檢查。
