# Clinic Shift Scheduler

本 repository 依據 `診所排班系統.md` 實作診所排班系統。目前完成 v1 資料契約、輸入驗證、正規化、OR-Tools CP-SAT 硬性可行性模型，以及第三階段的保守前置可行性檢查；尚未加入 TARGET 最佳化、兼職最小化、公平性、多階段最佳化或正式班表輸出。

## 專案結構

- `src/clinic_shift_scheduler/models.py`：不可變的輸入與正規化型別。
- `src/clinic_shift_scheduler/schemas/`：版本化 JSON Schema。
- `src/clinic_shift_scheduler/validation.py`：結構與語意驗證，失敗統一回報 `INPUT_INVALID`。
- `src/clinic_shift_scheduler/normalization.py`：日期、休診、可用性、請假及需求的正規化。
- `src/clinic_shift_scheduler/daily_patterns.py`：CP-SAT 與前置檢查共用的 v1 每日班型規則。
- `src/clinic_shift_scheduler/feasibility.py`：無目標函數的 CP-SAT 硬性可行性模型。
- `src/clinic_shift_scheduler/precheck.py`：總量、個人容量、職務容量及同時段匹配的必要條件檢查。
- `tests/`：synthetic fixtures 與單元測試。

## 使用方式

本專案使用名為 `clinic_shift_scheduler` 的 Conda environment，Python
版本固定為 3.12。首次建立環境並依 `pyproject.toml` 安裝專案：

```powershell
conda env create --file environment.yml
conda activate clinic_shift_scheduler
```

後續開發或執行前先啟用環境：

```powershell
conda activate clinic_shift_scheduler
```

```python
from clinic_shift_scheduler import validate_and_normalize

normalized = validate_and_normalize(raw_v1_mapping)
```

驗證失敗時會拋出 `InputValidationError`，其中 `status` 固定為 `INPUT_INVALID`，`issues` 包含錯誤代碼、資料路徑及訊息。

## 執行測試

PowerShell：

```powershell
conda activate clinic_shift_scheduler
python -m pytest
```

不切換目前 shell 的 environment 時，可執行：

```powershell
conda run --name clinic_shift_scheduler python -m pytest
```

不使用 pytest 時，也可在已啟用的 environment 中執行：

```powershell
python -m unittest discover -s tests -v
```

`pyproject.toml` 的依賴異動後，使用相同 environment 重新同步：

```powershell
conda env update --file environment.yml
```
