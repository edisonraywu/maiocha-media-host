# 寶寶礦到了｜Batch 與文案風格校準工程驗收

驗收日期：2026-09-26，Asia/Taipei。已保存 **Default Publish Time = 10:00 Asia/Taipei**，單篇時間覆蓋預設且不修改品牌設定。

`READY_FOR_BATCH_PHOTO_WORKFLOW = YES`

`CAPTION_CALIBRATION_SYSTEM_READY = YES`

`WAITING_FOR_CALIBRATION_PRODUCTS = YES`

目前 checkpoint：等待第一組 **1～3 條真實校準商品，每條約六張照片**。不要求正式 7～14 天 Batch。`CAPTION_STYLE_CALIBRATED = NO`：尚未收到真實照片與使用者風格回饋，沒有預先建立正式風格偏好。

## 部署與基礎整合

| 項目 | 真實結果／證據 |
|---|---|
| GitHub deployment | PASS；程式版本 `af1b3517c8fdb6ea07e1bb1ca9521665190bba8f` 已推送，沿用既有 commits，無回滾 |
| Actions / CI | PASS；[CI](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36241770138)；131 項 baobao tests |
| GitHub Pages | PASS；[Pages deployment](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36241769870)；沿用 maiocha-media-host |
| Meta | PASS；MaiOcha Lab Automation / 1833218008099793，Facebook Login、Graph v26.0 |
| Secrets | PASS；BAOBAO_PAGE_ID、BAOBAO_IG_USER_ID、BAOBAO_IG_USERNAME、BAOBAO_PAGE_ACCESS_TOKEN 皆存在且由 Actions 使用；沒有輸出 Secret 值 |
| Account Verification | PASS；真實 API：日常收藏所 → 寶寶礦 IG `babycrystal.tw`，Page、IG ID、username、權限與品牌 namespace 核對 |
| Cloud Dry Run | PASS；[唯讀帳號／Secrets／journal 驗證](https://github.com/edisonraywu/maiocha-media-host/actions/runs/36241800641)；Instagram POST=0 |
| Pause | PASS；journal paused=true、production_ready=false、queue=0、items=0；環境變數 pause 與發布途中 pause 測試通過 |
| maiocha regression | PASS；原有 8 項狀態機測試，全數通過；40 個原檔 hash 完全未變 |
| Security | Token 未寫入 repo、Preview、manifest 或此報告；私人 content／.env／DPAPI 不在提交內容 |

## Batch Final Acceptance

| 項目 | 結果 |
|---|---|
| Batch Architecture / Natural Language Intake | PASS；重用 batches、items、CLI，保存使用者原始宣告；不用手寫 YAML |
| 7-day / 14-day Batch | PASS（fixtures）；7／14 商品，各6張，共42／84張，不跨商品 |
| Six Photo Logic / Product Binding | PASS；asset_id、content_id、hash；保留原圖；重複與劣質照片明示 RECOMMEND_EXCLUDE 和原因 |
| User Declared Crystal Name | PASS；礦名只由使用者提供；缺少可先 Grounding，但不能完成文案 |
| Schedule Mapping | PASS；保留使用者日期、偵測撞期、10:00預設、19:30／20:30單篇覆蓋；未批准只有 proposed schedule |
| Grounding / Caption Basis / Caption Pipeline | PASS（結構與安全 fixtures）；實際商品照片決定描述，身份與價格等只來自手動資料 |
| Product Caption QA | PASS；攔錯色、錯礦名、跨商品內容、未知事實、失效照片／文字 hash；最多重試一次 |
| Batch Preview / Partial Approval | PASS；圖片、順序、三候選、Selected、日期、狀態；指定範圍只批准該範圍 |
| Unapproved Publish Block | PASS；發布與 queue 頂層要求明確批准，Style 校準不取代商品批准 |
| Publisher / Hosting / Archive / Duplicate | PASS（mock integration）；沿用既有 publisher、Pages namespace、journal；正式發布只讀保存且批准的 caption，不臨時生成；保存Media ID與hash並防重複 |

## Caption Calibration Acceptance

| 項目 | 結果 |
|---|---|
| Calibration Architecture | PASS；私人 session、1～3產品、每條獨立內容ID；重用 ingest、grounding、basis、QA 和照片排序 |
| Six Style Generator | PASS（fixtures）；每商品 A商品貼合／B顏色意境／C風景／D極簡／E日常／F品牌，六版均綁定當前商品，沒有自選唯一品牌Style |
| Style Metadata | PASS；tone、length、poetry、imagery、daily life、sales、CTA、emoji、signature、why it fits 均保留 |
| Calibration Preview | PASS；3商品×6照片×6Style 的 HTML／JSON 結構；18圖片連結與圖像解碼、18候選及QA綁定通過；非真實商品品質驗收 |
| Feedback Parser | PASS；自然中文喜歡／排除、混合句、語氣／段落、emoji、CTA、signature、長短等；只保留明確偏好，歧義逐處保存待確認 |
| Profile Mechanism / Persistence / Update | PASS；收到明確回饋才保存私人 `content/baobao/config/baobao-caption-style.yaml`；保留來源、例句、排除句、版本，確認後才 calibrated；之後可更新 |
| Style QA | PASS；獨立模型檢查＋確定性文字規則，profile／caption／content hash 綁定；漂移最多再生一次，仍FAIL不得READY |
| Wording Repetition Detection | PASS；近期形容詞、開頭、結尾、風景、CTA、品牌句與文字相似度；校準Preview顯示提醒，正式批次納入Style QA |
| Formal Batch Calibration Gate | PASS；未CALIBRATED，只 ingest／photo QA／grounding，WAITING_FOR_CALIBRATION；不能Final Caption／approve／schedule |
| No Schedule / Publish During Calibration | PASS；校準不存發布日期；reserved calibration ID 與 purpose 在 publisher／queue 最上層拒絕，偽造APPROVED也不能發，test publish 同樣拒絕 |
| Profile Changes / Reviewed Caption | PASS；更新風格前先撤回舊queue，未發布商品重新QA與審核；發布使用已審核文字，不載入生成器 |
| Tests / Regression | PASS；本機 131 項 baobao、8 項 maiocha；相同程式在GitHub CI通過 |

實際商品照片=0、實際Instagram POST=0、實際Media ID=無。工程 fixtures 僅驗證流程與安全，沒有冒充真實水晶圖、真實文案品質或使用者已選定的品牌風格。校準Preview以本機HTML解析、路徑／圖片解碼驗證；因瀏覽器 file URL 限制，沒有宣稱完成瀏覽器目視驗收。

## 日常使用與下一個 checkpoint

第一次：1～3條照片＋每條水晶名稱 → 商品觀察 → 六種Style Preview → 使用者回饋 → 確認Style Profile。校準不發文。

之後：7～14條照片＋名稱＋指定日期 → Batch → Grounding／Basis → 已確認Style → 三候選／Selected → Product QA／Style QA → Cover／Carousel／Preview → READY_FOR_REVIEW → 等使用者明確批准 → 才允許Hosting／Preflight／Schedule或Publish。

目前 `approval_mode=true`、`auto_publish_without_approval=false`，production仍paused。第一篇真實測試需要日後另外批准、真實照片／Caption／帳號／Media ID驗證；這不是本次工程停止條件，亦不由校準批准替代。

**沒有需使用者完成的工程設定；現在只等1～3條校準商品照片與水晶名稱。**

舊的實物發布驗收旗標 `READY_FOR_PHOTO_ONLY_WORKFLOW=NO`、`READY_FOR_BAOBAO_AUTOMATION=NO` 保留，直到日後明確批准的一篇實物test publish完成。本次三個YES表示Batch與Calibration機制已備妥，不代表偏好已選定、實物品質已驗證或可無審核發布。
