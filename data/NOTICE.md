# 資料來源與授權（Dictionary Data Attribution）

`bopomofo_dict.tsv` 是由 **libtabe** 的 `tsi.src` 詞頻／注音資料處理而來
（`scripts/build_dict.py`），保留了詞、頻率與注音讀音。

- **來源檔**：`tsi.src`
- **取得位置**：https://github.com/chewing/libchewing 的 `v0.8.5` 標籤，路徑 `data/tsi.src`
  （原始碼註明資料出自 libtabe）
- **原始授權**：BSD License（libtabe）
- **原始檔大小**：約 5.15 MB（158,043 行）

## 重建方式

```bash
# 1. 取得原始資料
curl -o tsi.src https://raw.githubusercontent.com/chewing/libchewing/v0.8.5/data/tsi.src

# 2. 產生精簡字典（單字全保留；多字詞預設保留頻率 >= 3）
python scripts/build_dict.py tsi.src
```

## 處理內容

- 依 `(去聲調注音, 詞)` 聚合，保留最高頻讀音。
- 丟棄頻率為 0 的雜訊與純注音符號的表頭列。
- 多字詞預設過濾掉頻率 < 3 的冷門詞（單字一律保留，確保任何合法音節都能被覆蓋）。
- 每個讀音鍵最多保留 20 個候選（依頻率）。

libtabe / libchewing 的原始 BSD 授權條款請見其專案。若要重新散布本 skill，
請一併保留本 NOTICE 與上游授權聲明。
