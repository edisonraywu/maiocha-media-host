# 寶寶礦到了｜實作與驗收報告

驗收日期：2026-09-26，Asia/Taipei。

**READY_FOR_BAOBAO_AUTOMATION = NO**

本機系統、操作入口、文件與測試已完成。41 個新系統測試及 8 個原有狀態機測試通過。原本 maiocha 的 40 個檔案未變動，實際帳號查詢與原有公開圖片驗證成功。尚未完成遠端 workflow 部署、寶寶礦授權、真實商品文案驗收及第一篇 Instagram 測試，因此沒有將 production 標為 ready。

目前為 `approval_mode=true`、遠端 `paused=true`、`production_ready=false`，正式排程與發布歷史都是空的。本次實際 Instagram 發布 POST 次數為 **0**。

BLOCKERS:

1. 既有 GitHub fine-grained PAT 沒有 Workflows 寫入權限，GitHub 已拒絕本次 push。程式完整保存在本機 commit，遠端 main 未改；需要帳號本人提高原 Token 的該 repo 權限。
2. 既有 Meta User Token 的 `me/accounts` 回傳 0 個已授權粉專。缺寶寶礦的確定 username、IG ID、Page ID 與專用 Page Token；必須在同一 Meta App 授權該品牌資產。
3. 工作區沒有寶寶礦真實商品照片。無法誠實驗收「這篇就是在寫這一串」、跑真實內容 Preflight，或發第一篇測試。

## A. 原本專案架構摘要

`New project` 工作區本身不是 Git repository。唯一業務 Git checkout 是 `maiocha-media-host-staging`，使用既有 `edisonraywu/maiocha-media-host` public repository，main 根目錄由 GitHub Pages 提供媒體。

內容、素材與 PowerShell 工具位於 `買房喵查局內容系統`。正式入口 `11_系統工具/Instagram官方發布/同步發布CampaignV2.ps1` 是特定活動組合：6 張輪播、1 Reel、3 Stories，具有固定順序與原品牌限制。

原流程已具 manifest、SHA256、preflight、核准、容器狀態、CSV 發布歷史與不確定結果停止機制。生成採本機／Codex 批次作業，沒有可直接重用的商品照片 grounding 引擎。遠端原有 Actions 只有 Pages deployment，沒有 Instagram cron。

修改前已完成現況盤點與 [implementation plan](baobao-implementation-plan.md)。

## B. 重用哪些既有功能

| 既有元件 | 本次處理 |
|---|---|
| GitHub repository、main、Pages | 沿用，新增 `media/baobao/{content_id}/` namespace |
| GitHub DPAPI 憑證及 AskPass | 重用，不把 Token 寫入程式或輸出 |
| Meta App `1833218008099793` | 沿用同 App 與 Facebook Login／Graph v26.0 |
| container → polling → media_publish | 延伸同一 API 流程，支援一般單圖／輪播 |
| manifest、hash、preflight、history 與不確定結果停止原則 | 品牌化並加入跨程序 GitHub CAS 持久紀錄 |
| 原 maiocha publisher、內容及媒體 | 保留原入口原樣，不移植其固定 Campaign 限制 |

使用 Python 共用 adapter 的理由是原 PowerShell publisher 強制固定組合；直接改掉其前置条件會影響正常活動。沒有新建 repo、Meta App、Hosting 服務或付費 AI API。

## C. 修改哪些檔案

相對本次開始時的 `0d40846`，既有 Git tracked 檔案沒有修改或刪除，都是新增功能。40 個原 maiocha 系統檔案的雜湊完全相同；只在工具旁新增品牌入口。

新增程式的後續修正包括：不可確定的發布結果不宣稱「未發布」、損壞 ICC 檔回報照片問題、以及發布成功後紀錄失敗／程序中斷的防重複測試。

## D. 新增哪些檔案

同一 Git repository 中：

| 檔案 | 用途 |
|---|---|
| `.gitignore`、`.gitattributes` | 排除私人素材與秘密、統一文字格式 |
| `requirements-automation.txt` | Python 依賴 |
| `config/brands/baobao.yaml`、`maiocha.yaml` | 獨立品牌、帳號、文風、排程設定 |
| `automation/__init__.py`、`core.py` | 共用路徑、設定、雜湊、原子寫入、安全錯誤與鎖 |
| `automation/ingest.py` | 每商品獨立 ingest、original、處理圖、縮圖、去重 |
| `automation/schemas.py`、`generator.py` | 結構化 grounding／basis／候選／視覺 QA；本機 Codex provider |
| `automation/qa.py`、`pipeline.py` | 來源綁定、內容 QA、有限重生與 batch prepare |
| `automation/calendar.py`、`preview.py` | 內容日曆與本機 HTML／JSON 預覽 |
| `automation/release.py` | 核准指紋、公開發布包、素材與 QA 完整性 |
| `automation/network.py`、`publisher.py` | 帳號驗證、Meta API、Preflight、Single／Carousel |
| `automation/journal.py`、`operations.py` | 遠端互斥紀錄、防重複、Hosting、排程、歸檔、實測驗收 |
| `automation/connect.py`、`cli.py` | 同 App 授權接入與日常簡單操作 |
| `.github/workflows/automation-ci.yml` | Python CI 測試 |
| `.github/workflows/baobao-publish.yml` | 只讀預生成內容的品牌隔離 cron |
| `tests/test_automation.py`、`test_network_journal.py` | 41 個單元、整合及 dry-run 測試 |
| `docs/baobao-automation.md`、`baobao-acceptance-report.md` | 操作手冊與本驗收報告 |

本機工作區另有：

- `baobao.cmd`、`baobao.ps1`：日常入口。
- `tools/Connect-Baobao.ps1`：不顯示 Token 的授權輸入與環境檔寫入。
- `tools/Deploy-Baobao-Code.ps1`：檢查 remote、秘密與 staged 範圍後安全推送，不 force push。
- `tools/Audit-Baobao-Access.ps1`、`Verify-Maiocha-Unchanged.ps1`：可重跑的權限稽核與回歸驗證。
- `買房喵查局內容系統/11_系統工具/Instagram官方發布/同步發布品牌.ps1`：原工具區的新品牌入口。
- `content/baobao/.env.example`、`product.example.yaml`、inbox、空日曆、空 Preview、history。
- `docs/baobao-implementation-plan.md`、本報告與操作手冊。
- `.local/maiocha-baseline.json`、`maiocha-regression.json`、`baobao-access-audit.json`、`baobao-readiness.json`：本機驗證證據，不提交公開 repo。

## E. baobao 最終資料夾結構

```
New project/
  baobao.cmd / baobao.ps1
  content/baobao/
    .env.example
    product.example.yaml
    inbox/{商品資料夾}/
      商品照片.jpg
      product.yaml                  可省略
    items/{content_id}/              ingest 後產生
      originals/
      processed/
      item.json
      product_grounding.json
      caption_basis.json
      caption_candidates.json
      selected_caption.txt
      vision_qa.json
      caption_qa.json
      preflight.json
      revisions/
    calendar/calendar.yaml
    calendar/calendar.json
    preview/preview.html
    preview/preview.json
    history/published-history.json
    archive/{content_id}/            成功後 sync 產生
  maiocha-media-host-staging/
    automation/
    config/brands/{baobao,maiocha}.yaml
    media/baobao/{content_id}/        核准選圖後產生
    releases/baobao/{content_id}/     caption 與 manifest
    .github/workflows/
    tests/
```

遠端另外有同 repo 的 `automation-state` 分支，`state/baobao.json` 保存 pause、正式啟用證據、queue、發布 intent、Media ID 與歷史。原始圖片、product.yaml、完整 grounding 與候選文案不公開。

## F. Brand Config

- 品牌：寶寶礦到了，核心句「寶寶，你的礦到了。」
- 原則：商品本人決定內容；品牌只決定怎麼說。
- `approval_mode: true`；remote journal 目前暫停，production 未啟用。
- `target.instagram_user_id / facebook_page_id / username` 目前刻意留空，不能猜。
- `timezone: Asia/Taipei`；暫定週二／四／六 20:00，每週 3 篇，`defaults_need_review: true`。
- 預設最多輪播 10 張、每次 cron 最多 1 篇、逾時 24 小時停止待重排。
- 每品牌有自己的 config、env 名稱、content、namespace、calendar、manifest、preflight 與 history；新入口對 maiocha 寫入命令停止，導向保留的原入口。

發布頻率是明示的可修改樣板，不是演算法最佳時間。新品、貓咪與小知識沒有完整可驗證素材時會阻擋，不會為了輪替硬生成。

## G. Image Grounding 流程

每個資料夾獨立識別，metadata 七欄全可省略。先檢查圖片並保存不可覆寫的 original、來源 hash；完全相同照片去重，建立等比例 JPEG 1080×1350 與縮圖，不重畫、不改礦色或透明度。

本機 Codex 分別讀取每件商品照片，逐張檢查清晰度、顏色可靠性、主體、構圖、全貌、細節、上手及封面適合度。保存使用者資料、可見色彩／光／表面／紋理、unknown fields、逐圖證據與選圖。透明感只是照片視覺描述。

品質不足或多商品混淆時留下問題照片與補拍建議，狀態為 `NEEDS_INFO`。沒有礦名仍可繼續生成「這一串」，不靠照片鑑定礦種。來源變動会使舊核准及排程失效。

**實測範圍：**圖片處理與來源隔離已用合成 fixture 驗證；尚無真實商品可驗收 AI 看圖正確性。

## H. Caption Generation 流程

保存 grounding 後，才能建立 `caption_basis.json`，記錄主／次色、光、氛圍、使用者提供的礦種、候選／排除意境與理由。再產 A 商品貼合、B 意境、C 短句三版，保存選擇理由與 selected caption。

重要事實有來源 references：手動欄位、視覺 fact ID 或 basis 意境。不得用文風覆蓋商品，也不能在 hashtag 偷加礦名或功效。沒提供的售價、珠徑、產地、品質等級與療效不可補猜。

使用已登入 ChatGPT 的 Codex CLI，僅在本機 prepare 執行。設有 ContentGenerator abstraction，拒絕 API key 模式；沒有啟用新的付費 API。GitHub 發布流程不呼叫 AI。實際 Codex CLI 的商品生成尚待照片驗收，單元測試使用假 provider，兩者沒有混稱。

## I. Caption QA 流程

先做來源與規則檢查，再獨立重新讀圖，核對顏色、光、透明／表面、名字、價錢、珠徑、未標註斷言、意境、content_id、圖片一致性與「是否在寫這一條」；任何關鍵 FAIL 都不能 READY。

最多重新生成一次；仍失敗即 `NEEDS_INFO`。QA、caption、圖片、metadata、schedule、target 都被 hash 綁定。改 caption 需 `review-caption` 重新看圖 QA，保留使用者改後原文，重新核准才可安排。

## J. Scheduler

先為 READY 商品建立可預覽日期；依色系、hook、結構、構圖與 SKU 最近使用狀況挑選，重跑保留既有日期。核准模式需明確 approve，schedule 才會 Hosting、線上 Preflight、寫入遠端正式 queue。

queue 綁定精確 release hash，撤回／修改後舊發布包不能繼續使用。auto 模式省略人工 approve，仍須 QA、線上 Preflight 與真實首次測試。排程發布無即時 AI 依賴。

GitHub cron 每 15 分鐘檢查；平台可能延遲，不能保證精準到分鐘。超過 24 小時的項目停止，避免突然補發整批。[GitHub 官方限制](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

## K. Hosting

沿用 `https://edisonraywu.github.io/maiocha-media-host/`，寶寶礦限定 `/media/baobao/{content_id}/`。公開包僅含核准的選圖、正式 caption、manifest 與必要 QA 證明。

Preflight 對每張做公開 GET、Content-Type、JPEG 格式、尺寸、大小、SHA256、brand namespace 與 manifest 一致性檢查。Meta 實際取圖能力仍需建立容器及第一篇實測才可確認；HTTP 200 不冒充 Meta 已取圖。

本次真實驗證的是原 maiocha 圖片：200、`image/jpeg`、SHA256 相符。baobao 尚無核准實物圖片可託管。

## L. Meta API、帳號門檻與防重複

沿用原 App 和 Graph v26.0。每次發布核對 requested brand、config target、專用 env、Page→IG ID、實際 username、caption manifest 與 asset namespace。任一不符即 STOP，不會 fallback 到 maiocha credentials。

Single／Carousel 具備統一方法；Reel／Story 介面目前明確回報未啟用，沒有阻擋 Feed／Carousel。舊 maiocha 的影片／Story 程式保留。

GitHub journal 以 compare-and-swap 保證單一 owner，先保存 container intent／publish intent 才送請求。成功保存 content_id、Media ID、時間、target、asset／caption／source hash。已 PUBLISHED 自動拒絕，只有明確 `--force-republish` 才可再走全部門檻。

GET 只做有限重試；有副作用的 POST 不盲目重送。不確定是否成功、runner crash 或成功後寫回失敗均停止，透過實際 Media ID reconcile。FAILED 的明確可安全重試情況最多 2 次。

## M. GitHub Actions

已完成 CI 與 baobao cron workflow，品牌獨立 concurrency，失敗不呼叫或改動 maiocha。`workflow_dispatch` 預設 dry-run；PAUSE variable 與遠端 pause 均可擋發文。Actions 的 GITHUB_TOKEN 只用於同 repo 持久紀錄。

**部署尚未成功。**GitHub 拒絕既有 PAT 寫入 workflow。本機 commit 已保存；遠端 main 仍是本次開始的 `0d40846`。不 force push，不宣稱雲端排程已上線。

遠端 `automation-state/state/baobao.json` 已實際建立並透過 sync 讀回，保持暫停及未啟用。這不等於 workflow 已部署。

## N. Secrets：已有與還缺

| 狀態 | 項目 |
|---|---|
| 已有、本次唯讀可用 | maiocha 的專用環境設定、Page Token、IG／Page／username；原 Meta App Secret／User Token DPAPI；GitHub DPAPI credential |
| 缺少本機 baobao 設定 | `BAOBAO_IG_USER_ID`、`BAOBAO_PAGE_ID`、`BAOBAO_IG_USERNAME`、`BAOBAO_PAGE_ACCESS_TOKEN` |
| GitHub Secrets 內容尚不能確認 | 現有 PAT 缺 Secrets 讀取權，不能把「讀不到」宣稱為「沒有」；啟用前需確認上述四個品牌 Secret |
| 平台自動提供 | Actions 的 `GITHUB_TOKEN`，不須手動建立 |

`.env`、DPAPI、原始商品與私人分析皆排除提交；錯誤只輸出安全代碼，不印 token 或 provider 原始錯誤。報告沒有 Secret 值。

## O. Dry Run 與回歸結果

| 驗證 | 結果 |
|---|---|
| 新系統 unittest | **41／41 通過**；命令 `..\.venv-baobao\Scripts\python.exe -m unittest discover -s tests -v` |
| 批次流程 | 隔離 fixture 一次 20 組、三候選、QA、日曆、Preview 通過；非真實商品成果 |
| 重要阻擋 | A／B metadata、錯品牌／username／IG、錯色、未知礦名／價格／珠徑、hosting failure、missing token、錯 namespace 通過 |
| 發布與 durable journal | carousel 組合、重複防止、CAS 衝突、lost response、publish timeout、runner crash、pause 中途、寫回失敗不重發通過 |
| dry-run | fixture 完整發布路徑 0 POST；真實空 inbox CLI 回傳 `NO_DUE_CONTENT`／0 POST |
| 真實 CLI | Windows 入口、status、prepare 空批次、preview、remote journal init／sync 已執行 |
| Preview | 本機瀏覽器已實際開啟並看過截圖；目前顯示空 inbox，沒有捏造商品 |
| maiocha 原檔 | **40 個雜湊相同**，PowerShell 語法檢查無錯 |
| maiocha 原狀態機 | **8／8 通過**，在複本 fixture 執行，不修改正式 campaign state |
| maiocha 真實唯讀查詢 | Page→IG 及 `maiocha.lab` 相符；回傳 media_count=0，不宣稱舊歷史貼文目前仍存在 |
| maiocha 真實 Hosting | 公開圖片 200、JPEG MIME、SHA256 相同 |

本機證據：`.local/maiocha-regression.json`、`.local/baobao-access-audit.json`、`.local/baobao-readiness.json`。新測試主要是受控假 Meta／GitHub transport；不等於 Instagram 實際 POST 成功。

## P. Test Publish

**尚未執行。**沒有 baobao 憑證及實物照片，不能冒用 maiocha、猜帳號或用測試 fixture 假裝實際商品發文。尚無寶寶礦 Media ID。

已實作一次單張 Feed 的測試模式、dry-run、Preflight、取得 Media ID、中文 caption 核對、baobao Media 列表確認、maiocha 不含該 Media ID 檢查，以及圖片人工／Codex 真實目視確認旗標。必須取得這些真實證據後，verify-test 才會設定 production_ready，並再次 pause，最後明確 resume 才進日常發布。

## Q. 還需要你本人完成什麼

1. **GitHub 權限：**開 [Fine-grained personal access tokens](https://github.com/settings/personal-access-tokens)，編輯原媒體託管 Token，僅限 `maiocha-media-host`，保留 Contents write 並增加 `Workflows: Read and write`。若讓程式代存 Secrets，增加 `Secrets: Read and write`；也可本人在 repo Settings → Secrets and variables → Actions 設四個品牌 Secret。不要把 Token 貼到對話。
2. **Meta 本人授權：**開 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)，選原 `MaiOcha Lab Automation`，Get User Access Token／Generate Access Token → 編輯資產權限，加入寶寶礦 Page 及已連結 IG、保留 maiocha；授予 `pages_show_list`、`pages_read_engagement`、`instagram_basic`、`instagram_content_publish`。複製 User Token 到 `tools/Connect-Baobao.ps1 -Username 實際IG帳號` 的隱藏輸入；程式核對並存專用 `.env`。不用重新連結 FB↔IG，不建新 App。
3. **實物與帳號名稱：**提供寶寶礦確定的 @username，在 `content/baobao/inbox/2026-10-001/` 放一張真實清楚商品照，product.yaml 可不填。首次只測單圖一篇。

以上不是重複請求一般操作核准：第一項是 GitHub 實際拒絕的 credential 權限，第二項是缺少該資產的 Meta 本人授權，第三項是無法代造的實物證據。補齊後可直接接續現有系統，無需重做架構。

權限更新後執行 `tools/Deploy-Baobao-Code.ps1` 推送已保存本機 commit。授權、照片到位後，依 [操作手冊第 11 節](baobao-automation.md#11-第一次只測一篇) 完成一篇實測及驗收。

## R. 以後每次實際怎麼使用

系統正式驗收啟用後，每次：

1. 一條實物一個 inbox 資料夾，可一次放 10～30 條；product.yaml 有資料才填。
2. 在工作區執行 `baobao.cmd prepare`，逐條讀圖、grounding、basis、三候選、QA、選圖、日曆。
3. 開 `content/baobao/preview/preview.html`，確認這篇確實在寫這一串。
4. 執行 `baobao.cmd approve --all`，再 `baobao.cmd schedule --all`；後者會完成 Hosting、Preflight 與正式排程。
5. 之後 GitHub 自動讀預生成內容發布。執行 `baobao.cmd sync` 同步 Media ID／history／本機歸檔；雲端 journal 已在發布時保存。
6. 隨時 `baobao.cmd pause` 暫停，`resume` 恢復；穩定後 `mode auto` 才省略人工核准。

修改文案、日期、取消、立即發布、失敗處理、Token 更新、approval／auto 全部步驟見 [非工程師操作手冊](baobao-automation.md)。

**READY_FOR_BAOBAO_AUTOMATION = NO** — 在上述三項 blocker 與一篇真實測試解決前維持暫停。
