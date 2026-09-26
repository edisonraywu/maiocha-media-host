# 寶寶礦到了｜照片到 Instagram 使用手冊

## 現在的啟用狀態

系統預設「人工核准」、全域暫停、production 未啟用。必須完成寶寶礦帳號授權與一篇真實單圖測試，才可啟用日常自動發布。測試程式通過不等於 Instagram 測試通過。

共用原有 Meta App、GitHub repository 和 GitHub Pages，不必重做 Facebook ↔ Instagram 連結。買房喵查局繼續使用原來的發布入口。

## 1. 照片放哪裡

在目前 `New project` 工作區裡，開啟：

```
content/baobao/inbox/
```

每條商品一個資料夾。名稱用英數字、減號或底線，例如：

```
content/baobao/inbox/
  2026-10-001/
    IMG_001.jpg
    IMG_002.jpg
    product.yaml
  2026-10-002/
    IMG_003.jpg
```

可以一次放 10～30 個資料夾。每個資料夾最多 50 張，最後每篇最多選 10 張。不要把不同商品混在一起；目前這個入口只處理單一商品，不會自動組合商品。

支援 JPEG、PNG、WebP、TIFF。HEIC 若本機沒有解碼器，請先匯出 JPEG。建議主體清楚、自然光、白平衡可靠、至少有一張全貌；短邊低於 600 像素會提醒品質不足。不要先用濾鏡改商品色。

## 2. product.yaml 怎麼寫

這個檔案完全可省略。也可以從 `content/baobao/product.example.yaml` 複製到某件商品資料夾並改名 `product.yaml`。

```yaml
product_name: 海藍寶素串
crystal_name: 海藍寶
price: 3280
bead_size: 10mm
stock: 1
sku: BB001
notes: 我看到的是淡藍色
```

所有欄位可留空，例如 `price:`。不確定就不要填。系統不會從照片猜出礦種、售價、珠徑、產地、處理方式或功效。手動名稱或價格不會被另一條商品拿走。

## 3. 平常最常用的三個步驟

在 `New project` 資料夾開啟終端機，執行：

```powershell
.\baobao.cmd prepare
```

它會一次处理整批照片、產生觀察與三版文案、圖片 QA、排未來日曆與 Preview。第一次讀圖可能花較久，之後不重做沒有變更的商品。使用目前 ChatGPT 登入的 Codex CLI；會使用你的 Codex 額度，不新增付費 API。若登入或額度有問題，顯示 `NEEDS_INFO`，不拿通用模板假裝完成。

接著雙擊：

```
content/baobao/preview/preview.html
```

檢查封面、輪播順序、實際商品特色、意境理由、文案、商品資料與日期。確認全部要發的內容後：

```powershell
.\baobao.cmd approve --all
.\baobao.cmd schedule --all
```

`schedule` 會處理 Hosting、公開圖片驗證、帳號驗證、Preflight，再登記到 GitHub 的正式排程。只有通過才成為 `SCHEDULED`。也可以把 `--all` 改成單一 ID，例如 `baobao-2026-10-001`。

之後電腦可以關機；GitHub Actions 只讀已生成的照片與文案。它每 15 分鐘檢查一次到期內容，每次最多發布 1 篇。GitHub 排程可能延遲，並非精準計時服務；超過預定時間 24 小時的內容停止，等你重排日期，不會突然補發整批。[GitHub 排程說明](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows)

## 4. 系統怎麼看圖、寫文案

1. 保留原始照片，不覆寫；建立 JPEG 1080×1350 的等比例版本與縮圖，必要時留白，不自動裁掉商品。
2. 每条商品獨立讀圖，逐張分析構圖、主色、光、上手、細節、全貌、可用性。
3. 先寫 `product_grounding.json`。照片中透明感只是視覺描述，不是寶石鑑定。
4. 再寫 `caption_basis.json`：適合／排除的意境與理由。
5. 寫 A 商品貼合、B 意境、C 短句，按貼合程度選擇，不偏袒 B。
6. 獨立重新讀圖檢查文案，再做程式規則檢查。錯色、猜礦、虛構價格、跨商品、無根據透明／功效都不能通過。
7. 失敗最多重新生成一次；還是失敗就 `NEEDS_INFO`，保留原因。

只做方向校正、ICC 轉 sRGB、等比例縮放、留白及格式轉換。沒有 AI 重畫、替換珠子、改顏色、提高透明度或美化品質。沒有你的貓照片就不會生成另一隻貓冒充。

內部分析與原始照片留在本機。公開 repository 只接收核准的選圖、正式文案、必要的完整性與 QA 證明；不含 product.yaml、原圖或完整内部分析。

## 5. 狀態怎麼看

```powershell
.\baobao.cmd status
.\baobao.cmd sync
```

`sync` 會讀 GitHub 最新結果，把成功紀錄、Media ID 與該篇文案／QA 歸檔到 `content/baobao/archive/`。雲端發布成功後立即保存在 `automation-state` 分支的品牌 journal；本機下次 sync 再同步。原始照片保留在 `items/{content_id}/originals/`，不刪除 inbox。

| 狀態 | 意思 |
|---|---|
| DRAFT | 尚未完成觀察或生成 |
| NEEDS_INFO | 照片、資料、生成或 QA 需要處理 |
| READY | 內容完成，尚未核准 |
| APPROVED | 已核准，尚未登記正式排程 |
| SCHEDULED | 線上 Preflight 已通過且排程已登記 |
| PUBLISHING | 正在建立／發布容器 |
| PUBLISHED | Meta 已返回 Media ID 並保存 |
| FAILED | 確定失敗，已停止 |
| MANUAL_ACTION_REQUIRED | 授權或發布結果不確定，需要確認 |
| CANCELLED | 這篇已取消 |

## 6. 修改文案

先編輯：

```
content/baobao/items/baobao-2026-10-001/selected_caption.txt
```

然後：

```powershell
.\baobao.cmd review-caption baobao-2026-10-001
.\baobao.cmd approve baobao-2026-10-001
.\baobao.cmd schedule baobao-2026-10-001
```

`review-caption` 重新看圖檢查你修改的原文，不會把它擅自改成另一篇。修改會撤回原排程與核准；不能只改文字後繼續沿用舊 QA。請先暫停或取消已經快到時間的文章，再修改。

## 7. 改日期、取消、立即發布

```powershell
.\baobao.cmd reschedule baobao-2026-10-001 2026-10-08T20:00:00+08:00
.\baobao.cmd approve baobao-2026-10-001
.\baobao.cmd schedule baobao-2026-10-001

.\baobao.cmd cancel baobao-2026-10-002
```

日期必須有 `+08:00`。重新排日期先撤回雲端舊排程，再要求新核准。已發布或結果不明的商品不能直接重排。

已核准並 Hosted 的單篇若要立即發布：

```powershell
.\baobao.cmd publish baobao-2026-10-001 --now --dry-run
.\baobao.cmd publish baobao-2026-10-001 --now
```

`--dry-run` 保證 0 次 Meta POST。真正發布仍會跑全部門檻。成功過的 item 自動拒絕重發。只有非常確定要再發一次時才使用 `--force-republish`；不要用它處理逾時或不確定結果。

## 8. 修改每週頻率

編輯 `maiocha-media-host-staging/config/brands/baobao.yaml` 的 `posting`：

```yaml
posting_days: [1, 3, 5]
posting_times: ['20:00']
posts_per_week: 3
timezone: Asia/Taipei
defaults_need_review: true
```

星期採 0=星期一、1=星期二、…、6=星期日。預設是每週二／四／六 20:00、每週 3 篇，只是可修改樣板，沒有宣稱是演算法最佳時間。確定你的頻率後可把 `defaults_need_review` 改 `false`。

日曆避免連續同色、同 hook、同文案結構、同構圖與短期重複 SKU；已指定的日期不因再次 prepare 自動亂移。需要改既有日期時使用 reschedule。`calendar/calendar.yaml` 是產出結果，請不要只改這份副本。

## 9. 暫停、恢復、approval / auto

```powershell
.\baobao.cmd pause
.\baobao.cmd resume
```

pause 直接寫 GitHub 品牌 journal，下次發布門檻會停止；不影響買房喵查局。也可在 GitHub repository → Settings → Secrets and variables → Actions → Variables 設 `PAUSE_ALL_BAOBAO_PUBLISHING=true`；恢復改 `false` 並執行 resume。

```powershell
.\baobao.cmd mode approval
.\baobao.cmd mode auto
```

預設 approval=true。切 auto 後，prepare 通過圖片 QA 才會接著 Hosting、Preflight、Schedule；不必逐篇 approve。仍需有效憑證、未暫停及首次真實測試成功。mode 修改的設定隨下次 host/schedule 推送。**切換模式不能跳過首次驗收。**

## 10. 第一次連接寶寶礦

不建立新 Meta App，不重做 FB ↔ IG 連結。

1. 開啟 [Graph API Explorer](https://developers.facebook.com/tools/explorer/)。選既有 `MaiOcha Lab Automation`（App ID `1833218008099793`）。
2. 選 Get User Access Token／Generate Access Token，使用原來的 Facebook 身分登入。
3. 在授權視窗的編輯存取權／選擇企業資產中，加入「寶寶礦到了」Facebook 粉專與其已連結 Instagram，保留原 maiocha 勾選。
4. 需要 `pages_show_list`、`pages_read_engagement`、`instagram_basic`、`instagram_content_publish`。按 Continue／Allow。
5. 複製 Explorer 的 **User Access Token**，不要貼到聊天。執行下列指令，貼到不顯示輸入的提示中：

```powershell
.\tools\Connect-Baobao.ps1 -Username 寶寶礦的實際IG帳號
```

程式會使用原 App Secret 換長效 Token（若可用），取得並核對 Page→IG，將專用欄位存入 `content/baobao/.env`，不改 maiocha `.env`。若 Explorer 沒列出寶寶礦，代表此授權尚未包含該資產，不代表 FB↔IG 沒連好。

GitHub Actions 需要在同一 repository 的 Secrets 存這四個名稱，值來自上述 `.env`：

- `BAOBAO_IG_USER_ID`
- `BAOBAO_PAGE_ID`
- `BAOBAO_IG_USERNAME`
- `BAOBAO_PAGE_ACCESS_TOKEN`

`GITHUB_TOKEN` 由 Actions 自動提供，不要手動建立它。若目前 GitHub PAT 沒有 Secrets／Workflows 管理權限，需以你的 GitHub 設定頁完成或提高該既有 credential 的對應權限。

本次實際稽核：既有 credential 是 **fine-grained PAT**，缺少 workflow 寫入與 Secrets 讀取權限。開啟 [Fine-grained personal access tokens](https://github.com/settings/personal-access-tokens)，編輯原本媒體託管使用的 Token，維持只選 `maiocha-media-host`，在 Repository permissions 補 `Workflows: Read and write`。若要讓程式代存品牌 Secrets，再補 `Secrets: Read and write`。不要擴成所有 repository，也不需要建立另一個 Meta App。

GitHub 官方列出的 [fine-grained 權限對照](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens) 將 workflow 檔案更新及 Actions Secrets 分別列為 Workflows、Secrets 權限。原本的 Token 直接更新權限即可，無需把 Token 貼到聊天。

權限完成後，重新執行 `.\tools\Deploy-Baobao-Code.ps1` 即可推送本機已保存的程式；不會 force push，也不會自動開啟 production。

## 11. 第一次只測一篇

選一條實際商品，只放一張清楚照片，完成 prepare 與 preview 核准後：

```powershell
.\baobao.cmd init-journal
.\baobao.cmd resume
.\baobao.cmd approve baobao-2026-10-001
.\baobao.cmd schedule baobao-2026-10-001 --test
.\baobao.cmd publish baobao-2026-10-001 --test --now --dry-run
.\baobao.cmd publish baobao-2026-10-001 --test --now
```

`--test` 只允許單張 Feed，且只允許首次一篇；不會啟動其他正式商品。打開真實 IG 貼文，確認是寶寶礦、圖片正常、中文正常，再用 verify-test 核對兩個帳號並保存證據：

```powershell
.\baobao.cmd verify-test --confirm-visual --other-env '.\買房喵查局內容系統\11_系統工具\Instagram官方發布\.env'
.\baobao.cmd resume
```

verify-test 會確認 Media ID 在寶寶礦、caption 完整相符、買房喵查局没有該貼文；`--confirm-visual` 表示你／Codex 已真正開圖檢查。成功後 production_ready 才能成為 true。完成驗證時會先再次暫停，最後 resume 才恢復日常排程。

## 12. Token 失效或發布失敗

- `MISSING_BAOBAO_*`：補 `.env`／GitHub Secrets。不要填成 maiocha 的 ID 或 Token。
- `LIVE_ACCOUNT_MISMATCH`：核對寶寶礦專用 config、ID、username 和選到的 Page；不要跳過。
- Token 被撤銷／過期：重新走上面的同 App 授權與 Connect-Baobao，更新 GitHub Secret。无需重做帳號連結。
- `HOSTING_*`／`PAGES_NOT_READY`：等 Pages 建置完成，再 schedule；任何圖片 MIME、hash、網址不符都禁止發文。
- `NEEDS_INFO`：看 Preview 的問題照片與補充建議，補拍或修正商品資料，再 prepare。
- `MANUAL_ACTION_REQUIRED`／發布逾時：**不要重發**。先看 IG 是否已有貼文。已有時以實際 Media ID 執行 `baobao reconcile ID --media-id 真實ID`，再 sync。
- 明確 `FAILED` 且未送過 publish intent，程式可允許 `baobao retry ID`，最多兩次；不確定結果不允許此操作。
- 手動新增商品資料或修改照片後，prepare 會撤回已登記的舊排程。若網路失敗，先在 GitHub 暫停再处理，不能把本機修改視為雲端已撤回。

錯誤只記錄安全代碼，不輸出 API 原始錯誤、Token 或 App Secret。

## 13. 程式與資料在哪裡

```
New project/
  baobao.cmd / baobao.ps1
  content/baobao/
    .env                         私人，禁止上傳
    inbox/                       每條實際商品一個資料夾
    items/{content_id}/
      originals/                 原照片不可覆寫
      processed/                 等比例發布圖、縮圖
      item.json
      product_grounding.json
      caption_basis.json
      caption_candidates.json
      selected_caption.txt
      vision_qa.json
      caption_qa.json
      preflight.json
      revisions/                 舊版本證據
    calendar/calendar.yaml
    preview/preview.html
    history/published-history.json
    archive/{content_id}/
  maiocha-media-host-staging/
    automation/                  共用內容與發布引擎
    config/brands/{baobao,maiocha}.yaml
    media/baobao/{content_id}/    只放核准選圖
    releases/baobao/{content_id}/ 正式caption與manifest
    .github/workflows/           CI與baobao排程
    tests/
```

Reels／Stories 已保留統一介面，但寶寶礦目前明確回報尚未啟用；不會以未測完的格式阻擋 Feed／Carousel。原 maiocha Reel／Story 程式仍在原位置。

技術依據：[Codex 批次與結構化輸出](https://learn.chatgpt.com/docs/non-interactive-mode)、[Meta 官方 Instagram API 範例](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api)。
