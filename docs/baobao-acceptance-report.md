# 寶寶礦到了｜照片準備與人工批准驗收

更新：2026-09-26，Asia/Taipei。延續原 commits，沒有重建專案或回滾。

**READY_FOR_PHOTO_ONLY_WORKFLOW = NO**

GitHub checkpoint 已解除，程式及 Actions 已部署。新的人工批准流程已通過本機與遠端測試；尚缺 baobao Meta 資產授權、真實商品內容驗收及你對第一篇測試的明確批准。本次真實 Instagram POST 為 **0**。

固定模式：`approval_mode=true`、`auto_publish_without_approval=false`。遠端 journal：`paused=true`、`production_ready=false`、queue 0、published items 0。

BLOCKERS:

1. **Meta 資產授權與帳號／Secrets：**既有 User Token 的實際 `me/accounts` 回傳 0 個粉專。四項所需 permissions 已 granted，但沒有寶寶礦可核定的 Page／IG／username／Page Token，因此尚不能設定四個品牌 Secrets。
2. **真實商品：**目前 inbox 無實際商品照片。照片品質、AI grounding、商品貼合文案與公開 baobao Hosting，尚不能以真實商品驗收。
3. **審核與第一篇實測：**必須先提供真實 Preview，等你明確說「這篇可以測試發」，才能做正式 Preflight 與一篇測試。尚無 baobao Media ID。

## A. GitHub 狀態

**PASS。**既有 fine-grained PAT 權限更新已實際生效。原 `6a89988`、`a668131` 已成功推送；本次功能更新 commit 為 `e50e0933dd896965cdb30d32b3f91718831ec0fd`，位於同一 `edisonraywu/maiocha-media-host` main。後續驗收文件更新不改動此已測試的程式。

保留原 repo、Meta App、GitHub Pages 與 maiocha 入口。沒有 force push、回滾或新建另一套服務。tracked／待提交文字及新增 commits 的秘密模式掃描通過，沒有 `.env`、DPAPI 或 Token 入庫；稽核只記錄檔名與結果，不輸出秘密值。

## B. GitHub Actions 狀態

**已部署且實際成功：**

| 驗證 | 結果與證據 |
|---|---|
| 新版 CI，Ubuntu／Python 3.12 | [PASS：36225529967](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36225529967)，程式 commit `e50e093` |
| 新版 baobao 手動 Dry Run | [PASS：36225579227](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36225579227)，程式 commit `e50e093` |
| 同 repo Pages deployment | [PASS：36225529431](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36225529431) |
| Actions 實際 GITHUB_TOKEN 讀取 journal | artifact `journal_access=PASS` |
| 人工批准／暫停設定 | artifact `approval_mode=true`、`auto_publish_without_approval=false`、`paused=true` |
| 真實空內容 Dry Run | `NO_DUE_CONTENT`、`api_post_requests_sent=0` |

已下載並檢視上面 dry-run 的真實 artifact，保存於本機 `.local/baobao-actions-36225579227.json`。這是雲端連通與安全驗證，不冒充真實商品完整 Dry Run。

baobao workflow 只讀 BAOBAO Secrets、品牌 config、releases 與品牌 journal，獨立 concurrency，不呼叫 maiocha publisher。原遠端沒有 maiocha Instagram workflow，只有共用 Pages deployment；不能宣稱「已執行一個原本不存在的 maiocha IG workflow」。原 maiocha 本機發布程式已另做回歸。

## C. Meta 狀態

**MANUAL_ACTION_REQUIRED。**沿用 `MaiOcha Lab Automation`（App ID `1833218008099793`），Facebook Login／Graph v26.0。已重新 inspect 原流程：DPAPI 保存 App Secret 與 User Token；由原 App 換長效 User Token，再取得 Page Token，檢查 Page→IG→username。

2026-09-26 15:05 的唯讀 API 稽核：`me/accounts.data=[]`，沒有後續分頁；`pages_show_list`、`pages_read_engagement`、`instagram_basic`、`instagram_content_publish` 為 granted。這代表目前無法從該授權列出寶寶礦資產，不代表 FB↔IG 沒連好。需要本人重新選擇 App 可存取的 Page／IG。

不新建 App，不要求重做 FB↔IG 連結。新接入工具使用原 App Secret 換 token、檢查必需 permissions，核對指定 username，只在 API 驗證成功後寫入 baobao 設定。

## D. Secrets 狀態

GitHub Secrets API **PASS**；實際名稱列表為空，Actions 的四個品牌 Secret presence 也都是 false：

```
BAOBAO_PAGE_ID
BAOBAO_IG_USER_ID
BAOBAO_IG_USERNAME
BAOBAO_PAGE_ACCESS_TOKEN
```

已實作 `baobao secrets-sync`：先確認專用 credentials 與 Meta 帳號，再以 GitHub repository public key／libsodium sealed box 加密，僅寫入這四個 BAOBAO 名稱，最後讀取名稱 metadata 確認，不讀回或印出值。[GitHub 官方加密方法](https://docs.github.com/en/rest/guides/encrypting-secrets-for-the-rest-api)

`tools/Connect-Baobao.ps1` 完成安全隱藏輸入與 API 驗證後，會自動接續 Secrets 同步。尚未有 baobao 真實值，因此本次沒有虛填 Secret，也未複製 maiocha Token 代用。

## E. Account Verification

**baobao 尚未通過真實帳號驗證。**config 的 Page ID、IG ID、username 保持 null，不能猜。

已實作並測試的發布門檻：requested brand、config、專用 env、真實 Page→IG→username、caption／asset namespace、current content_id、完整性 hash、QA、人工批准、history、pause、schedule；任何不符即 DO_NOT_PUBLISH。建立容器後、真正 `media_publish` 前再核对帳號與 pause。

本次唯讀 maiocha 驗證仍正確：Page→IG 與 `maiocha.lab` 相符。未進行真實 baobao PREVIEW_PREFLIGHT／PUBLISH_PREFLIGHT，亦未測試發布。

## F. Inbox workflow

一条商品一個 `content/baobao/inbox/{folder}/`，product.yaml 七欄全部選填。新增真實照片後，`prepare` 或「幫我處理這批寶寶礦照片」會批次處理；不會把提供照片當作批准。

狀態為 `DRAFT → PREPARED → READY_FOR_REVIEW → 停止`。QA 不通過為 NEEDS_INFO。一次 20 組的隔離 fixture 測試通過，原照片保留、去重與縮圖測試通過；真實 10～30 組仍待你提供。

## G. Grounding

先讀每一件商品實拍，保存獨立 product_grounding。包含使用者資料、主／次色、明暗、照片透明感、表面、紋理、對比、光、氣質、上手／平放／近拍／全貌與未知欄位，逐圖留 evidence。

保留原圖，不生成假商品、不改顏色或透明度。圖片處理與跨商品隔離已測試；**真實 AI 觀察品質尚未驗收**。

## H. Caption

Grounding 後建立 basis，保存意境候選、排除理由、user-provided facts 與 unknown facts，再產 A 商品貼合、B 意境、C 短句三版，依實物選定。沒有 metadata 不猜礦名、售價、珠徑、產地、處理、等級或功效。

本機 Codex 批次預生成，不新增付費 API；Actions 發布時不呼叫 AI。`revise <content_id> --instructions ...` 只重寫該篇 caption，保留 grounding／basis，不重新處理其他商品。**尚無真實商品 caption 可交付或聲稱內容品質已 PASS。**

## I. Caption QA

規則 QA 加獨立讀圖 QA，驗證顏色、光、透明／表面、意境、metadata 來源、礦種、價錢、珠徑、產地／療效斷言、content_id 及是否只適用眼前商品。失敗最多重新生成一次，仍失敗 NEEDS_INFO。

錯色、未知礦種／價格、泛用文案、跨商品等攔截測試通過。沒有真實圖片時不把 fixture PASS 寫成真實 Caption QA PASS。

## J. Carousel

依清楚可用照片選 Single／Carousel，最多 10 張，不強制湊六張。保存封面與照片順序／photo_id。

`reorder <content_id> ...` 可只修改選圖或順序；不重寫 caption，重新圖片 QA，撤回舊批准。Single、Carousel 容器組合、順序修改及跨商品隔離測試通過。

## K. Preview、Hosting 與日曆

Preview 已更新：Content ID、商品資料夾、封面、所有選圖與順序、Grounding、basis、A／B／C、Selected Caption、metadata、未知欄位、預計帳號、形式、狀態與建議日期。

本機 `content/baobao/preview/preview.html` 已重新產生，目前空 inbox。沒有用假照片生成可供發布的示範內容。

日曆只給 `PROPOSED_SCHEDULE`，不能自行批准或寫正式 queue。PREVIEW_PREFLIGHT 唯讀檢查本機資料與 account；未公開 Hosting 時明確列 `PENDING_EXPLICIT_APPROVAL`。因 Pages 會把照片與文案公開，目前公開 Hosting 留到你明確批准後；使用同一 `/media/baobao/{content_id}/`，不偷用 maiocha asset。

批准後才完整 Hosting／公開 GET／MIME／hash／PUBLISH_PREFLIGHT。真正 Meta 取圖與一篇測試仍待授權、實物和明確同意。原 maiocha Hosting 本次回傳 200、image/jpeg、hash 相符。

## L. Approval Gate

**程式與測試 PASS。**已取消 baobao 自動核准路徑，`mode auto` 明確拒絕。`prepare`、`preview`、`calendar`、review preflight 都不會寫入 approval 或正式 queue。

只有明確 approve 指令會建立 `approval_state=APPROVED`、manual mode、時間、來源及涵蓋內容／照片／QA／日期／target 的指紋。直接呼叫 publisher、test publish、queue 或 journal claim 仍必須通過批准；重算 release hash 不能沿用被修改內容的舊批准。

測試包含 DRAFT／PREPARED／READY_FOR_REVIEW／NEEDS_INFO 直接發布拒絕、auto flag 繞過拒絕、查看 Preview 不等於批准、修改單篇撤回批准。第一次 test publish 也不例外。

## M. Pause 與防重複

遠端實際保持 paused=true，Actions artifact 確認已讀到。`PAUSE_ALL_BAOBAO_PUBLISHING` 環境變數／同名 Actions variable 及 journal pause 都保留。

程序中途 pause 阻止 `media_publish`、已發過不能重發、CAS 競爭、容器／發布逾時、runner crash、成功後紀錄失敗等測試通過。真實 publish history 目前空的。未批准內容無論 pause 是否解除都不能發。

## N. maiocha regression

**PASS，2026-09-26 14:52。**

- 原有狀態機 **8／8 PASS**，在隔離複本執行。
- **40 個原檔雜湊不變**，PowerShell 語法檢查沒有錯誤。
- 真實 Page→IG→`maiocha.lab` 正確，原公開圖 200／JPEG／SHA256 相同。
- 本次 Meta POST 0；不宣稱重新替 maiocha 發過貼文。

證據：`.local/maiocha-regression.json`。沒有修改原 maiocha publisher、config、內容、manifest 或 history。

## O. baobao tests

**57／57 PASS**（本機 Windows／Python 3.12），新版 GitHub Ubuntu CI 也成功。原 41 項保留其安全覆蓋，其中原 auto-mode 允許測試依新需求改為「不得自動核准」。新增覆蓋：

- Prepare 必停在 review，不建立 queue／approval。
- 未批准的正常與測試發布都在任何網路操作前停止。
- 修改日期／內容不可沿用舊批准。
- Preview 三版／順序／資料夾／target 完整。
- 只改指定商品 caption；只調順序不重寫文案。
- Secrets 使用 sealed box、只允許四個品牌名稱，不輸出值。
- 同原 Meta App 接入；缺發布 permission 不寫 credentials。
- Actions 診斷只輸出 Secret presence 與 pause，不輸出值。

fixture 使用合成圖片與假 Meta／GitHub transport，並非實際商品或真實 Instagram 發布驗收。真正線上證據另見 B／C／N。

## P. 還需本人完成什麼／下一個 checkpoint

**現在只需要完成 Meta 授權：**

1. 開 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)，選 `MaiOcha Lab Automation`／App ID `1833218008099793`。
2. Get Token → Get User Access Token／Generate Access Token，登入原 Facebook 身分。
3. 在編輯資產存取權時選「寶寶礦到了」Page 及其已連結的實際 IG，保留 maiocha。
4. 勾 `pages_show_list`、`pages_read_engagement`、`instagram_basic`、`instagram_content_publish`，Continue／Allow。
5. 複製 User Access Token 到下列工具的隱藏輸入；不要貼聊天：

```powershell
.\tools\Connect-Baobao.ps1 -Username 寶寶礦的實際IG帳號
```

工具成功後，會安全存入 local `.env`，並直接加密設定前述四個 GitHub Secrets，不需要你逐一貼值。

6. 回覆「Meta 授權已完成」並提供實際 @username（不是 Token）。接著我會做真實帳號與 Secrets／Actions 驗證，再請你提供第一組實物照片。

照片準備後先交付 READY_FOR_REVIEW Preview，等待你明確說「這篇可以測試發」。尚未完成 test publish、Media ID、實物圖片與中文驗證。即使成功，也維持人工核准模式。

平常操作只需看 [「平常我到底要怎麼用」](baobao-automation.md#平常我到底要怎麼用)。

**READY_FOR_PHOTO_ONLY_WORKFLOW = NO**

**READY_FOR_BAOBAO_AUTOMATION = NO**
