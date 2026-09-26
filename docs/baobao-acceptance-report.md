# 寶寶礦到了｜Multi-Brand Isolation 安全修復驗收

驗收日期：2026-09-26，Asia/Taipei。本次保留原 commits、品牌資料夾、Meta App 與 Hosting 路徑，沒有重新命名 New project、搬動商品、產生假校準內容、發布 Instagram 或 Resume production。

## 本機修復與重新稽核

| 項目 | 結果與證據 |
|---|---|
| Hosting Cache Identity | PASS；schema 2 綁定 brand、Campaign、asset key、來源根目錄／路徑、SHA-256、完整及正規化 URL、原始及正規化 object key、namespace、MIME。舊 hash-only evidence 不再命中 |
| Formal Publisher URL Gate | PASS；maiocha 的正式 API 前再次檢查 URL 與 Campaign，正式發布重新下載 hash／MIME；拒絕 redirects。原本同 hash 換 baobao URL 的漏洞，唯讀重現已被拒絕 |
| Hosting Brand Boundary | PASS；雙向 upload、overwrite、delete、cleanup 與來源範圍；路徑 segment、URL decoding、dot segments、重複斜線、prefix collision、junction／symlink 防線 |
| Generic Launcher | PASS；必須 -Brand maiocha 或 baobao；缺少／未知／重複 override 拒絕；原 maiocha 入口位置保留 |
| Older Entrypoints | PASS；舊 Campaign／單張／臨時 Hosting 也限制 maiocha 來源及確認範圍。單張測試的任意外部 URL 路徑關閉；目前設定本來就使用本機圖片臨時 Hosting |
| Retired Release Backend | PASS；無啟用設定的 GitHub Release asset 寫入／刪除介面停止接受操作，現行 Pages 不受影響 |
| Current Hosting Inventory | PASS；依真實 manifest/config 登記四個 maiocha Campaign；唯讀核對 40 份現有素材全部通過，沒有移動或改名 |
| Scope / Shared Engine | PASS；安全核心由 config scope 決定品牌差異，不內嵌 Token／IG ID／Caption；repository 名稱是歷史名稱，不視為混用 |
| State Isolation | PASS；品牌獨立 journal／queue／history，跨品牌 approval、claim、schedule、history 寫入拒絕；錯品牌 config 不能進入文案生成 |
| Pause Isolation | PASS；兩品牌獨立狀態測試；baobao 不 Resume |
| Actual maiocha Publisher Dry Run | PASS；修復後真實 API、10 份公開素材、中文 Caption／既有 QA／history／target checks 全通過；Instagram POST=0 |
| Python Regression | PASS；146 tests，含原有 131 與新增 15 項 isolation tests；60.621 秒 |
| PowerShell Security | PASS；53 個案例，含快取、双向 Hosting、launcher、舊入口、原狀態機整合；只使用 fixtures，不發布 |
| maiocha Original Tests | PASS；原 8 項狀態機測試保持原內容，在安全案例中及本機原入口驗證 |
| Baseline | PASS；原 40 檔 baseline 不重設。29 檔未變，11 檔為授權的安全修復；另修 generic launcher，共 12 個原位置工具。無意外變更 |
| Deployment Copies | PASS；12 份本機工具與 repository 的部署來源逐一 hash 相同；更新前有 preimage 檢查與私人備份 |
| Workflow Syntax | PASS；YAML 解析、job 結構；新增 Windows／Linux PowerShell CI，原 baobao 發布 workflow 不修改 |

## Batch 與 Caption Calibration 回歸

以下由完整測試驗證，沒有把 fixtures 當成真實商品文案品質：

| 項目 | 結果 |
|---|---|
| Batch / Natural-language Intake | PASS；7／14 天商品、每條約 6 張、content_id／asset_id／hash 隔離 |
| User Identity / Metadata | PASS；crystal_name 只接受使用者提供；商品與 metadata 不跨組 |
| Schedule | PASS；保留使用者日期；預設 **10:00 Asia/Taipei**；單篇 override 不改品牌預設 |
| Grounding / Caption Basis / Product Caption QA | PASS；實際照片優先，不猜礦名、價格、珠徑、功效；錯色與跨商品資料拒絕 |
| Calibration / Six Styles / Preview | PASS；1～3 商品、每條獨立六種 Style；CALIBRATION_READY_FOR_REVIEW 後停止 |
| Feedback / Profile / Updates | PASS；自然語言偏好保存、使用者確認後才建立正式 Profile；可持續更新 |
| Style QA / Wording Repetition | PASS；語氣、風景、句型、CTA、signature 與近期重複檢查 |
| Formal Batch Calibration Gate | PASS；未校準不能 finalize Caption 或正式批准排程 |
| Calibration Cannot Schedule / Publish | PASS；校準確認不等於商品發布批准；偽造 APPROVED 也不得發 |
| Approval / Reviewed Caption / Duplicate / Archive | PASS；只發布事前 QA 且明確批准的版本；發布當下不重新生成，保存 Media ID 與 hash，禁止自動重複 |

## 遠端部署驗證

本機修復與稽核已 PASS；本次新版本 GitHub push、CI、Pages、遠端 dry-run／暫停狀態尚待本輪部署後記錄，不能以先前 CI 代替新版本結果。

沿用 MaiOcha Lab Automation（1833218008099793）及 Facebook Login。已驗證的帳號為 maiocha.lab／藍屋生活誌與 babycrystal.tw／日常收藏所；BAOBAO 四個 Secrets 名稱保持獨立。部署階段只讀取 Secret 存在狀態，不輸出值。

## 下一個 checkpoint

工程驗收完成後只等待 **1～3 條真實校準商品，每條約六張照片及使用者提供的 crystal_name**；價格、珠徑、SKU、stock、notes 可選。不要求現在提供正式 7～14 天 Batch。

照片 → Ingest／Photo QA → Grounding → Caption Basis → A商品貼合／B顏色意境／C風景／D極簡／E日常／F品牌 → Calibration Preview → CALIBRATION_READY_FOR_REVIEW → 等使用者選喜歡／不喜歡。

目前實際商品=0、Instagram POST=0、Media ID=無、CAPTION_STYLE_CALIBRATED=NO。approval_mode=true、auto_publish_without_approval=false、production paused。第一次實物 test publish 仍需日後單獨明確批准。

安全規則與排錯：[Multi-Brand Isolation / Safety](multi-brand-isolation.md)。日常操作：[使用說明](baobao-automation.md)；第一組照片格式：[校準說明](baobao-caption-calibration.md)。
