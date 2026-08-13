診所排班系統 {{VERSION}}（Windows 64 位元）

使用方式：
1. 雙擊 ClinicShiftSchedulerEditor.exe，建立或開啟 input 資料夾內的月份資料。
2. 在編輯器完成輸入檢查並儲存 JSON；也可以不使用編輯器，直接修改 JSON。
3. 按編輯器右上角「設定」，調整執行與候選設定；也可以直接修改 config.json。
4. 到「執行排班」頁執行目前月份，並在畫面查看進度、耗時與輸出路徑。
5. 到 output 資料夾取得 JSON、Excel 與 PDF。

不使用圖形介面時，也可以雙擊 ClinicShiftScheduler.exe，依 config.json 指定的輸入檔完成相同排班流程。

直接雙擊執行時，排班完成或發生錯誤後視窗會保留，閱讀訊息後按 Enter 才會關閉。從 PowerShell 或其他既有終端執行時不會額外等待。

注意事項：
- 整個資料夾必須一起保留，請勿刪除或移動 _internal。
- ClinicShiftSchedulerEditor.exe 會以獨立背景程序執行排班；介面本身不載入求解器，因此命令列入口仍可單獨使用。
- input、output 與 config.json 可能含有個人資料，請妥善保管。
- 發布包內的月份資料是匿名範例，可直接用於首次測試。
- 若已有自己的 config、input 或 output，更新版本前請先備份；不要直接以新 ZIP 覆蓋既有資料夾。
- 正式檔案產生後才會開始候選處理；在編輯器可按「終止候選處理」，獨立主控台則按 Ctrl+C，均不影響已完成的正式結果。
- 第三方元件聲明、完整授權條款與 Qt LGPL 原始碼資訊集中在 licenses 資料夾。

發生錯誤時，請保留主控台訊息、使用的 config.json 與匿名化後的輸入資料供維護者檢查。
