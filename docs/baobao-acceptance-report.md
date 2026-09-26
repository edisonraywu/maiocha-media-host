# 寶寶礦到了｜Batch 工程驗收

驗收日期：2026-09-26（Asia/Taipei）。本次依最新要求，以「所有收件工程準備完成，只等未來一週／兩週商品」為終點，不要求現在提供照片或測試發布。

`READY_FOR_BATCH_PHOTO_WORKFLOW = NO`

`WAITING_FOR_BATCH_PHOTOS = NO`

目前 checkpoint：DEFAULT_PUBLISH_TIME_OWNER_CONFIRMATION。每日預設時間：待使用者回覆一次性時間問題；未把20:00樣板當成批准。

| 驗收項目 | 結果與證據 |
|---|---|
| A. GitHub | PASS，本次程式已部署；基準 5a2748207dfda8d052143c73363f5b47bd063d12；未回滾 commits |
| B. Actions / CI | https://github.com/edisonraywu/maiocha-media-host/actions/runs/36238952629 |
| C. Pages | https://github.com/edisonraywu/maiocha-media-host/actions/runs/36238952389；沿用 maiocha-media-host |
| D. Meta authorization | PASS；沿用 MaiOcha Lab Automation / 1833218008099793、Facebook Login、v26.0 |
| E. Secrets | PASS；BAOBAO_PAGE_ID、BAOBAO_IG_USER_ID、BAOBAO_IG_USERNAME、BAOBAO_PAGE_ACCESS_TOKEN 已存在；只驗證存在，不輸出值 |
| F. Account Verification | PASS；日常收藏所 / Page 1348149615047101 → IG 17841431857348052 → babycrystal.tw；真實 API 關聯與專用帳號核對 |
| G. Batch Architecture | PASS；batches/{batch_id} 保存清單與分組，items/{content_id} 沿用原管線；沒有第二套 publisher |
| H. Natural Language Intake | PASS；逐行／多行商品清單、日期、時間、選填價格珠徑 SKU；原始宣告保存；歧義只擋該筆 |
| I. 7 / 14 商品 | PASS；fixtures 各商品6張，42／84張綁定、再 prepare 重用、指定日期保留 |
| J. 6 Photo Logic | PASS；逐張 photo_type、清晰度、曝光、白平衡、可見度、構圖、相似度、排序理由；未採用圖與完全重複在 Preview 顯示 RECOMMEND_EXCLUDE，原圖保留 |
| K. Product Binding | PASS；每圖 content_id / asset_id / SHA256；同hash跨商品阻擋；metadata、照片、日期、caption 與 QA 綁定同項目 |
| L. User Declared Crystal Name | PASS；正式商品必須由使用者提供 crystal_name；照片與 product_name 不能補猜，缺少只做觀察並 NEEDS_INFO |
| M. Schedule Binding | PASS；保留使用者日期，不受舊每週三篇樣板覆蓋；同日多篇提示；缺日期不私排；預設时间仍需一次確認（若未設定） |
| N. Caption Grounding / QA | PASS（結構與安全 fixture）；三版均驗證使用者礦名與照片色彩／特徵；獨立圖片QA檢查選定版；失敗再生一次後仍阻擋 |
| O. Batch Preview | PASS（HTML／JSON結構、7商品、43個圖片連結含重複原圖）；日期、照片順序與原因、A/B/C、Selected與理由、未知資料、QA、狀態俱全 |
| P. Partial Approval | PASS；指定日期範圍只批准該範圍；有未完成項目時不部分誤批；其餘維持 READY_FOR_REVIEW |
| Q. Publisher / Approval | PASS（mock integration）；未批准在最上層拒絕；批准指紋綁定文案／照片／日期；publish無生成器呼叫；batch prepare無批准／queue／POST |
| R. Hosting / Preflight | 共用 Pages 與 /media/baobao/{content_id}/，已測 URL/MIME/hash failure gate；公開商品需明確批准後才上傳，未使用fixture冒充實物Hosting |
| S. Pause / Duplicate | PASS；journal pause及環境pause均攔截；成功記Media ID與hash，禁止自動重發；目前真實journal paused=true、production_ready=false、queue=0、items=0 |
| T. baobao Tests | 95 項本機測試 PASS；隔離fixtures／fake Meta，沒有真實商品發布 |
| U. maiocha Regression | 8 項原有測試 PASS；40個原檔0變更；沒有改maiocha帳號、素材或workflow |
| V. Cloud Dry Run | https://github.com/edisonraywu/maiocha-media-host/actions/runs/36238971349；專用 Secrets、live account、pause 只讀驗證，Instagram POST=0 |

## 真實資料與工程 fixtures 的界線

本次新增 `automation/batch.py`、`tests/test_batch.py`、`docs/baobao-batch-intake.md`；延伸既有 ingest、pipeline、schema、QA、calendar、preview、CLI及approval。Hosting、Meta publisher、GitHub journal 與原maiocha程式保持沿用。Windows長路徑的舊版本備份改存私人 revisions 雜湊目錄，原始檔不覆寫。

真實商品数=0；真實 Instagram POST=0；真實 Media ID 尚無。視覺品質與中文實際發布驗收保留到收到商品後；這不冒充本次fixture測試已通過。瀏覽器對 file URL 有安全限制，未作瀏覽器目視驗收，採本機HTML解析及每張圖片解碼／路徑檢查。完整依據在工作區 .local/ 的安全報告，沒有Token。

## 每週實際工作流

使用者提供7～14條、每條約6張照片＋水晶名稱＋每天發哪條 → Codex整理Batch → 逐商品Ingest／Grounding／Caption Basis／三版Caption／QA／Cover與Carousel → 整批Preview → READY_FOR_REVIEW → 等待明確批准。

指定範圍批准後，只對指定內容執行Hosting／Publish Preflight／Schedule。首篇測試需要另外明確批准；未完成前production維持paused。發布時只讀已批准檔案，禁止臨時改Caption。成功保存Media ID與hash並歸檔。保持 approval_mode=true、auto_publish_without_approval=false。

## 剩餘一次性操作

DEFAULT_PUBLISH_TIME_OWNER_CONFIRMATION

舊的完整實物上線標準仍為 `READY_FOR_PHOTO_ONLY_WORKFLOW = NO` / `READY_FOR_BAOBAO_AUTOMATION = NO`，直到真實商品經審核、明確批准並完成一篇test publish。新的 Batch readiness 只描述照片到待審核的工程已備妥，不授權任何自動發文。
