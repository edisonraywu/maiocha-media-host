# 寶寶礦到了｜照片準備與人工審核

系統固定使用 `approval_mode=true`、`auto_publish_without_approval=false`。**提供照片、看 Preview、請我準備或先排好，都不等於批准發布。第一次測試也要你明確同意。**

## 平常怎麼用

1. **把照片給 Codex。**同一條素串的照片放在同一組，不同商品分清楚；有商品資料就附上，沒有也可以。
2. **說「幫我處理這批寶寶礦照片」。**我會整理可存取的附件、逐條觀察實物、寫三版文案、QA、選封面與輪播順序。
3. **等我交付 Preview。**內容停在 `READY_FOR_REVIEW`，讓你一次看整批。
4. **不喜歡就指定修改。**例如「BB001 改短一點」或「這篇第二張和第四張交換」，只改該篇，再交給你審核。
5. **你明確說「這幾篇可以發」。**只批准你指定的內容；第一篇測試也需說「這篇可以測試發」。
6. **系統才安排或發布。**讀取你審核過的照片與文案，完成發布前檢查，成功後記錄 Media ID 並歸檔。

若附件無法由工作區讀取，才會請你放到指定 inbox；不需要先研究下方技術細節。

## 平常我到底要怎麼用

1. **照片放哪：**`content/baobao/inbox/`。
2. **一條商品一個資料夾：**例如 `inbox/BB001/` 放這一串的所有實拍，再用 `inbox/BB002/` 放下一串。一次 10～30 組也可以。
3. **商品資料可不填：**`product.yaml` 完全選填。不知道礦名、價錢或珠徑就留空，系統不猜。
4. **叫我 Prepare：**告訴我「幫我處理這批寶寶礦照片」。我會逐件讀圖、寫三版文案、QA、選封面／輪播，最後回報幾篇等待審核。
5. **Preview 在哪：**雙擊 `content/baobao/preview/preview.html`。你會看到商品、照片順序、觀察、意境理由、三版文案、選定文案和狀態。
6. **改某一篇：**說「BB001 文案短一點」、「不要那麼夢幻」或「BB001 第二張换第四張」。只修改對應商品，再回到等待審核。
7. **批准：**明確說「BB001 這篇可以發」並指定要發的項目。第一篇測試請說「這篇可以測試發」。我才會 approve、Hosting、發布前檢查，再安排或發布；不會自行 approve-all。
8. **取消：**說「取消 BB001」。已送出或結果不確定的貼文要先查結果，不能假裝取消成功。
9. **全部暫停：**說「暫停寶寶礦發布」。不影響買房喵查局；恢復也不會把未批准的商品變成已批准。

## 照片與 product.yaml

```
content/baobao/inbox/
  BB001/
    IMG_001.jpg
    IMG_002.jpg
    product.yaml       可省略
  BB002/
    IMG_003.jpg
```

可從 `content/baobao/product.example.yaml` 複製。七欄全可留空：

```yaml
product_name:
crystal_name:
price:
bead_size:
stock:
sku:
notes:
```

如果你提供 `crystal_name: 海藍寶` 才可正式寫海藍寶；沒提供就寫「這一串」。不從照片猜產地、礦種、珠徑、售價、等級、處理方式、證書或功效。

支援 JPEG、PNG、WebP、TIFF。HEIC 如無解碼器，請先匯出 JPEG。每資料夾最多 50 張，正式選圖最多 10 張；差照片不湊輪播。原圖保留不覆寫，只做方向校正、ICC 轉 sRGB、等比例縮放、平台尺寸留白與格式轉換，不重畫商品或改礦色／透明度。

## 系統如何逐件準備

`DRAFT → PREPARED → READY_FOR_REVIEW → 停止`

先 ingest、去重與縮圖，逐张分析照片，保存 `product_grounding.json`。再保存 `caption_basis.json`，記錄主／次色、光感、意境選擇與排除理由、手動事實及未知欄位。最後產 A 商品貼合、B 意境、C 短句三版，依商品挑选，獨立重新看圖 QA。

照片透明感只表示視覺外觀，不是寶石鑑定。主要顏色、光、礦名、價格、珠徑、來源、功效、商品 ID 任一關鍵錯誤，都不能通過。最多再生一次，仍失敗就 `NEEDS_INFO`，並列問題照片與補充建議。

文案在本機批次預生成，使用已登入 ChatGPT 的 Codex CLI 額度，沒有新增付費 API。GitHub 到時間只讀保存好的文案與選圖，不臨時呼叫 AI。

## 審核畫面、Hosting 與兩階段 Preflight

Preview 包含商品資料夾、Content ID、預計 target account、照片順序與 photo_id、封面、Grounding、Caption Basis、A／B／C、Selected Caption（含已使用的 hashtags）、形式、狀態和建議日期。

- **PREVIEW_PREFLIGHT：**檢查本機商品／文案／照片完整性、命名空間、帳號設定與可用 API。未公開 Hosting 時明示 `PENDING_EXPLICIT_APPROVAL`，不假裝已通過公開 URL 驗證。
- **PUBLISH_PREFLIGHT：**明確批准後，Hosting 上傳同一 Pages 的 `/media/baobao/{content_id}/`，驗證公開 GET、MIME、SHA256、帳號、token access、批准指紋、schedule、pause、history、防重複，全部通過才可發。

原圖、product.yaml、完整內部分析與私人 Preview 不放公開 repo。因 Hosting 會把商品與正式文案公開，目前先準備本機資料，等你明確批准後才對外上傳；這不影響先看 Preview。

`READY_FOR_REVIEW` 不等於 APPROVED。修改照片、文案或日期會撤回舊排程／核准，回到待審核。Publisher、queue 與 test publish 都檢查批准紀錄，改設定成 auto 也不能繞過。

## 自己操作時的簡單指令

在 `New project` 工作區開終端機：

```powershell
.\baobao.cmd prepare
.\baobao.cmd preview
.\baobao.cmd status
```

只有你確定批准後才執行下面兩個指令，或明確叫我代為執行：

```powershell
.\baobao.cmd approve baobao-BB001
.\baobao.cmd schedule baobao-BB001
```

一次全部批准可用 `approve --all`；**這是你的批准命令，系統不會自行執行。** Prepare 只提供 `PROPOSED_SCHEDULE`，不登記正式 queue。

只修改一篇：

```powershell
.\baobao.cmd revise baobao-BB001 --instructions "短一點，不要那麼夢幻"
```

只調整順序，用 Preview 所列 photo_id：

```powershell
.\baobao.cmd reorder baobao-BB001 PHOTO_ID_1 PHOTO_ID_4 PHOTO_ID_3 PHOTO_ID_2
```

順序修改不重寫文案，但會重新做圖片 QA。手動編輯 `items/{content_id}/selected_caption.txt` 後執行 `review-caption ID`，可保留你改的原文並重新檢查。都需重新批准。

## 日期、取消與立即發布

```powershell
.\baobao.cmd reschedule baobao-BB001 2026-10-08T20:00:00+08:00
.\baobao.cmd cancel baobao-BB002
```

日期修改只代表建議日期，必須再次批准。每週頻率在 `maiocha-media-host-staging/config/brands/baobao.yaml` 的 `posting`；目前樣板是週二／四／六 20:00，每週 3 篇、Asia/Taipei。`posting_days` 採 0=週一至 6=週日。這不是演算法最佳時間。

日曆盡量錯開色系、hook、結構、構圖與相同 SKU。GitHub 每 15 分鐘查詢到期內容，可能延遲；每次最多 1 篇，逾時超過 24 小時停止待重新安排。[GitHub 排程限制](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

已批准且 Hosted 的單篇，要立即發布仍先檢查：

```powershell
.\baobao.cmd publish baobao-BB001 --now --dry-run
# 僅在你明確批准這篇立即發布後：
.\baobao.cmd publish baobao-BB001 --now
```

## 狀態、歸檔、暫停

```powershell
.\baobao.cmd status
.\baobao.cmd sync
.\baobao.cmd pause
.\baobao.cmd resume
```

`sync` 同步 Media ID 與歷史，成功項目歸檔到 `content/baobao/archive/`，原始照片保留。雲端發布時已把結果存入同 repo 的 `automation-state` 分支，電腦關機仍保存。

`pause` 修改遠端品牌 journal，可攔住下一次發布及已建立容器後的發布步驟。也可在 GitHub Settings → Secrets and variables → Actions → Variables 設 `PAUSE_ALL_BAOBAO_PUBLISHING=true`。恢復不代表批准任何內容。

| 狀態 | 意思 |
|---|---|
| DRAFT / PREPARED | 正在處理照片、觀察與文案 |
| NEEDS_INFO | 照片或 QA 需要補充 |
| READY_FOR_REVIEW | 等待你的明確批准 |
| APPROVED | 已批准，尚未正式排程 |
| SCHEDULED | 完整線上 Preflight 通過、已登記 queue |
| PUBLISHING / PUBLISHED | 發布中／已取得並保存 Media ID |
| FAILED | 確定失敗，停止 |
| MANUAL_ACTION_REQUIRED | 授權問題或結果不明，不能盲目重發 |
| CANCELLED | 已取消 |

目前固定人工核准模式。`mode approval` 可保留此設定；`mode auto` 明確拒絕。第一篇成功後也不切換成無審核發布。

## 一次性的 Meta 接入

沿用 `MaiOcha Lab Automation`，App ID `1833218008099793`，不用重連 Facebook ↔ IG。

1. 開 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)，選上面的既有 App。
2. Get Token → Get User Access Token／Generate Access Token，以原 Facebook 身分登入。
3. 在編輯先前設定／資產存取權時加入粉專「日常收藏所」與 Instagram `babycrystal.tw`，保留 maiocha。
4. 授予 `pages_show_list`、`pages_read_engagement`、`instagram_basic`、`instagram_content_publish`，按 Continue／Allow。
5. 複製 User Access Token，執行下面指令，在隱藏輸入中貼上；不要貼聊天。

```powershell
.\tools\Connect-Baobao.ps1 -Username babycrystal.tw
```

程式使用原 App Secret 換 token，驗證實際 App、User Token、permissions 與資產授權，再逐一核對 Page→IG→username。若粉專清單為空，會只依 Token 已授權的 Page ID 做直接 API 查核；不猜 ID，也不拿 maiocha 代用。成功後保存受保護的 `content/baobao/.env`，並以 GitHub repository public key 加密設定這四個 Secrets：

```
BAOBAO_PAGE_ID
BAOBAO_IG_USER_ID
BAOBAO_IG_USERNAME
BAOBAO_PAGE_ACCESS_TOKEN
```

如果只需重新同步已驗證 `.env`，執行 `baobao.cmd secrets-sync`。依據 [GitHub 官方 Secrets 加密流程](https://docs.github.com/en/rest/guides/encrypting-secrets-for-the-rest-api)，不輸出值、不送到聊天。Actions 的 `GITHUB_TOKEN` 由平台提供。

GitHub PAT 權限目前已修正，可部署 workflows、操作 Actions 和 Secrets，不必再更新一次。

隱藏輸入的 User Token 只以 Windows DPAPI 在 repository 外暫存；兩小時內可由 `Connect-Baobao.ps1 -Username babycrystal.tw -Resume` 安全續跑，成功後刪除暫存。Token 不出現在命令列、聊天、診斷或報告。安全診斷保存於 `.local/baobao-connect-result.json`。

`baobao.cmd validate --live-account` 可唯讀核對實際帳號與品牌命名空間，不發布內容。GitHub Actions 的手動 Dry Run 也會使用 repository Secrets 做此檢查；排程執行仍由既有批准與 pause 閘門控制。

## 第一篇真實測試

GitHub、Meta 都完成後，提供一條真實商品照片；資料夾預設 `inbox/2026-10-001/`。Prepare 後先停在 READY_FOR_REVIEW，讓你看真實 Preview。

**等你說「這篇可以測試發」才繼續。**首次只測一篇單張 Feed；多張商品照可先完成輪播預覽，再經你審核選定的測試封面，不批次發。

批准後才 approve → test Hosting → Dry Run → PUBLISH_PREFLIGHT → 一篇 test publish。成功需驗證實際圖片、完整中文 caption、baobao username、Media ID、時間，且該 Media ID 不在 maiocha。`verify-test --confirm-visual` 只能在真正目視確認後使用。

驗證成功仍保持 approval_mode=true，系統重新 pause。是否恢復「已批准篇目的排程」另外依你的指示，不自動開放無審核發布。

## Token 失效或發布失敗

- `MISSING_BAOBAO_*`：重新完成品牌授權／Secrets；不要填 maiocha 的值。
- `LIVE_ACCOUNT_MISMATCH`：停止，核對 Page→IG→username 與固定設定，不能跳過。
- Token 失效：同 App 重新授權，執行 Connect-Baobao 更新本機與 GitHub Secrets，不必重連 FB↔IG。
- `HOSTING_*`／`PAGES_NOT_READY`：等待 Pages 完成再安排，圖片 hash／MIME 不符不能發。
- `NEEDS_INFO`：看 Preview 的問題照片與補充建議，補拍／修正後再 prepare。
- `MANUAL_ACTION_REQUIRED`／發布逾時：先看 IG 有無貼文，不重發。確認實際 Media ID 後用 `reconcile ID --media-id 真實ID` 保存結果。
- 明確 FAILED 且沒有不確定 publish intent 才可 `retry ID`，最多兩次。`--force-republish` 不是修復逾時的方法。

Reels／Stories 暫未為 baobao 啟用，不影響 Feed／Carousel；原 maiocha 入口與內容保持原樣。
