# Clinic Shift Scheduler

本 repository 依據 [診所排班系統規格](docs/scheduling-specification.md) 實作診所排班系統。目前完成 v1 資料契約、輸入驗證、正規化、OR-Tools CP-SAT 硬性可行性模型、保守前置可行性檢查、完整嚴格字典序目標、獨立結果驗證器、媒介無關的正式班表與統計輸出模型，以及 JSON／Excel／PDF 正式輸出 adapter。

## 專案結構

- `src/clinic_shift_scheduler/models.py`：不可變的輸入與正規化型別。
- `src/clinic_shift_scheduler/authoring_models.py`：使用者維護的 weekly-v1 不可變 typed document。
- `src/clinic_shift_scheduler/authoring.py`：weekly-v1 的驗證、讀寫與 canonical v1 逐日需求展開。
- `src/clinic_shift_scheduler/input_contracts.py`：JSON Schema 與 runtime parser 共用的輕量欄位契約。
- `src/clinic_shift_scheduler/json_io.py`：使用者 JSON 文件的 UTF-8 讀取與原子替換。
- `src/clinic_shift_scheduler/events.py`：前端／CLI 共用的結構化診斷、進度事件與取消介面。
- `src/clinic_shift_scheduler/application_contracts.py`：不載入求解器的執行請求與候選輸出設定。
- `src/clinic_shift_scheduler/optimization_contracts.py`：不依賴 CP-SAT 的正式目標與公平性契約。
- `src/clinic_shift_scheduler/solver_contracts.py`：不依賴 CP-SAT 的 assignment 與求解結果契約。
- `src/clinic_shift_scheduler/schemas/`：版本化 JSON Schema。
- `src/clinic_shift_scheduler/validation.py`：結構與語意驗證，失敗統一回報 `INPUT_INVALID`。
- `src/clinic_shift_scheduler/normalization.py`：日期、休診、可用性、請假及需求的正規化。
- `src/clinic_shift_scheduler/daily_patterns.py`：CP-SAT 與前置檢查共用的 v1 每日班型規則。
- `src/clinic_shift_scheduler/feasibility.py`：無目標函數的 CP-SAT 硬性可行性模型。
- `src/clinic_shift_scheduler/precheck.py`：總量、個人容量、職務容量及同時段匹配的必要條件檢查。
- `src/clinic_shift_scheduler/class_preferences.py`：A／B 類各自偏好順位、方向、類別機會日及 regret 的共用定義。
- `src/clinic_shift_scheduler/optimization.py`：TARGET 偏差、兼職用量、類別偏好 benchmark／regret、類別內個人比例／整數公平性、其他群組公平性與最佳值鎖定控制器。
- `src/clinic_shift_scheduler/ratio_fairness.py`：optimizer、結果重算與報表共用的整數 basis-points 換算規則。
- `src/clinic_shift_scheduler/result_metrics.py`：只從最終 assignments 重算每日模式、統計、公平性 gap 與完整目標向量。
- `src/clinic_shift_scheduler/result_validation.py`：獨立驗證硬性規則、階段順序及鎖定目標值。
- `src/clinic_shift_scheduler/output.py`：媒介無關的日期橫向班表、個人／群組／整體統計與正式狀態提升。
- `src/clinic_shift_scheduler/exporters/`：版本化 JSON、Excel 等檔案媒介 adapter 與安全輸出路徑管理；不得放入排班或統計邏輯。
- `src/clinic_shift_scheduler/runner.py`：串接一次完整排班、正式輸出及端到端計時。
- `src/clinic_shift_scheduler/__main__.py`：`python -m clinic_shift_scheduler` 的正式命令列入口。
- `tests/`：synthetic fixtures 與單元測試。
- `input/`：本機實際排班資料；直接放在此層的真名檔案由 Git 忽略，只有 `input/匿名範本/` 會納入版本控制並作為開發與整合驗證資料。
- `runtime/expanded-input/`：由 weekly-v1 自動展開的逐日 canonical 輸入；每次排班會先清空再重建，整個 `runtime/` 不納入 Git。

## 使用者輸入文件邊界

weekly-v1 與 `config.json` 都有版本化 typed document、bundled JSON Schema、
`from_dict()`／`to_dict()`、讀檔及原子寫入功能。weekly round-trip 會保留員工
`notes`、請假 note、欄位是否明確宣告及原始排序；config round-trip 會保留所有
`__...__` 說明與分隔欄位。前端應只透過這些文件模型維護 `input/` 與
`config.json`，不得直接編輯 `runtime/expanded-input/` 的 solver 中間資料。

`solve_lexicographic` 將 A 類「連續雙班、早晚雙班、單節日」與 B 類
「避免單節日、連續雙班、三節班 fallback」視為不同偏好順位；B 類另有每人每個
排班月份最多 3 個單節出勤日的硬限制，不建立最大化三節班目標。每一順位先獨立證明
A、B 類各自的理想值，再依類別機會日計算整數 basis-point regret，依序最小化
兩類最大 regret 與 regret 總和，並明確鎖定兩類各自的實際品質總值。類別總體品質鎖定後，個人公平性只在相同類別及
`fairness_group` 內計算，但將全部班型 gap 放進同一 minimax 套件：先壓低最差
gap，再處理第一順位 gap 總和及全部 gap 總和，避免逐項過早鎖死或為公平增加較差班型總量。
既有目標全部鎖定後，最後再跨 A／B 類與 `fairness_group` 最小化全體正職的週日節數及週日出勤天數差距，僅作同品質候選解的最終 tie-breaker。各階段的
`OPTIMAL`／`SKIPPED_CONSTANT` 及
`implemented_objective_prefix_optimal` 表示所有正式目標均已證明最佳，
但求解結果本身仍只回傳 `FEASIBLE`。將結果交給
`finalize_schedule_output` 後，只有獨立驗證全部通過才會提升為完整 v1
`OPTIMAL`；驗證失敗則回傳 `VALIDATION_FAILED` 且不建立正式月班表。

正式執行產物預設寫入 repository root 的 `output/`，整個資料夾均由
Git 忽略，避免真實姓名或排班內容進入版本控制。正式檔名固定為
`排班結果_YYYY-MM.result-v1.json`／`.xlsx`／`.pdf`；Excel 使用 `openpyxl` 建立
月班表、個人班型摘要、個人詳細統計、類別與公平性統計及求解與驗證資訊五個工作表；
個人班型摘要另列每人的週日節數與週日出勤天數。
工作表依一般使用者的閱讀順序排列，完整技術與稽核資料仍保留。預設拒絕覆寫，只有呼叫端
明確指定 `overwrite=True` 才會替換既有檔案。
PDF 使用 `reportlab` 直接讀取已完成驗證的正式 Excel，輸出單頁 A4 橫向「月班表」，
並在月班表下方直接接續「個人班型摘要」表格，不另加摘要標題，供快速查看與列印；
PDF exporter 不重新計算排班規則或統計，Excel 不是
`OPTIMAL + validation PASS` 時拒絕產生正式 PDF。

## 使用方式

本專案使用名為 `clinic_shift_scheduler` 的 Conda environment，Python
版本固定為 3.12。首次建立環境並依 `pyproject.toml` 安裝專案：

```powershell
conda env create --file environment.yml
conda activate clinic_shift_scheduler
```

### 建立 Windows 一般使用者發布包

Windows 64 位元 portable 發布設定集中在
[`packaging/config_packaging.json`](packaging/config_packaging.json)，包含發布版本、
PyInstaller 版本、匿名範例、Noto Sans TC 固定來源與建置／驗收開關。啟用專案
Conda environment 後執行：

```powershell
.\packaging\windows\build.ps1
```

建置器會執行測試、產生 PyInstaller `onedir`、使用匿名月份完成封裝後 smoke test，
並在被 Git 忽略的 `release/版本名稱/` 建立 ZIP、SHA-256 與 build manifest；
不另外保留已解壓的 onedir。完整維護方式請見
[`packaging/windows/README.md`](packaging/windows/README.md)。

後續開發或執行前先啟用環境：

```powershell
conda activate clinic_shift_scheduler
```

### 完整執行一次排班

日常使用只需準備兩份 JSON：`input/` 內的每月排班輸入，以及 repository root
的 `config.json` 執行設定。`config.json` 的「輸入檔名」只填檔名，例如
`排班輸入_2026-08.json`；主要入口 `src/run_scheduler.py` 會固定到 `input/`
尋找該檔案。在 repository root 執行：

```powershell
python src/run_scheduler.py
```

此入口會明確使用覆寫模式更新同月份結果，並依序完成讀檔、weekly-v1 逐日展開、
validation、normalization、precheck、完整
lexicographic optimization、獨立結果驗證，以及 JSON、Excel、PDF 輸出。
封裝版若由使用者直接雙擊執行，完成或失敗後會等待按 Enter 才關閉視窗；從既有
PowerShell／VS Code 終端執行則維持原本結束行為，不會阻塞自動化流程。
三份正式檔案完成後，程式才開始搜尋與正式班表具有完全相同鎖定品質、但核心
assignment 不同的候選班表；因此不想等待診斷時，可在看到「正式 JSON／Excel／PDF
已完成」後按 `Ctrl+C`，已產出的正式班表不受影響。候選數不包含正式輸出的那一份。
若搜尋空間已完整證明，程式會列印精確數量；達到預設 100 份上限或本次 CP-SAT
最佳化時間五分之一的診斷時限時，只列印「至少找到 N 份」並明確註明尚未證明
是否還有更多。正式輸出完成時會先列印排班時間與全部檔案路徑，後續訊息改用
`[候選處理]` 標籤，不會讓使用者誤以為正式排班仍未完成。
`config.json` 可設定候選搜尋份數、診斷秒數、額外保存幾份候選及保存格式。
被保存的候選會逐份通過獨立 validator，寫入 `output/候選班表/`；每次成功產生
新的正式班表後會清空重建該資料夾。候選診斷的搜尋先完成，再進行 JSON、Excel、
PDF 寫檔，因此媒介轉換不占用診斷搜尋時限。
展開後的逐日 `demands` 只寫入 `runtime/expanded-input/`，供除錯與稽核；該資料夾
每次執行都會清空重建，不是使用者要維護的輸入。

`config.json` 範例：

```json
{
  "__使用者設定分隔線__": "==================== 使用者設定 ====================",
  "使用者設定": {
    "設定版本": "1",
    "輸入檔名": "排班輸入_2026-08.json",
    "覆寫既有結果": true,
    "進度更新秒數": 5,
    "候選診斷": {
      "啟用": true,
      "搜尋上限": 100,
      "診斷時間上限": {
        "模式": "比例",
        "排班時間比例": 0.2
      },
      "額外輸出候選班表份數上限": 3,
      "輸出格式": ["JSON", "Excel", "PDF"]
    }
  },
  "__預設設定分隔線__": "==================== 預設設定（僅供查閱） ====================",
  "預設設定": {
    "設定版本": "1",
    "輸入檔名": "排班輸入_2026-08.json",
    "覆寫既有結果": true,
    "進度更新秒數": 5,
    "候選診斷": {
      "啟用": true,
      "搜尋上限": 100,
      "診斷時間上限": {"模式": "比例", "排班時間比例": 0.2},
      "額外輸出候選班表份數上限": 3,
      "輸出格式": ["JSON", "Excel", "PDF"]
    }
  }
}
```

「診斷時間上限」有兩種互斥模式：「比例」以正式 CP-SAT 最佳化實測時間乘上
「排班時間比例」，例如 `0.2` 即五分之一；「定值」則改填 `"秒數": 60`。
「額外輸出候選班表份數上限」為 `0` 代表只診斷數量、不保存候選，且不可大於「搜尋上限」。
支援的格式為 `JSON`、`Excel`、`PDF`。程式只讀「使用者設定」；「預設設定」只供
修改後查回原始值。所有說明與視覺分隔欄位一律命名為 `__...__`，載入時自動忽略；
請修改「使用者設定」，不要只修改「預設設定」。

固定 60 秒的寫法如下：

```json
"診斷時間上限": {
  "模式": "定值",
  "秒數": 60
}
```

若需要從命令列臨時指定其他輸入，而不修改主檔，也可使用套件入口：

```powershell
python -m clinic_shift_scheduler "input/排班輸入_2026-08.json" --overwrite
```

也可以使用安裝專案時由 `pyproject.toml` 建立的同義指令：

```powershell
clinic-shift-scheduler "input/排班輸入_2026-08.json" --overwrite
```

若不允許取代同月份既有輸出，省略 `--overwrite`；另可用
`--output-dir <資料夾>` 指定輸出位置。入口會自動辨識 `weekly-v1` 精簡輸入與
canonical v1 輸入。執行完成時，終端會列印輸入、驗證、precheck、CP-SAT、
獨立驗證、各輸出媒介及端到端總時間。排班管線的時間紀錄亦會保存於正式 JSON
的 `execution_timing`，並顯示在 Excel 的「求解與驗證資訊」工作表。
嚴格分階段最佳化執行期間每 5 秒會更新一次累積耗時；在互動式終端中固定覆寫
同一行，完成時清除進度行並列印該段總時間，用來確認長時間 CP-SAT 求解仍在運作。
輸出重新導向到檔案或 CI log 時則保留逐行紀錄。由於各階段搜尋難度並不平均，
系統不顯示可能誤導的百分比進度。候選診斷找到每一份候選時，也會在互動式終端覆寫同一行顯示累積份數；非互動式 log 則保留逐行紀錄。
候選診斷可用 `--equivalent-limit`、`--equivalent-time-limit` 或
`--equivalent-time-ratio` 調整上限；明確提供固定秒數時優先使用固定值。若完全不需診斷，可加上
`--skip-equivalent-diagnostic`。臨時從 CLI 保存候選時可用
`--candidate-export-count N --candidate-export-formats json excel pdf`；日常執行則直接
修改 `config.json`。此診斷在正式輸出之後執行，不屬於正式 result contract，
也不改變 `OPTIMAL + validation PASS`。

```python
from clinic_shift_scheduler import validate_and_normalize_weekly

normalized = validate_and_normalize_weekly(raw_weekly_mapping)
```

使用者正式維護 `weekly-v1` 精簡輸入，例如
`input/匿名範本/排班輸入_匿名_2026-08.json`。每個星期必須恰好由一條
週規則涵蓋，通常分為週一至週五、週六、週日三組；`is_open: true` 時完整填寫
早、午、晚各職務人數，
`is_open: false` 時省略 `staffing`。`date_overrides` 可讓原本營業的特定
日期臨時休診，或以完整的當日 `staffing` 取代週規則。前處理會展開為
canonical v1 的逐日 `demands`，再交給既有嚴格驗證與求解流程。相同 JSON 亦包含
每位員工姓名、職務資格、正職類別、`fairness_group`、班次模式與當月節數、
兼職明確可排時段、請假及不可排時段，均可按月修改。

使用者檔名不放格式版號；格式由 JSON 內部欄位辨識。`schema_version: v1`
代表排班資料與規則契約版本，`authoring_version: weekly-v1` 則代表這份輸入使用
「每週規則展開成逐日需求」的編輯格式。兩者分開版本化，才能在排班規則仍是 v1
時，辨識 weekly authoring 與 canonical 等不同資料表示方式。

canonical v1 是 solver-facing 中間契約；只有上游系統本來就會產生完整逐日資料時，
才需要直接使用：

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
