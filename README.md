# bopomofo-input-recovery

把「忘記切輸入法、用注音鍵盤打出來的英數亂碼」自動還原成中文的 Claude Code skill。

實際情況通常不是整句亂碼，而是**一句話裡有一半忘了切**：

```
這個 PR dk3u3 merge 了嗎           →  這個 PR 可以 merge 了嗎
a86z06 你了，幫我看一下 login.py    →  麻煩 你了，幫我看一下 login.py
幫我把這段 code hk4g4 一下          →  幫我把這段 code 測試 一下
```

中文照舊、英文和檔名不動，只有忘了切的那幾段被還原。

**裝好之後不用打任何指令**：你送出訊息的當下就完成解碼，AI 第一眼就看得懂。

給每個都會忘記切輸入法的台灣工程師。

---

## 安裝

把整個資料夾放進你的個人 skills 目錄，就這樣：

```bash
git clone https://github.com/Oliviaiii/bopomofo-input-recovery.git ~/.claude/skills/bopomofo-input-recovery
```

Windows PowerShell：

```powershell
git clone https://github.com/Oliviaiii/bopomofo-input-recovery.git "$env:USERPROFILE\.claude\skills\bopomofo-input-recovery"
```

**重開 Claude Code**，然後直接打 `su3cl3a8` 試試看。

> 第一次建立 `~/.claude/skills/` 這個目錄時一定要重開 Claude Code，之後修改才會即時生效。

### 需要什麼

- **Claude Code**（`${CLAUDE_SKILL_DIR}` 免提示執行需要 v2.1.129 以上；舊版仍可用，只是會多問一次權限）
- **Python 3**，且 `python` 指令要在 PATH 上
  （若你的環境只有 `python3`，把 [hooks/hooks.json](hooks/hooks.json) 裡的 `"command": "python"` 改成 `"python3"`）

### 為什麼不用打指令就會生效

這個資料夾同時是 skill 也是 plugin（含 `.claude-plugin/plugin.json`），所以放進
`~/.claude/skills/` 之後會自動掛上兩樣東西：

| | 做什麼 | 範圍 |
|---|---|---|
| **UserPromptSubmit hook** | 每則訊息送出當下就解碼，結果直接附在訊息旁 | 你的**所有**專案 |
| **skill** | AI 需要更多細節時載入的完整說明與工具 | 你的**所有**專案 |

真正讓你「不用打前綴」的是 hook —— 它不是「AI 決定要不要查」，而是「東西已經在那了」。

不想要自動 hook、只想保留 skill 的話，刪掉 `.claude-plugin/` 這個資料夾即可。

---

## 用起來是什麼樣子

你打了一長串，中間有好幾段忘了切：

```
你可以幫我把變更都上 git a8 ? 2/3uvu84 ji3ul41j4gj3 到測試機
```

AI 看到的（hook 自動附上，你什麼都不用做）：

```
[注音還原] 2/3uvu84 -> 等一下
[注音還原] ji3ul41j4gj3 -> 我要部屬
你可以幫我把變更都上 git a8 ? 2/3uvu84 ji3ul41j4gj3 到測試機
```

於是它直接照「等一下我要部署到測試機」動作，不會再問你「`2/3uvu84` 是什麼意思」，
也不會跑任何工具去查。

（`a8` = 嗎 只有一個音節、信心中等，hook 刻意不提示 —— 寧可少講也不亂猜。
這種短片段 AI 通常從上下文就看懂了。）

`git`、`login.py`、`npm` 這類技術字串完全不會被碰。

> 注意上面的 **部屬 → 部署**。這兩個詞注音完全相同（ㄅㄨˋ ㄕㄨˇ），詞典只看詞頻，
> 挑了日常較常見的「部屬」。但 AI 看得到你在講 git 和測試機，會自己修成「部署」。
> 這是刻意的分工：程式負責把音還原對，選字交給有上下文的 AI —— 這正是標準輸入法
> 做不到的地方。

---

## 它不會亂翻你的程式碼

這是設計上最花力氣的地方。因為 26 個英文字母**全部**都對應到注音鍵，
「看起來像亂碼」不能當判斷依據，否則它會熱心到把 `npm run dev` 也翻成中文。

三道防線：

1. **硬排除** —— 程式碼區塊、行內 code、URL、路徑、git hash、CLI flag、版本號、
   含大寫的識別字，一律跳過。
2. **音節合法性** —— 要能完整切成合法的國語音節。`github` 切不出來，直接放過。
3. **信心分級** —— 只有高信心才會靜默還原；曖昧的寧可不動。

實測掃過 72 個常見技術字串（`npm`、`git`、commit hash、`utf-8`、`k8s`、`iso8601`、
`python3`、`config.py`…）全部正確放過。測試套件共 **72 項，其中 27 項專門守這件事**。

---

## 進階功能

### 打錯鍵也救得回來

相鄰兩鍵打反是快打時的常見手誤。例如「說」的注音是 ㄕㄨㄛ，要打 `gji`，快打成 `jgi`：

下面這句的最後一段 `gp6ak78a`，是把「嗎」的 `a8` 打成了 `8a`。整段因此切不出合法
音節，舊版會直接放棄；現在它會多給一個 `repair` 建議：

```
su3d042k72j/3ji3y94gji gp6ak78a ?

  你看的懂我再說            ← 前半段照常還原
  gp6ak78a  (無中文)        ← 這段本身解不出來
      repair: gp6ak7a8 -> 什麼嗎   ← 但把兩鍵對調就通了
```

AI 收到這些線索後，會理解成「你看得懂我在說什麼嗎？」——
注意 **的/得**、**再/在** 這些同音字也是它順手修掉的。

`repair` 只是建議：**不會覆蓋原本的解讀、也不會提高信心值**，
若建議在語境中不通，AI 會退回原解讀。

### 健檢：確認它還活著

hook 刻意設計成「壞掉也絕不吭聲」——因為依 Claude Code 規格，這類 hook 若回了
特定離開碼，會**擋下並清除你正在送的訊息**。寧可安靜失效，也不能擋你打字。

代價是失效無聲無息。所以附了一支健檢工具（Windows）：

```powershell
.\check.ps1
```

它檢查五項，最後一項是**真的餵訊息進去比對輸出** —— 因為前四項（註冊在、python 在、
腳本在、路徑對）全過，仍可能因詞典檔遺失而整個壞掉。有問題會明講壞在哪、怎麼修，
並以非 0 離開碼結束。

---

## 直接當命令列工具用

不透過 Claude Code 也能單獨使用：

```bash
# 精簡 JSON（給 LLM 讀，約完整輸出的 10%）
python scripts/decode_bopomofo.py --brief "幫我修一下 su3cl3a8"

# 只印還原後的字串
python scripts/decode_bopomofo.py --text "su3cl3a8"

# 完整 JSON（含每個 token 的分析，除錯用）
python scripts/decode_bopomofo.py --full "su3cl3a8"

# 測試
python tests/run_tests.py
python scripts/decode_bopomofo.py --selftest
```

---

## 運作原理

```
輸入
  │
  ├─ Layer A  按鍵 → 注音    純查表，100% 確定
  │
  ├─ Layer B  偵測 + 信心    音節切分 + 排除規則 + 信心分級
  │
  └─ Layer C  注音 → 中文    詞典最大機率斷詞，給出中文猜測
                             LLM 再用上下文確認 / 修正
```

**為什麼 Layer A 一定要用程式**：LLM 自己心算按鍵映射會出錯 —— 常見錯誤是把 `dj94`
說成「是的」，其實是「快」。這層必須確定性。

**為什麼 Layer C 留一半給 LLM**：詞典只看詞頻、不看上下文。同音字（`ㄕˋ` = 是/事/世/市…）
要靠前後文才選得準，而這正是標準 IME 做不到、LLM 擅長的。

Layer C 用一元語言模型加逐詞懲罰（`Σ log(freq) − k·log(total)`）做斷詞，
逐詞懲罰正好抑制過度切碎，讓「媽媽」贏過「嗎+嗎」。

---

## 檔案結構

```
bopomofo-input-recovery/
├── SKILL.md                  # 觸發條件 + 給 AI 的行為指示
├── .claude-plugin/
│   └── plugin.json           # 讓它同時是 plugin，才能自動掛 hook
├── hooks/
│   ├── hooks.json            # UserPromptSubmit 註冊
│   └── bopomofo_hook.py      # 每則訊息的解碼器（永遠 exit 0）
├── scripts/
│   ├── decode_bopomofo.py    # 核心：按鍵→注音→中文
│   └── build_dict.py         # 由 tsi.src 重建字典（建置期用）
├── data/
│   ├── bopomofo_dict.tsv     # 注音字典（詞+注音+詞頻，~4.7MB）
│   └── NOTICE.md             # 資料來源與 BSD 授權
├── references/               # 鍵盤對照表、排除規則
├── tests/                    # 72 項測試（含 27 項誤判守門）
├── check.ps1                 # hook 健檢（Windows）
└── install.ps1               # 選用：安裝到單一專案（Windows）
```

---

## 授權與資料來源

字典由 **libtabe** 的 `tsi.src`（BSD 授權，經 libchewing 散布）處理而來，
詳見 [data/NOTICE.md](data/NOTICE.md)。重新散布時請一併保留該 NOTICE。

---

## 已知限制

- 僅支援**大千式（標準）注音鍵盤**。倚天、許氏等配置需另建對照表。
- 純字母、不含數字的誤打（如 工 = `ej/`）會被壓在低信心、不主動還原 ——
  因為與英文難以區分。這種情況需要 AI 依上下文判斷。
- **中英之間沒有空白時可能會漏**。以整個 token 判斷，所以 `git a8`（有空白）還得出
  「git 嗎」，但 `gita8`（黏在一起）整段都會被放過 —— 因為 `gita8` 硬解出來是
  ㄕㄛㄔㄇㄚ 這種無意義的音，程式寧可放過也不亂猜。
