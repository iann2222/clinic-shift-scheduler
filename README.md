# Clinic Shift Scheduler

本 repository 依據 `診所排班系統.md` 實作診所排班系統。目前完成第一階段的 v1 資料契約、輸入驗證與正規化；尚未加入 OR-Tools 求解器、最佳化或班表輸出。

## 專案結構

- `src/clinic_shift_scheduler/models.py`：不可變的輸入與正規化型別。
- `src/clinic_shift_scheduler/schemas/`：版本化 JSON Schema。
- `src/clinic_shift_scheduler/validation.py`：結構與語意驗證，失敗統一回報 `INPUT_INVALID`。
- `src/clinic_shift_scheduler/normalization.py`：日期、休診、可用性、請假及需求的正規化。
- `tests/`：synthetic fixtures 與單元測試。

## 使用方式

```python
from clinic_shift_scheduler import validate_and_normalize

normalized = validate_and_normalize(raw_v1_mapping)
```

驗證失敗時會拋出 `InputValidationError`，其中 `status` 固定為 `INPUT_INVALID`，`issues` 包含錯誤代碼、資料路徑及訊息。

## 執行測試

PowerShell：

```powershell
$env:PYTHONPATH = "src;."
python -m pytest
```

不使用 pytest 時，也可執行：

```powershell
$env:PYTHONPATH = "src;."
python -m unittest discover -s tests -v
```
