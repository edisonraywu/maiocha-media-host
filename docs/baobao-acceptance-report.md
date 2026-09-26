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

安全修復 commit：`0b3ee4ed06080601252832cfeac70bc3d8715c50`，已推送至現有 `main`，沒有 force push。以下均為該版本的實際結果。

| 項目 | 結果與證據 |
|---|---|
| GitHub deployment | PASS；安全修復 commit 已包含於 remote main，後續驗收紀錄僅修改文件；原商品素材、brand config、baobao 發布 workflow 無變更 |
| CI | PASS；[36250094251](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36250094251)，Python 全套及 Windows／Linux PowerShell 三個 jobs 全部 success |
| Pages | PASS；[36250093766](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36250093766) 部署成功；部署後再次 GET 現有正式圖片，HTTP／image/jpeg／SHA-256 與本機一致 |
| Workflow validation | PASS；GitHub 已接受新 workflow，push CI 及手動 dry-run 都實際成功執行 |
| baobao live dry-run | PASS；[36250104496](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36250104496)，`VALIDATION_PASS`、`NO_DUE_CONTENT`、Instagram POST=0 |
| Meta / Account Gate | PASS；由 Actions 使用實際 Secrets，GET 驗證 Page 日常收藏所 `1348149615047101` → IG `17841431857348052` → `babycrystal.tw`；API access 與帳號閘門通過 |
| Secrets | PASS；GitHub API 可列出四個 BAOBAO Secret 名稱，Actions 確認存在且真實 API 可用；沒有輸出 Secret 值 |
| Durable pause | PASS；遠端 `state/baobao.json` 保持 `paused=true`、`production_ready=false`，items=0、queue=0；未 Resume |
| Approval | PASS；Actions 驗證 `approval_mode=true`、`auto_publish_without_approval=false`；沒有商品獲得批准 |
| Secret audit | PASS；64 份公開文字檔與既有 commit 掃描無命中；另唯讀檢查 164 份私人報告／Preview／文件／輸入提示 log，無 Secret 洩漏；`.env` 未進版本庫 |

沿用 MaiOcha Lab Automation（1833218008099793）及 Facebook Login。已驗證的帳號為 maiocha.lab／藍屋生活誌與 babycrystal.tw／日常收藏所；BAOBAO 四個 Secrets 名稱保持獨立。部署階段只讀取 Secret 存在狀態，不輸出值。

## 修復後唯讀 Multi-Brand Audit

四個 maiocha Campaign 的 40 份來源／hash／URL／object key／namespace 全部通過；每個 Campaign 都以記憶體副本重現「只換成 baobao URL」，四次全部被拒絕。此複查寫檔=0、Instagram request=0。12 份已部署工具與版本庫內容一致。

| 檢查範圍 | 隔離結果 |
|---|---|
| Content、inbox、Batch、商品 metadata、content_id、照片 binding | PASS；baobao 使用自己的 content 根目錄、品牌 ID、逐商品 manifest／hash；目前尚無真實商品 |
| Grounding、Caption Basis、captions、六種 Style、Style Profile | PASS；品牌 context 先驗證；maiocha 不讀 baobao Profile；正式 Profile 尚未建立 |
| Preview、calibration、approval | PASS；校準只在 baobao；校準與一般查看 Preview 不產生發布批准；跨品牌 approval 拒絕 |
| Assets、media、Hosting URL、remote object key、cache | PASS；共享 repository 內依 policy／release 分隔；更換任何快取 identity 會失效 |
| Publisher、scheduler、history、archive、duplicate protection | PASS；各自 target／journal／queue／history，跨品牌紀錄及排程拒絕；maiocha 原流程保留 |
| Pause、Secrets、IG／Page mapping | PASS；各自設定與帳號，沒有環境變數名稱覆蓋；baobao 仍 paused |
| Shared engine、launcher、write／delete／cleanup | PASS；共用安全核心讀明確 scope，通用入口必須指定品牌；跨品牌上傳、覆寫、刪除、清理拒絕 |

`SHARED`：repository 基礎設施、`automation/` 共用元件、`safety/`、CI／Pages。
`MAIOCHA_ONLY`：`買房喵查局內容系統/`、已登記的 `media/maiocha-<campaign>/`、`legacy/maiocha/` 部署來源。
`BAOBAO_ONLY`：`content/baobao/`、`config/brands/baobao.yaml`、`media/baobao/`、`releases/baobao/`、`state/baobao.json`。
`POSSIBLE_MIXING_RISK`：原三項風險均已修復並有回歸案例；目前沒有未解決的 CRITICAL／HIGH 或會跨品牌發布／覆寫／批准的問題。舊 repository 名稱屬歷史命名，不構成 namespace 混用。

## 下一個 checkpoint

工程驗收完成後只等待 **1～3 條真實校準商品，每條約六張照片及使用者提供的 crystal_name**；價格、珠徑、SKU、stock、notes 可選。不要求現在提供正式 7～14 天 Batch。

照片 → Ingest／Photo QA → Grounding → Caption Basis → A商品貼合／B顏色意境／C風景／D極簡／E日常／F品牌 → Calibration Preview → CALIBRATION_READY_FOR_REVIEW → 等使用者選喜歡／不喜歡。

目前實際商品=0、Instagram POST=0、Media ID=無、CAPTION_STYLE_CALIBRATED=NO。approval_mode=true、auto_publish_without_approval=false、production paused。第一次實物 test publish 仍需日後單獨明確批准。

安全規則與排錯：[Multi-Brand Isolation / Safety](multi-brand-isolation.md)。日常操作：[使用說明](baobao-automation.md)；第一組照片格式：[校準說明](baobao-caption-calibration.md)。

## 最終工程狀態

```text
MULTI_BRAND_FILE_ISOLATION = PASS
SAFE_FOR_BAOBAO_CALIBRATION_PHOTOS = YES
READY_FOR_BATCH_PHOTO_WORKFLOW = YES
CAPTION_CALIBRATION_SYSTEM_READY = YES
WAITING_FOR_CALIBRATION_PRODUCTS = YES
```

這些狀態表示工程已可接收真實校準照片，並停在私人 Calibration Preview 等待風格回饋；不表示已校準品牌 Style、已驗收真實商品文案、已完成 test publish，或允許跳過逐篇批准。正式 Batch 的 Caption finalization 仍須先完成 Style Calibration。
