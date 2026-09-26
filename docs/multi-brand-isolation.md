# 兩個品牌的檔案與發布安全

`maiocha-media-host` 保留原名稱。它是共用 GitHub／Pages repository，品牌內容仍分開；不需要改「New project」或搬動照片。

## 實際範圍

| 品牌 | 私人內容 | 公開素材 | 發布狀態 |
|---|---|---|---|
| maiocha | 買房喵查局內容系統／各 Campaign | 現有 `media/maiocha-<campaign>/`；逐一登記，沒有猜新的路徑規則 | 原 Campaign 狀態、確認文字、CSV |
| baobao | `content/baobao/`；商品、Batch、校準、Preview、Style Profile | `media/baobao/{content_id}/` | `automation-state` 分支的 `state/baobao.json` |

`config/hosting-scopes.json` 保存目前真實的四個 maiocha Campaign 路徑與 baobao 範圍。所有 Hosting 寫入、覆寫、刪除及清理都先核對品牌、Campaign、來源及目標目錄。URL decoding、斜線、重複分隔符及 dot segments 會先正規化；prefix collision、跨目錄、Windows 路徑別名、junction／symlink 均被拒絕。清理只可操作該 Campaign，不能清理整個品牌或 repository。

新 maiocha Campaign 必須依其正式 manifest／Hosting config 登記明確範圍。未登記會停止，不會自行猜路徑。baobao 商品仍沿用原 Batch intake，不增加使用者操作。

## Hosting 驗證快取

新快取位於 maiocha Campaign 的 `Hosting/hosting-verification-cache.json`。每筆綁定 brand、campaign_id、asset key、來源根目錄及完整來源路徑、檔案 SHA-256、原始完整 URL、正規化 URL、原始及正規化 object key、hosting namespace、MIME。

任一身分不同就不能命中快取。原 `hosting_status.json` 保留作歷史證據，不能充當新快取。第一次安全 dry-run 會重新下載驗證並建立新快取。

正式 maiocha 發布即使有快取，仍重新下載核對 SHA-256／MIME，拒絕 redirect；每次把 URL 送入 Meta container 前再次驗證品牌及 Campaign。baobao 則沿用 release／approval／圖片與 Caption hash 驗證，並增加正規化路徑防線。這些檢查不是只放在 Preview。

## 明確品牌入口

一般 baobao 使用方式不變：把校準照片交給 Codex，等待私人 Preview。

通用 `同步發布品牌.ps1` **沒有預設品牌**。必須提供 `-Brand maiocha` 或 `-Brand baobao`；缺少、未知品牌或重複 brand override 都會停止。`-DescribeContext` 只顯示將使用的入口，不發布。

原本明確命名／位置的 maiocha `同步發布CampaignV2.ps1` 保留。舊 Campaign 與單張測試入口也限制在 maiocha 的本機素材／確認範圍；舊單張測試不再接受任意外部圖片 URL。既有綁定本機圖片的臨時 Hosting 保留。

GitHub Release asset 舊後端已無任何啟用設定；其未限定品牌的新增、上傳及刪除介面停止接受寫入。現行 GitHub Pages 流程照常使用。

## 如果流程停止

- `HOSTING_*MISMATCH`／`HOSTING_NAMESPACE_MISMATCH`：檢查指定品牌、商品或 Campaign，以及 URL／object key；不要改帳號或停用檢查來繞過。
- 舊快取失效：重新執行安全 dry-run，讓系統重新下載核對，不需刪除原圖。
- `EXPLICIT_BRAND_REQUIRED`：補上正確 `-Brand`；查看 Preview 不代表批准。
- `LEGACY_DEPLOYMENT_LOCAL_CHANGES_REQUIRE_REVIEW`：本機工具和已知版本不同，先比對差異，禁止直接覆蓋。
- Pause 開啟、未經明確批准、校準尚未完成或第一次實物測試未驗證：保持停止狀態，不自行 Resume。

## 維護與驗證

必要修改的旧工具存於 repository 的 `legacy/maiocha/`，作為原位置的部署來源；這不是第二套內容專案。`safety/Install-LegacySafety.ps1` 只更新列於 manifest 的工具檔，更新前檢查既有雜湊並備份。`-VerifyOnly` 可比對部署版本，不寫檔。原 40 檔 baseline 不重設，合法安全修復與其餘未變檔案分別回報。

CI 同時跑 Python 原有／新安全測試，以及 Windows、Linux 的 PowerShell Hosting／launcher／舊 maiocha 狀態機測試。測試只使用 fixtures 與 mock API；正式帳號驗證及 publisher dry-run 僅 GET，不建立 Instagram container。

發布始終需要自己的 brand context、獨立 approval、queue 與 history。風格校準確認不能批准任何商品貼文；baobao Pause 不影響 maiocha，反向亦同。
