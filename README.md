# Clinic Shift Scheduler

本 repository 依據 `診所排班系統.md` 實作診所排班系統。目前完成 v1 資料契約、輸入驗證、正規化、OR-Tools CP-SAT 硬性可行性模型、保守前置可行性檢查、完整嚴格字典序目標、獨立結果驗證器、媒介無關的正式班表與統計輸出模型，以及 JSON／Excel／PDF 正式輸出 adapter。

## 專案結構

- `src/clinic_shift_scheduler/models.py`：不可變的輸入與正規化型別。
- `src/clinic_shift_scheduler/authoring.py`：將使用者維護的每週營業／需求範本展開成 canonical v1 逐日需求。
- `src/clinic_shift_scheduler/schemas/`：版本化 JSON Schema。
- `src/clinic_shift_scheduler/validation.py`：結構與語意驗證，失敗統一回報 `INPUT_INVALID`。
- `src/clinic_shift_scheduler/normalization.py`：日期、休診、可用性、請假及需求的正規化。
- `src/clinic_shift_scheduler/daily_patterns.py`：CP-SAT 與前置檢查共用的 v1 每日班型規則。
- `src/clinic_shift_scheduler/feasibility.py`：無目標函數的 CP-SAT 硬性可行性模型。
- `src/clinic_shift_scheduler/precheck.py`：總量、個人容量、職務容量及同時段匹配的必要條件檢查。
- `src/clinic_shift_scheduler/optimization.py`：TARGET 偏差、兼職用量、A+B 班型品質、A／B 類別品質比例、類別內個人比例／整數公平性、其他群組公平性與最佳值鎖定控制器。
- `src/clinic_shift_scheduler/ratio_fairness.py`：optimizer、結果重算與報表共用的品質順位及整數 basis-points 換算規則。
- `src/clinic_shift_scheduler/result_metrics.py`：只從最終 assignments 重算每日模式、統計、公平性 gap 與完整目標向量。
- `src/clinic_shift_scheduler/result_validation.py`：獨立驗證硬性規則、階段順序及鎖定目標值。
- `src/clinic_shift_scheduler/output.py`：媒介無關的日期橫向班表、個人／群組／整體統計與正式狀態提升。
- `src/clinic_shift_scheduler/exporters/`：版本化 JSON、Excel 等檔案媒介 adapter 與安全輸出路徑管理；不得放入排班或統計邏輯。
- `tests/`：synthetic fixtures 與單元測試。
- `排班資料/`：本機實際排班資料；直接放在此層的真名檔案由 Git 忽略，只有 `排班資料/匿名範本/` 會納入版本控制並作為開發與整合驗證資料。

`solve_lexicographic` 會先鎖定 A+B 連續雙班總數，再跨 A／B 類與
`fairness_group` 最小化全體正職個人的連續雙班比例最大差距及兩兩差總和；
其餘班型公平性仍依正式規格分組處理。各階段的 `OPTIMAL`／`SKIPPED_CONSTANT` 及
`implemented_objective_prefix_optimal` 表示所有正式目標均已證明最佳，
但求解結果本身仍只回傳 `FEASIBLE`。將結果交給
`finalize_schedule_output` 後，只有獨立驗證全部通過才會提升為完整 v1
`OPTIMAL`；驗證失敗則回傳 `VALIDATION_FAILED` 且不建立正式月班表。

正式執行產物預設寫入 repository root 的 `output/`，整個資料夾均由
Git 忽略，避免真實姓名或排班內容進入版本控制。正式檔名固定為
`排班結果_YYYY-MM.result-v1.json`／`.xlsx`／`.pdf`；Excel 使用 `openpyxl` 建立
月班表、個人班型摘要、個人詳細統計、類別與公平性統計及求解與驗證資訊五個工作表。
工作表依一般使用者的閱讀順序排列，完整技術與稽核資料仍保留。預設拒絕覆寫，只有呼叫端
明確指定 `overwrite=True` 才會替換既有檔案。
PDF 使用 `reportlab` 直接讀取已完成驗證的正式 Excel，只輸出單頁 A4 橫向「月班表」，
供快速查看與列印；PDF exporter 不重新計算排班規則或統計，Excel 不是
`OPTIMAL + validation PASS` 時拒絕產生正式 PDF。

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
from clinic_shift_scheduler import validate_and_normalize_weekly

normalized = validate_and_normalize_weekly(raw_weekly_mapping)
```

建議使用者維護 `weekly-v1` 精簡輸入，例如
`排班資料/匿名範本/排班輸入_匿名_2026-08.weekly-v1.json`。每個星期必須恰好由一條
週規則涵蓋；`is_open: true` 時完整填寫早、午、晚各職務人數，
`is_open: false` 時省略 `staffing`。`date_overrides` 可讓原本營業的特定
日期臨時休診，或以完整的當日 `staffing` 取代週規則。前處理會展開為
canonical v1 的逐日 `demands`，再交給既有嚴格驗證與求解流程。

若上游系統本來就會產生完整 canonical v1 資料，仍可直接使用：

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
