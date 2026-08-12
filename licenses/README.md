# Third-party licenses

本目錄是診所排班系統第三方授權資訊的唯一版本控制來源。開發環境與 Windows 發布包
不得各自維護不同聲明；正式封裝會完整複製此目錄到發布資料夾的 `licenses/`。

- `THIRD_PARTY_NOTICES.txt`：元件、版本、授權類型與 Qt LGPL 使用方式摘要。
- `PYTHON_PACKAGE_LICENSES.txt`：由實際發布環境之套件 metadata 彙整的授權全文。
- `PYTHON-3.12.txt`：封裝之 Python runtime 授權。
- `GNU-LGPL-3.0.txt`、`GNU-GPL-3.0.txt`：PySide6／Qt 採用的社群版授權全文。
- `QT_SOURCE_OFFER.txt`：對應 Qt／PySide6 原始碼與 DLL 替換資訊。
- `NOTO-OFL-1.1.txt`：PDF 內嵌 Noto Sans TC 字型授權。
- `ORTOOLS-*.txt`：OR-Tools wheel 中個別 native DLL 的上游授權全文。
- `manifest.json`：授權檔 SHA-256 與同步時的精確套件版本。

維護者升級 Python、Qt、OR-Tools、輸出套件或任何間接依賴後，需重新執行：

```powershell
python packaging/windows/sync_licenses.py
```

若 GNU 授權全文尚未建立，第一次可加上 `--download-static`。產生結果必須經人工審查後
提交；正常發布流程不會連線下載授權文件。
