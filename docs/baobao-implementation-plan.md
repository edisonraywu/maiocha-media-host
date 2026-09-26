# 寶寶礦到了：稽核與實作計畫

稽核日期：2026-09-26。此計畫在修改任何既有程式前建立。

## 已確認的現況

- 工作區不是 Git repository；唯一業務用 Git checkout 是 `maiocha-media-host-staging`，remote 為 `edisonraywu/maiocha-media-host`（public、main）。
- 遠端 GitHub Actions 只有動態的 `pages-build-deployment`，沒有 Instagram 發布排程 workflow。GitHub Pages 使用 main 根目錄，現有網址 `https://edisonraywu.github.io/maiocha-media-host/`。
- 內容工作區為 `買房喵查局內容系統/01_*` 至 `11_系統工具`。生成採 Codex 批次作業及本機 Python/JS 製作，沒有可重用的商品視覺分析 API。
- 正式 publisher 是 `11_系統工具/Instagram官方發布/同步發布CampaignV2.ps1`。已具 manifest、精確路徑與 SHA256、preflight、人工核准、容器狀態、CSV history、不確定回覆後停止與查詢。
- 該 publisher 的入口及 preflight 硬性要求 6 張輪播、1 Reel、3 Stories、固定順序、特定舊 Reel 證據，並固定 maiocha ID。把它直接改成商品引擎會危及既有流程。
- 單圖測試程式、舊版 Campaign 程式均保留。現有 Meta App `1833218008099793`，Facebook Login、Graph v26.0；maiocha IG `17841423624192593` / `maiocha.lab`、Page `1364481190072089`。
- 既有本機 `.env` 只有 maiocha 欄位；App Secret、User Token 與 GitHub Token 使用 DPAPI。沒有讀出或記錄任何 Secret 值。
- 2026-09-26 實際 Meta GET 成功核對 maiocha 的 Page、IG ID、username；回傳 media_count=0。舊 CSV 有 2026-09-17 成功紀錄，不能據此宣稱目前貼文仍存在。
- 既有 User Token 的 `me/accounts` 沒有列出寶寶礦。尚缺可核定的 baobao ID、username、Page Token。
- 範圍內未找到 baobao 商品照片。沒有實物照片時不能通過商品文案品質驗收。
- 本機 Codex CLI 已以 ChatGPT 登入，支援圖片輸入與 JSON schema；不需要新增付費 API。批次 CLI provider 只在 prepare 使用，scheduler 禁止呼叫 AI。

## 實作決策

1. 在同一 hosting repository 增設共用 `automation/`、`config/brands/`、workflow、測試。新增現有發布工具旁的品牌入口，保留既有 maiocha scripts、assets、manifests、history 原樣。
2. 重用既有 Pages 與 `/media/baobao/{content_id}/`；以品牌化 Python adapter 延伸既有 Meta container → polling → media_publish 程序（解除舊 Campaign 的固定媒體组合限制），不建立另一個服務、repo 或 Meta App。
3. 本機私有素材與 draft 位於工作區 `content/baobao/`；originals、商品資料、grounding、候選與 preview 不加入 public repository。只有核准/auto-mode 完整驗證的發布包可匯出公開 repository。
4. 所有路徑、metadata、caption、grounding、manifest 使用同一 content_id、來源快照 hash；變動後取消舊核准。每條商品分開讀圖，不跨資料夾拼接。
5. 批次 ingest → 真實圖片視覺分析 → 保存 grounding → 保存 caption basis → 三候選 → 選擇 → 獨立讀圖 QA＋程式規則 QA。最多重新生成一次，仍失敗 NEEDS_INFO。
6. 固定狀態機與 approval_mode=true、paused=true、production_ready=false。排程預設明示為可修改樣板（Asia/Taipei），不宣稱最佳時間。
7. 發布門檻必須核對品牌 config、環境 ID、username、Page→IG 關聯、公開 asset namespace/bytes/MIME、caption/QA/hash、schedule、history、pause、核准/auto-mode，以及測試驗收。
8. 共用 GitHub CAS journal 在每次不可逆 POST 前持久記錄 intent，防止本機/GitHub 並行、runner 中斷與狀態寫回失敗重發；未確認結果只能人工處理。安全 GET 有有限 retry，publish POST 不盲目 retry。
9. workflow 只找到期已預先生成內容；baobao job 隔離，不呼叫舊 maiocha publisher。沒有成功的單篇實測證據不可開啟 production。
10. 適當 unit/integration/dry-run：混資料、錯帳號、錯色、未知礦種/價格、缺 token、錯 URL、重複與 crash、遠端 CAS、approval invalidation、pause、批次 20 組；最後 legacy checksum/PowerShell syntax 回歸。

## 執行順序

- [x] 本機架構、publisher、hosting、metadata、secrets 名稱、history、GitHub 遠端、唯讀 Meta 稽核。
- [x] 建立本計畫。
- [x] 品牌設定與安全核心、商品 ingest、Codex 批次 provider（尚無真實商品照片可跑視覺驗收）。
- [x] Grounding/caption/QA/preview/calendar 與簡單 CLI。
- [x] Hosting promotion、Meta publisher、durable history、Actions、pause 程式；遠端品牌 journal 已實際建立並保持暫停。
- [x] 更新為 57 個測試、本機與遠端空 inbox dry-run、40 個 maiocha 原檔雜湊、原有 8 個狀態機測試、唯讀帳號與 Hosting 回歸、使用手冊。
- [x] GitHub PAT 權限已解除，原 commits 與人工批准更新 e50e093 已部署，CI／Pages／手動 Dry Run PASS，Secrets API 可讀。
- [ ] baobao 線上帳號驗證：現有 Meta User Token me/accounts 仍回傳 0，待本人授權寶寶礦 Page／IG；品牌帳號值與 Secrets 尚缺。
- [ ] 一篇真實測試 Feed、確認帳號/中文/圖片、保存 Media ID，才允許 production readiness。

## 最終交付狀態

依最新使用者指示，正式模式固定為人工批准，取代本計畫初期可切 auto 的設計：`approval_mode=true`、`auto_publish_without_approval=false`。Prepare 停在 READY_FOR_REVIEW，日曆為 PROPOSED_SCHEDULE；連第一次 test publish 都要明確批准，不能自行 approve-all。

詳見 `docs/baobao-acceptance-report.md`。程式已保存 Git commit 並部署；57 項新系統測試使用隔離合成 fixture 與假 Meta，不能取代實際商品驗收。未進行任何真實 Instagram POST。`READY_FOR_PHOTO_ONLY_WORKFLOW = NO`；`READY_FOR_BAOBAO_AUTOMATION = NO`。

## 文件依據

- Meta 官方 Instagram API 範例：https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api
- Codex 結構化批次：https://learn.chatgpt.com/docs/non-interactive-mode
- GitHub 排程限制：https://docs.github.com/en/actions/how-tos/troubleshoot-workflows

GitHub schedule 可能延遲，系統使用到期時間比較與 catch-up 上限，不承諾精準到分鐘。
