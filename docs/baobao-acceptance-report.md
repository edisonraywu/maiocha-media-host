# 寶寶礦到了｜Meta 接入完成，等待第一組真實商品

更新：2026-09-26T17:49:40+08:00。

**READY_FOR_PHOTO_ONLY_WORKFLOW = NO**

Meta 授權、真實帳號與四個 GitHub Secrets 已完成。下一個本人 checkpoint 是提供第一组真實商品照片；尚未提供實物 Preview，尚未批准或發布任何測試貼文。

固定模式：approval_mode=true、auto_publish_without_approval=false。遠端 paused=true、production_ready=false，queue 與 published items 都是 0。真實 Instagram POST 為 **0**。

BLOCKERS:

1. 第一組真實商品照片尚未提供；需實物 ingest、Grounding、Caption Basis、商品對應三版文案及圖片 QA。
2. 真實 Preview 尚待本人審核，內容必須停在 READY_FOR_REVIEW。
3. 必須在本人明確批准後，完成商品 Hosting、Dry Run、PUBLISH_PREFLIGHT、一篇 Feed test publish 與 Media ID／圖片／中文／帳號驗證。

## A. GitHub

**PASS。**已將原 commits 加上 Meta 接入修正與真實帳號設定推送至同一 repository 的 main。程式 commit：`5188ba8e0f5029b59f8d944c6bb201620fa4ca2b`。後續報告 commit 僅更新驗收文件。沒有 force push、回滾或新建專案。

沿用 edisonraywu/maiocha-media-host。只部署 baobao／共用 Python 功能、品牌設定、測試、workflow 與文件。部署前掃描 tracked／待提交檔案及新增 commits，禁止 .env、DPAPI、Token 入庫。

## B. Actions

**PASS。**本次程式 commit `5188ba8e0f5029b59f8d944c6bb201620fa4ca2b` 的 [GitHub CI](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36233762750) 已成功。原 57 項覆蓋延伸至本機 70 項，遠端亦執行同一份測試。

**帳號與空內容 Dry Run PASS。**[手動 Dry Run](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36233793937) 在 GitHub runner 實際使用四個 Secrets 查詢 Meta，account_safety_gate=PASS、四項 secret_presence=true、paused=true、production_ready=false、NO_DUE_CONTENT、api_post_requests_sent=0。這不是實物貼文的完整 Dry Run。

baobao 有獨立 concurrency、BAOBAO Secrets、config、releases 與 state/baobao.json，不呼叫原 maiocha publisher。原 repo 沒有 maiocha Instagram workflow；不能宣稱執行不存在的 workflow。手動 Dry Run 新增唯讀帳號檢查，排程仍只發布既有、已明確批准的內容，不生成文案。

## C. Pages

**PASS。**同一 Hosting 的 [Pages deployment](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36233762400) 成功。原 maiocha 圖片公開 GET 為 200、image/jpeg，SHA256 相符。尚無 baobao 真實商品可驗證公開圖片 URL。

## D. Meta authorization

**PASS。**沿用 MaiOcha Lab Automation／App ID 1833218008099793、Facebook Login、Graph v26.0。真實 debug_token 確認同一 App、USER、is_valid=true；四項必要 permissions 與 baobao Page／IG 的 granular asset grants 均已驗證。

me/accounts 仍回傳空陣列，因此依真實 token grants 取得已授權 Page ID，再用官方支援的 Specific Page 查詢取得該 Page Token。只查已授權 ID，排除原 maiocha Page；以 Page Token 核對實際 Page→IG→username 與 content_publishing_limit。沒有猜 ID、跳過授權或改建 App。[Meta 官方 Specific Page Token 流程](https://www.postman.com/meta/workspace/instagram/documentation/23987686-9386f468-7714-490f-9bfc-9442db5c8f00)

## E. Secrets

**PASS。**以下四個名稱已經 GitHub API 確認存在；寫入前先做真實帳號驗證，使用 repository public key／libsodium sealed box，加密後寫入，僅查名稱 metadata，不讀回值：

- BAOBAO_PAGE_ID
- BAOBAO_IG_USER_ID
- BAOBAO_IG_USERNAME
- BAOBAO_PAGE_ACCESS_TOKEN

Page Token 保存在受限 ACL 的 local .env 與 GitHub Secrets，不進 code、manifest、Preview、報告或 log。User Token 的 Windows DPAPI 重試暫存已於連線／Secrets 成功後刪除。安全結果檔：content/baobao/github-secret-verification.json；不含 token 值。

## F. Account Verification

**PASS，真實 API 查核。**

| 項目 | 驗證結果 |
|---|---|
| 品牌 | baobao／寶寶礦到了 |
| Facebook Page | 日常收藏所 |
| Page ID | 1348149615047101 |
| IG User ID | 17841431857348052 |
| IG username | babycrystal.tw |
| 所需權限 | pages_show_list、pages_read_engagement、instagram_basic、instagram_content_publish |
| Asset namespace | media/baobao |
| Content／caption namespace | content/baobao |
| Publish history | 同 repo automation-state 分支的 state/baobao.json |

credentials 必須與固定 config 相同；真實 Page 名稱、Page→IG 與 username 亦須相同。發布前另外核對該商品 content_id、caption、assets、hash、QA、approval、history。真實商品尚未提供，不能把帳號驗證當作商品 Preflight。

## G. Real Product Ingest

**待照片。**目前真實商品數 0。每條商品獨立資料夾、原圖保留、去重、processed／thumbnail、照片品質與批次隔離已由測試覆蓋，不拿 fixture 充當商品驗收。metadata 七欄皆選填。

## H. Grounding

**實物驗收待照片。**逐張讀取實際商品，保存顏色、明暗、照片中的透明感／表面／紋理、光線、構圖、上手／平放／近拍／全貌與未知資訊。沒有 metadata 不推論礦種、售價、尺寸、等級或功效。

## I. Caption Basis 與 Caption

**實物驗收待照片。**先保存視覺事實、使用者事實、未知欄位與候選／排除意境，再生成 A 商品貼合、B 意境、C 短句，選擇最貼合眼前商品的一版並保存理由。由本機 Codex 批次預生成，GitHub 發布時不重新寫文案。

## J. Caption QA

**實物驗收待照片。**規則檢查與獨立讀圖 QA 都須 PASS；錯色、光感、礦名、價格、珠徑、產地、功效、其他商品 metadata／ID 或泛用文案都攔截。最多重新生成一次，仍失敗 NEEDS_INFO。

## K. Preview／Single／Carousel

**真實 Preview 待照片。**依好照片數量選 Single／Carousel，不湊差照片。預覽包含照片與順序、cover、Grounding、basis、A／B／C、Selected Caption、理由、metadata、未知欄位、形式、target IG 與 status。所有準備完成的內容停在 READY_FOR_REVIEW，修改只影響指定商品並重新 QA。

## L. Approval Gate

**程式與測試 PASS。**沒有明確批准，不能 approve、建立正式 schedule 或呼叫 publisher；第一次測試也不能繞過。批准指紋綁定照片、文案、QA、日期與帳號，修改後撤回舊批准。mode auto 明確拒絕。

## M. Hosting

**基礎設施 PASS，baobao 真實圖片待商品與批准。**沿用 GitHub Pages 的 /media/baobao/{content_id}/。因 Hosting 會公開圖片與正式文案，先準備私人 Preview，明確批准後才上傳並檢查公開 GET、MIME、hash；不使用 maiocha 圖片。

## N. Publish Preflight

**尚未執行真實商品 PUBLISH_PREFLIGHT。**需先有該商品與明確批准；不得用帳號檢查或空內容 Dry Run 冒充完整商品 PASS。

## O. Test Publish

**未執行。**尚無商品或批准，真實 Instagram POST 為 0。第一次只能在本人同意後發一篇 Feed，不批次發，不影響 maiocha。

## P. Media ID Verification

**尚無 baobao Media ID。**測試成功後才保存 content_id、Media ID、時間、asset／caption hashes、target，核對圖片、中文、正確帳號及 maiocha 未出現該貼文，並測試不能重複發。

## Q. Pause

**PASS。**遠端 paused=true、production_ready=false、queue 0、items 0。PAUSE_ALL_BAOBAO_PUBLISHING 與 journal pause 可攔截已排程內容，且建立容器後再次檢查 pause；未批准內容不因解除暫停而得到批准。

## R. maiocha Regression

**PASS，2026-09-26T17:37:42.4017287+08:00。**原有 8 項測試全通過、40 個原檔 hash 不變、PowerShell 語法無錯。真實 Page→IG→maiocha.lab 正確，原 Hosting GET 200／JPEG／hash 相符，唯讀驗證沒有 Meta POST。

## S. baobao Tests

**70／70 本機 PASS。**新增覆蓋分頁、空清單但存在明確資產授權、錯誤 App／Page／IG／個別資產發布權限、錯誤紀錄不含秘密、雲端帳號檢查不發布且保持 pause。原批次 20 商品、metadata 隔離、QA、批准、pause、idempotency、retry、archive 覆蓋保持。

## T. Final Workflow／Remaining Manual Steps

下一步只需要：**提供第一組真的準備上架的素串照片。**附件若能由工作區讀取，Codex 自行整理到 inbox；否則才請放入 content/baobao/inbox/2026-10-001/。商品資料選填。

照片 → 整理／Ingest → Grounding → Basis／三版文案 → QA → 選封面／Carousel → Preview → **READY_FOR_REVIEW 停止** → 本人批准指定內容 → Hosting／Preflight → Publish／Schedule → Media ID／Archive。

第一篇仍需「這篇可以測試發」。成功後也維持 approval_mode=true、auto_publish_without_approval=false；不自行開放無審核發布。

**READY_FOR_PHOTO_ONLY_WORKFLOW = NO**

**READY_FOR_BAOBAO_AUTOMATION = NO**
