# Preserve Current Best Schedule Design

## 目標

在 GUI 排班執行期間新增「終止排班並保留當前最佳班表」操作。此操作會停止後續 CP-SAT 最佳化，保存目前可取得且通過獨立驗證的合法班表；結果必須明確標示為 `FEASIBLE`，不得宣稱或冒充完整 `OPTIMAL` 正式結果。

現有「終止排班」維持取消並放棄本次結果的語意。正式 lexicographic objective 順序、最佳值鎖定、cancellation、正式 exporter 與候選班表流程均不得改變。

## 使用者介面與狀態

執行頁新增「終止排班並保留當前最佳班表」按鈕：

- 尚未完成 hard feasibility 時停用。
- 收到 `has_feasible_solution=true` 後啟用。
- validation、正式輸出與候選處理期間停用。
- 按下後顯示確認視窗，說明班表合法但尚未證明完整最佳。
- 確認後停用所有排班停止按鈕，狀態改為「正在停止最佳化並保存目前最佳合法班表」。
- 若按鈕請求與完整 `OPTIMAL` 幾乎同時發生，優先完成正常正式輸出。

成功保存後，執行頁顯示 `FEASIBLE + validation PASS`、已完成的正式 stages、停止位置及實際輸出路徑。失敗時顯示結構化原因，不得把暫存結果顯示成正式完成。

## 停止控制

新增與 `CancellationToken` 分離的 thread-safe preserve request。兩者都能要求目前的 `CpSolver` 執行 `stop_search()`，但後續控制流程不同：

- cancellation：維持現況，runner 中止且不保存本次結果。
- preserve request：optimizer 正常返回目前可用的 partial result，runner 繼續獨立驗證及 provisional export。

GUI controller 與 worker 使用獨立 control file 傳遞 preserve request，不重用 cancel file。worker protocol 新增可辨識的 preserved completion 結果，但既有 progress `details` 與 cancellation 訊息維持相容。

## 要保存的解

optimizer 在每個已完成正式 stage 後保留穩定 snapshot，並依停止位置選擇結果：

- 正在正式 objective stage：若本次 CP-SAT 已有 incumbent，使用該 incumbent；若尚無 incumbent，使用上一份穩定 snapshot。
- 正在 hard feasibility：只有 solver 已取得合法解且能形成 snapshot 時才可保存；否則回報尚無可保存班表。
- 正在 preference benchmark：不得輸出單一 A／B benchmark 的 incumbent，必須使用 benchmark 開始前的最近穩定正式流程 snapshot。
- 位於 stage 邊界：不再啟動下一個 stage，直接使用剛完成並鎖定的 snapshot。
- 正式十六階段均已證明完成：忽略 provisional 降級，走既有正式 `OPTIMAL` 流程。

Partial result 必須記錄已完成 stages、停止時 activity、尚未完成 stages、已知 objective values、`implemented_objective_prefix_optimal`、停止原因及 solver telemetry。未完成或未證明的 objective 不得偽造值或鎖定狀態。

## 驗證與結果狀態

保存前必須只根據 assignment 與輸入重新執行既有獨立驗證器。驗證範圍包含全部硬性規則，以及 partial result 中宣稱已鎖定的 objective values。

- 驗證通過：`FEASIBLE + PASS`，允許 provisional export。
- 驗證失敗：`VALIDATION_FAILED`，不得輸出 JSON、Excel 或 PDF。
- 尚無合法 snapshot：不輸出，回報 `NO_FEASIBLE_SCHEDULE_TO_PRESERVE`。

既有正式 exporter 仍只接受 `OPTIMAL + PASS`，不得放寬 `require_formal_result()`。

## 設定契約

在 `使用者設定` 與 `預設設定` 新增向後相容的選用區塊：

```json
"當前最佳班表輸出": {
  "輸出格式": [
    "JSON",
    "Excel",
    "PDF"
  ]
}
```

- 支援格式為 JSON、Excel、PDF，大小寫正規化規則沿用候選輸出。
- 至少選擇一種格式，預設三種全部輸出。
- 舊設定檔未提供區塊時使用預設三種格式，因此 `設定版本` 維持 `1`。
- 此設定只控制 preserve request 的 provisional files，不影響正式輸出或候選班表輸出。
- GUI 一般設定頁提供相同格式選項。

## Provisional 輸出

媒介邏輯維持在 `exporters/`，不得移入媒介無關的 `output.py`。檔名為：

```text
排班暫存結果_YYYY-MM.feasible-v1.json
排班暫存結果_YYYY-MM.feasible-v1.xlsx
排班暫存結果_YYYY-MM.feasible-v1.pdf
```

輸出遵守既有 `覆寫既有結果` 設定。開始停止 solver 前應先確認所選格式的目標路徑可寫入；不可覆寫且已有檔案時，preserve request 不得停止仍在執行的排班。

JSON 使用獨立版本化 provisional result contract，保存 `FEASIBLE`、validation、assignments、statistics、partial stage records、停止位置及 telemetry。Excel 與 PDF 沿用既有媒介無關結果資料，不重新計算規則或統計，並在顯著位置標示：

```text
目前最佳合法班表
尚未完成全部最佳化，不代表正式最佳結果
```

如果只選 PDF，exporter 可在暫存位置建立 provisional Excel 作為 PDF 來源，完成後刪除未被選取的中間 Excel。所有被選取格式完成後才能回報 preserved success。

## 錯誤與競態處理

- preserve 與 cancel 只接受第一個有效請求，後續請求不改變既定 disposition。
- preserve 路徑預檢失敗時不得停止 solver。
- preserve 完成後不執行 equivalent solution／candidate diagnostic。
- exporter 失敗時回報 provisional export failure；不得建立或覆蓋正式結果檔案。
- worker 非正常結束時維持既有 protocol failure 行為。
- 關閉 GUI 仍使用 cancellation，不自動保存，避免使用者關閉程式時產生意外檔案。

## 驗收標準

- 未取得 hard-feasible schedule 前按鈕保持停用，取得後立即啟用。
- 現有「終止排班」仍不留下本次結果。
- preserve 在 hard feasibility、正式 stage、preference benchmark 與 stage boundary 均選擇正確 snapshot。
- preserve 不改變已完成 stage 的 objective values 或 locks。
- partial assignment 必須通過獨立驗證，竄改後不得輸出。
- 輸出格式完全遵守 config，舊 config 預設輸出三種格式。
- provisional JSON、Excel、PDF 均清楚標示 `FEASIBLE` 與未證明最佳。
- 完整 `OPTIMAL` 正式輸出與 candidate diagnostic 行為保持不變。
- cancellation、preserve、輸出失敗與幾乎同時完成的 race condition 有自動化測試。
- 完整既有測試套件通過。
