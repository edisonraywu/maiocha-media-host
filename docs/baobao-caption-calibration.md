# 第一次：一起找寶寶礦的文案語氣

先給 **1～3 條你真的準備上架的素串**，每條約六張照片。有什麼商品就用什麼，不必特地準備不同顏色，也不用安排未來兩週。

可以直接說：

> 這是第一輪文案校準。  
> BB001：海藍寶，下面六張是同一條。  
> [六張照片]  
> BB002：綠碧璽，下面六張是另一條。  
> [六張照片]

一條也可以。水晶名稱與照片對應由你提供；價格、珠徑、SKU、庫存、備註可省略。Codex 會整理照片，你不必建立複雜檔案。

先看照片 → 商品觀察 → 文案依據 → 每條六種說法 → 私人 Preview。

六種說法是：A 商品貼合、B 顏色意境、C 風景、D 極簡短句、E 日常生活、F 寶寶礦品牌。每版都寫同一條真實商品，並顯示語氣、長短、詩意、銷售感和使用原因；不替你選唯一答案。

看完可以直接說：

- 「我喜歡 B 跟 E，C 太文青。」
- 「BB001 的 A 第一段，加上 E 的語氣。」
- 「emoji 不要，CTA 少一點。」
- 「寶寶，你的礦到了可以留，但不用每篇。」
- 「不要『剛剛好』這句，最近文案太像。」

不知道你指哪一句時，只會確認那一處。回饋會保存，整理給你看；你說風格可以後，系統才將它設為正式偏好。後面仍可說「最近不要 CTA」「風景感再多一點」來更新，不需要改設定檔。

**確認風格不是批准發文。校準期間完全不排程、不發布、不測試發文。**之後正式 Batch 仍會停在 Preview，等你說「可以發」。預設發文時間是上午 10:00（Asia/Taipei），單篇可另訂。

## 給 Codex 接續操作

下面是工作區內部入口，平常使用者只需要上面的自然語言：

```powershell
.\baobao.cmd calibration status
.\baobao.cmd calibration intake --session-id first --input .local\校準清單.txt --source .local\校準照片
.\baobao.cmd calibration prepare first
.\baobao.cmd calibration preview first
.\baobao.cmd calibration feedback first --text '我喜歡 B 跟 E，C 不要。emoji 不要。'
```

清單每行如 `BB001 海藍寶`，無需日期。照片來源每個商品代號一個資料夾；Codex 只能按使用者明確對應分組，不能猜。

若回饋指特定商品或 Style，使用 `--content-id BB001 --style A`。不明確的片段保存為待確認；收到針對該問題的回答後，才加 `--resolve-pending`。只改一條資料可用 `calibration update first BB001 --crystal-name 海藍寶`，補照用 `calibration add-photos first BB001 --source 路徑`，然後再次 prepare；其他已驗證商品重用。

`calibration confirm first` **只在使用者明確確認已展示的風格偏好後**執行，不能代替商品 approve。後續使用者明確給出的風格調整會保存新版本；未發布舊項目需要重新 QA／審核，已排程內容先撤回。

私人資料：

```text
content/baobao/
  calibration/status.json
  calibration/{session_id}/
    session.json
    batches/calibration-{session_id}/
    items/{content_id}/
      product_grounding.json
      caption_basis.json
      calibration_captions.json
      calibration_qa.json
    preview/preview.html
    preview/preview.json
  config/baobao-caption-style.yaml   收到回饋後才建立
```

Style Profile 保存偏好、排除風格、語氣、長短、CTA／emoji／品牌句規則、喜歡／不喜歡的例句、回饋來源與版本。它放在 repository 外，避免私人校準例句被 Pages 公開。未指定偏好保持未知，不替使用者決定。

狀態依序為 `CALIBRATION_SYSTEM_READY` → `CALIBRATION_WAITING_FOR_PRODUCTS` → `CALIBRATION_PREPARING` → `CALIBRATION_READY_FOR_REVIEW` → `CALIBRATION_FEEDBACK_RECEIVED` → `CALIBRATION_STYLE_CONFIRMED`。最後才有 `CAPTION_STYLE_CALIBRATED=YES`；照片不足或礦名缺少的商品為 NEEDS_INFO。

正式 Batch 沿用同一 ingest／grounding／basis，加上 Profile、Product QA、獨立 Style QA；重複開頭、結尾、風景、常用形容詞、CTA 與品牌句也會檢查。漂移最多重寫一次，仍失敗便 NEEDS_INFO。發布端只驗證保存好的文案與 QA，不臨時生成。
