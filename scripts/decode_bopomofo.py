#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
decode_bopomofo.py — 注音鍵盤誤打還原（keystroke -> 注音 -> 信心分數）

用途：使用者在英文輸入模式下用注音鍵盤打字，會產生像 "su3cl3a8" 這種
看起來像亂碼的 ASCII 串（其實是按鍵序列）。這支程式把按鍵**確定性地**
還原成注音符號，並判斷這段文字有多像「誤打的中文」。

設計原則：
  1. 按鍵 -> 注音：純查表，100% 確定，不靠猜。
  2. 偵測：用「能不能完整切成合法國語音節」來區分誤打中文 vs 英文/技術字串。
  3. 排除：程式碼、路徑、網址、git hash、CLI flag、版本號等一律跳過。
  4. 注音 -> 中文：這支程式**不做**，交給有上下文的 LLM 決定選字。
     （之後的 phase 2 會加離線詞典，讓這一步也能在程式內完成。）

輸出：JSON（給 LLM 讀）。也支援 --text 只印還原後的注音字串。

用法：
  python decode_bopomofo.py "幫我修一下 su3cl3a8"
  echo "su3cl3a8" | python decode_bopomofo.py
  python decode_bopomofo.py --text "su3cl3a8"
  python decode_bopomofo.py --selftest
"""

import sys
import os
import json
import math
import argparse
import re

# --------------------------------------------------------------------------
# 1. 大千式（標準）注音鍵盤對照表
#    每個鍵盤按鍵 -> 一個注音符號 / 聲調符號
# --------------------------------------------------------------------------
KEY_TO_BOPOMOFO = {
    # 數字列：1~5 為注音，6/3/4/7 為聲調，8/9/0/- 為韻母
    '1': 'ㄅ', '2': 'ㄉ', '3': 'ˇ', '4': 'ˋ', '5': 'ㄓ',
    '6': 'ˊ', '7': '˙', '8': 'ㄚ', '9': 'ㄞ', '0': 'ㄢ', '-': 'ㄦ',
    # 上排 QWERTY
    'q': 'ㄆ', 'w': 'ㄊ', 'e': 'ㄍ', 'r': 'ㄐ', 't': 'ㄔ',
    'y': 'ㄗ', 'u': 'ㄧ', 'i': 'ㄛ', 'o': 'ㄟ', 'p': 'ㄣ',
    # 中排 ASDF（home row）
    'a': 'ㄇ', 's': 'ㄋ', 'd': 'ㄎ', 'f': 'ㄑ', 'g': 'ㄕ',
    'h': 'ㄘ', 'j': 'ㄨ', 'k': 'ㄜ', 'l': 'ㄠ', ';': 'ㄤ',
    # 下排 ZXCV
    'z': 'ㄈ', 'x': 'ㄌ', 'c': 'ㄏ', 'v': 'ㄒ', 'b': 'ㄖ',
    'n': 'ㄙ', 'm': 'ㄩ', ',': 'ㄝ', '.': 'ㄡ', '/': 'ㄥ',
}
# 第一聲沒有符號（按空白），二聲 ˊ=6、三聲 ˇ=3、四聲 ˋ=4、輕聲 ˙=7
ALLOWED_KEYS = set(KEY_TO_BOPOMOFO.keys())

# --------------------------------------------------------------------------
# 2. 注音音節結構：聲母 + 韻母(含介音) + 聲調
# --------------------------------------------------------------------------
INITIALS = set('ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ')   # 21 聲母
MEDIALS = set('ㄧㄨㄩ')                                        # 介音
TONES = set('ˊˇˋ˙')                                          # 聲調符號（一聲無符號）

# 合法韻母（韻母 = 介音? + 韻尾 的固定組合）。用固定清單比「介音+韻尾亂配」更準，
# 可避免像 ㄩㄤ 這種不存在的組合被誤判為合法。
_RIME_STRINGS = [
    # 單韻母 / 空韻以外
    'ㄚ', 'ㄛ', 'ㄜ', 'ㄝ', 'ㄞ', 'ㄟ', 'ㄠ', 'ㄡ', 'ㄢ', 'ㄣ', 'ㄤ', 'ㄥ', 'ㄦ',
    # 介音單獨成韻
    'ㄧ', 'ㄨ', 'ㄩ',
    # ㄧ 系
    'ㄧㄚ', 'ㄧㄛ', 'ㄧㄝ', 'ㄧㄞ', 'ㄧㄠ', 'ㄧㄡ', 'ㄧㄢ', 'ㄧㄣ', 'ㄧㄤ', 'ㄧㄥ',
    # ㄨ 系
    'ㄨㄚ', 'ㄨㄛ', 'ㄨㄞ', 'ㄨㄟ', 'ㄨㄢ', 'ㄨㄣ', 'ㄨㄤ', 'ㄨㄥ',
    # ㄩ 系
    'ㄩㄝ', 'ㄩㄢ', 'ㄩㄣ', 'ㄩㄥ',
]
RIMES = set(tuple(r) for r in _RIME_STRINGS)

# 可以「只有聲母、沒有韻母」的空韻聲母：ㄓㄔㄕㄖㄗㄘㄙ（如 是=ㄕˋ、日=ㄖˋ）
BARE_OK = set('ㄓㄔㄕㄖㄗㄘㄙ')


# --------------------------------------------------------------------------
# 3. 按鍵 -> 注音符號
# --------------------------------------------------------------------------
def keys_to_symbols(keys):
    """把一串鍵盤按鍵轉成注音符號 list。未知按鍵回傳 None（代表無法解析）。"""
    symbols = []
    for ch in keys:
        if ch not in KEY_TO_BOPOMOFO:
            return None
        symbols.append(KEY_TO_BOPOMOFO[ch])
    return symbols


# --------------------------------------------------------------------------
# 4. 音節切分（DP）：判斷一串注音符號能否完整切成合法音節
# --------------------------------------------------------------------------
def _with_optional_tone(symbols, k):
    """在位置 k 之後，若下一個是聲調符號則可多吃一個。回傳可能的結束位置集合。"""
    ends = {k}
    if k < len(symbols) and symbols[k] in TONES:
        ends.add(k + 1)
    return ends


def _syllable_ends(symbols, i):
    """回傳所有 j，使得 symbols[i:j] 剛好是一個合法音節。"""
    ends = set()
    n = len(symbols)
    # (A) 有聲母
    if i < n and symbols[i] in INITIALS:
        init = symbols[i]
        # A1: 聲母 + 韻母(2 或 1 個符號) + 選擇性聲調
        for rl in (2, 1):
            if i + 1 + rl <= n and tuple(symbols[i + 1:i + 1 + rl]) in RIMES:
                ends |= _with_optional_tone(symbols, i + 1 + rl)
        # A2: 空韻聲母（只有聲母沒韻母）+ 選擇性聲調
        if init in BARE_OK:
            ends |= _with_optional_tone(symbols, i + 1)
    # (B) 沒聲母，直接韻母（如 一=ㄧ、我=ㄨㄛ、愛=ㄞ）
    for rl in (2, 1):
        if i + rl <= n and tuple(symbols[i:i + rl]) in RIMES:
            ends |= _with_optional_tone(symbols, i + rl)
    return ends


def segment(symbols):
    """
    若整串 symbols 能完整切成合法音節，回傳音節 list（每個音節是符號 list）；
    否則回傳 None。

    偏好「音節數最少」的切法（音節盡量長），這符合自然斷音，也能解決像
    ㄊㄧㄢ 到底是「天」(1 音節) 還是「剔安」(2 音節) 的歧義 —— 選較長的天。
    """
    if not symbols:
        return None
    n = len(symbols)
    INF = float('inf')
    dp = [INF] * (n + 1)     # dp[i] = 覆蓋 symbols[0:i] 的最少音節數
    prev = [None] * (n + 1)
    dp[0] = 0
    for i in range(n):
        if dp[i] == INF:
            continue
        for j in _syllable_ends(symbols, i):
            if dp[i] + 1 < dp[j]:
                dp[j] = dp[i] + 1
                prev[j] = i
    if dp[n] == INF:
        return None
    # 回溯切點
    cuts = []
    k = n
    while k > 0:
        cuts.append((prev[k], k))
        k = prev[k]
    cuts.reverse()
    return [symbols[a:b] for a, b in cuts]


# --------------------------------------------------------------------------
# 5. 排除規則：這個 token 是技術字串 / 明顯不是誤打中文嗎？
# --------------------------------------------------------------------------
# 從 token 兩端剝掉的「包裝」標點（引號、括號、中英文句讀等）。
# 也含 ASCII 句讀 , . ! ? : ; —— 這些雖然是注音鍵，但出現在 token 尾端時多半是
# 句子標點，不剝掉會被解成多餘音節（如 su3cl3a8, -> 你好嗎誒、cl3. -> 好偶）。
# 只剝「兩端」，夾在中間的仍當注音保留（vu,4=謝、1;ji3d04uvu84=幫我看一下）。
_WRAP_CHARS = '"\'`()[]{}<>「」『』（）【】，。、！？：；,.!?:;…—　 \t\r\n'

# 常見開發用詞，剛好能切成合法音節但幾乎不可能是誤打中文。維持小而精，
# 長尾交給下游 LLM 判斷與 phase 2 詞典。
_TECH_DENYLIST = {
    'utf8', 'utf16', 'x86', 'x64', 'mp3', 'mp4', 'h264', 'h265',
    'p50', 'p90', 'p95', 'p99', 'sha1', 'md5', 'crc32',
    # 常見「執行檔/套件 + 版本」短詞：字母後接單一版本數字，會切成合法音節而被誤判。
    # 較長的(python3/jdk8…)由 score_candidate 的結構化規則擋下；這裡收短的 2 音節款。
    'py2', 'py3', 'php4', 'php5', 'php7', 'php8', 'vue2', 'vue3',
}

# 一眼就是技術字串的樣式
_RE_URLSCHEME = re.compile(r'://')
_RE_PATHISH = re.compile(r'(^[~./])|(//)|([\\])|(^[a-zA-Z]:)')   # 路徑 / drive letter
_RE_FLAG = re.compile(r'^-{1,2}[a-z0-9]')                        # CLI flag: -x / --xxx
_RE_NUMERIC = re.compile(r'^[0-9]+([.,][0-9]+)*$')               # 純數字 / 版本號
# 副檔名須以字母開頭(.py/.js/.md…)。純數字/單一數字的「副檔名」多半是注音的
# ㄡ鍵(.)接聲調數字(如 qk4ru.6 = ㄆㄜˋ ㄐㄧㄡˊ),不可當檔名排除,要放行去切音節。
_RE_FILENAME = re.compile(r'^[a-z0-9_-]+\.[a-z][a-z0-9]{0,5}$')  # filename.ext(副檔名字母開頭)
# git commit hash:純小寫 hex、長度 7~40。全是注音鍵又常帶數字,會躲過其他規則被誤還原
# (如 55a9d0096c87 -> 之只賣看安癌哈)。SKILL 承諾跳過 hash,故明確排除。真誤打中文幾乎
# 一定含 hex 以外的鍵(s/u/l/i/o…)或長度不足,不會誤傷。
_RE_HEXHASH = re.compile(r'^[0-9a-f]{7,40}$')


def strip_wrappers(token):
    """剝掉 token 兩端的包裝標點，回傳 (core, prefix, suffix)。"""
    i, j = 0, len(token)
    while i < j and token[i] in _WRAP_CHARS:
        i += 1
    while j > i and token[j - 1] in _WRAP_CHARS:
        j -= 1
    return token[i:j], token[:i], token[j:]


def exclusion_reason(core):
    """若 core 應被排除（不是誤打中文的候選），回傳原因字串；否則回傳 None。"""
    if not core:
        return 'empty'
    if core.lower() in _TECH_DENYLIST:
        return 'tech_term'              # 常見開發用詞（utf8/x86/mp3…），非誤打中文
    if any(c.isupper() for c in core):
        return 'has_uppercase'          # 注音誤打一定是小寫；大寫多為 camelCase/常數/hash
    if any(c not in ALLOWED_KEYS for c in core):
        return 'non_keyboard_char'      # 含注音鍵盤以外字元（含中日韓字、@#$ 等）
    if _RE_URLSCHEME.search(core):
        return 'url'
    if _RE_PATHISH.search(core):
        return 'path'
    if _RE_FLAG.match(core):
        return 'cli_flag'
    if '-' in core:
        return 'hyphenated'             # utf-8、x86-64、well-known…（ㄦ 很少夾在詞中）
    if _RE_NUMERIC.match(core):
        return 'numeric_or_version'
    if _RE_HEXHASH.match(core):
        return 'git_hash'               # 純小寫 hex 且長度像 commit hash(7~40 碼)
    if _RE_FILENAME.match(core):
        return 'filename'
    return None


# --------------------------------------------------------------------------
# 6. 信心分數
# --------------------------------------------------------------------------
def score_candidate(core, syllables):
    """
    根據 token 內容給信心分數與分級。

    關鍵訊號是 token 裡的數字種類：
      - 聲調鍵 3/4/6/7：最強訊號。英文字不含數字，而真正打中文幾乎每個音節都帶
        聲調，所以有聲調鍵 + 能切音節 = 幾乎確定是誤打中文 -> high。
      - 韻母鍵 8/9/0（ㄚㄞㄢ）但無聲調：可能是一聲字（如 媽媽=a8a8、天=wu0），
        但也可能是帶版本號的技術詞，所以最高只到 medium，讓 LLM 用上下文確認。
      - 完全沒數字：純字母如 npm/git/html 都能硬切成音節，本質曖昧 -> low。
    """
    has_tone_key = any(c in '3467' for c in core)   # 聲調鍵
    has_vowel_digit = any(c in '890' for c in core)  # 韻母鍵 ㄚㄞㄢ
    has_any_digit = any(c.isdigit() for c in core)
    n_syll = len(syllables)
    key_len = len(core)

    conf = 0.55                                     # 能完整切音節的基底分
    if has_tone_key:
        conf += 0.35
    elif has_vowel_digit:
        conf += 0.20
    if n_syll >= 2:
        conf += 0.05
    if key_len >= 4:
        conf += 0.03
    conf = min(conf, 0.98)

    # 上限：沒聲調鍵最多 medium；完全沒數字壓到 low。
    if not has_any_digit:
        conf = min(conf, 0.60)
    elif not has_tone_key:
        conf = min(conf, 0.85)

    # 「英文指令 + 版本號」防線：像 python3 / jdk8 會被切成 3 個以上音節、卻只有單一
    # 數字(多半是字尾那個),而真正誤打中文幾乎每音節都帶聲調/韻母鍵、數字會散布。
    # 故「≥3 音節且數字 ≤1 個」壓到 low,避免高信心靜默還原毀掉 CLI 指令。
    n_digits = sum(c.isdigit() for c in core)
    if n_syll >= 3 and n_digits <= 1:
        conf = min(conf, 0.60)

    if conf >= 0.90:
        tier = 'high'       # 幾乎確定：可靜默還原
    elif conf >= 0.65:
        tier = 'medium'     # 可能：簡短標註推測後繼續
    else:
        tier = 'low'        # 曖昧：僅在上下文明顯時才採用

    signals = []
    if has_tone_key:
        signals.append('tone_marks')
    elif has_vowel_digit:
        signals.append('vowel_digit')
    if n_syll >= 2:
        signals.append('multi_syllable')
    return round(conf, 3), tier, signals


# --------------------------------------------------------------------------
# 6.5 注音 -> 中文（詞典 DP，Phase 2a）
#     用一元語言模型 + 逐詞懲罰做最大機率斷詞：
#         score = Σ log(freq_i) − k·log(TOTAL)   （k = 詞數）
#     逐詞懲罰 log(TOTAL) 正好懲罰過度切碎，讓「媽媽」勝過「嗎+嗎」。
#     詞典缺席時所有函式安靜地回傳 None，退回 Phase 1 行為。
# --------------------------------------------------------------------------
_DICT_TONES = set('ˊˇˋ˙')
_MAXWORD = 8            # 詞典中最長詞的音節數上限（DP 每個位置最多試這麼長）
_TONE_BONUS = 6.0      # 使用者聲調與候選讀音相符時的加分
_DICT_CACHE = None      # (dict, word_penalty)；None 表示尚未載入


def _strip_tones(syllable):
    return ''.join(c for c in syllable if c not in _DICT_TONES)


def _default_dict_path():
    # 環境變數可覆寫（方便測試無詞典的退化行為、或給 phase-2b hook 指定路徑）
    env = os.environ.get('BOPOMOFO_DICT')
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), 'data', 'bopomofo_dict.tsv')


def load_dictionary(path=None):
    """
    載入 data/bopomofo_dict.tsv -> ({toneless_key: [(word, toned, freq), ...]},
    word_penalty)。每個 key 的候選已依頻率由高到低排序（build_dict.py 保證）。
    找不到檔案時回傳 ({}, 0.0)，呼叫端據此退回 Phase 1。
    """
    global _DICT_CACHE
    if _DICT_CACHE is not None:
        return _DICT_CACHE
    path = path or _default_dict_path()
    table = {}
    total = 0
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                row = line.rstrip('\n').split('\t')
                if len(row) != 4:
                    continue
                key, word, toned, freq = row[0], row[1], row[2], row[3]
                try:
                    freq = int(freq)
                except ValueError:
                    continue
                table.setdefault(key, []).append((word, toned, freq))
                total += freq
    word_penalty = math.log(total) if total > 0 else 0.0
    _DICT_CACHE = (table, word_penalty)
    return _DICT_CACHE


def decode_chinese(syllables):
    """
    syllables: 含聲調的注音音節字串 list，如 ['ㄋㄧˇ','ㄏㄠˇ','ㄇㄚ']。
    回傳 {'chinese', 'words', 'alternatives'} 或 None（詞典缺席/無法完整覆蓋）。
    """
    table, word_penalty = load_dictionary()
    if not table:
        return None

    n = len(syllables)
    toneless = [_strip_tones(s) for s in syllables]
    NEG = float('-inf')
    score = [NEG] * (n + 1)
    score[0] = 0.0
    back = [None] * (n + 1)     # (prev_i, word, key)

    for i in range(n):
        if score[i] == NEG:
            continue
        for L in range(1, min(_MAXWORD, n - i) + 1):
            key = ' '.join(toneless[i:i + L])
            entries = table.get(key)
            if not entries:
                continue
            span_toned = ' '.join(syllables[i:i + L])
            # 只在使用者「明確按了聲調鍵」時才給聲調加分。沒聲調（如 a8=ㄇㄚ 一聲）
            # 是弱證據，不該把「一聲讀音的字」硬推贏「高頻但輕聲的字」（媽 vs 嗎）。
            has_explicit_tone = any(c in _DICT_TONES for c in span_toned)
            best_local = None       # (local_score, word)
            for word, toned, freq in entries:
                s = math.log(freq + 1) - word_penalty
                if has_explicit_tone and toned == span_toned:
                    s += _TONE_BONUS
                if best_local is None or s > best_local[0]:
                    best_local = (s, word)
            cand = score[i] + best_local[0]
            if cand > score[i + L]:
                score[i + L] = cand
                back[i + L] = (i, best_local[1], key)

    if score[n] == NEG:
        return None                 # 無法用詞典完整覆蓋

    # 回溯出詞序列
    spans = []
    k = n
    while k > 0:
        pi, word, key = back[k]
        spans.append((pi, k, word, key))
        k = pi
    spans.reverse()

    words = [w for _, _, w, _ in spans]
    alternatives = []
    for _, _, word, key in spans:
        others = [w for (w, _t, _f) in table.get(key, []) if w != word][:4]
        if others:
            alternatives.append({'reading': key, 'chosen': word, 'others': others})
    return {'chinese': ''.join(words), 'words': words, 'alternatives': alternatives}


# 補救：相鄰兩鍵對調（快打手誤）。core 超過這個長度就跳過，避免長字串爆炸。
_MAX_REPAIR_LEN = 24
_MAX_REPAIR_SUGGESTIONS = 3


def try_transpose_repair(core, limit=_MAX_REPAIR_SUGGESTIONS, require_word=False):
    """
    音節切得出來、信心也高，卻一個中文都還不出來時的補救。

    常見手誤是相鄰兩鍵打反：「說」= ㄕㄨㄛ 應打 gji，快打成 jgi，
    切出來變 ['ㄨ','ㄕㄛ'] —— 音節合法但詞典查無此詞。這裡窮舉「只對調一次
    相鄰兩鍵」的所有變體，看哪個能讓詞典完整還原。

    回傳建議 list（最多 limit 個）。這只是建議：呼叫端仍須用上下文判斷，
    原始解讀不會被覆蓋、信心也不會因此提高。
    """
    if len(core) > _MAX_REPAIR_LEN:
        return []
    found = []
    seen = set()
    for i in range(len(core) - 1):
        if core[i] == core[i + 1]:
            continue                                    # 對調同樣的字元沒意義
        variant = core[:i] + core[i + 1] + core[i] + core[i + 2:]
        if variant in seen:
            continue
        seen.add(variant)
        symbols = keys_to_symbols(variant)
        if symbols is None:
            continue
        syl = segment(symbols)
        if syl is None:
            continue
        dec = decode_chinese([''.join(s) for s in syl])
        if not dec:
            continue
        if require_word and max((len(w) for w in dec['words']), default=0) < 2:
            # 還原結果全是單字串接（額+哪、喔+內+啊+版）＝雜訊，不是真的詞。
            # 只有放寬過的呼叫端（整段切不出音節那條路）需要這道額外門檻。
            continue
        found.append({
            'kind': 'transpose',
            'from': core,
            'to': variant,
            'chinese': dec['chinese'],
            'note': '相鄰兩鍵對調後詞典可完整還原',
        })
        if len(found) >= limit:
            break
    return found


# --------------------------------------------------------------------------
# 7. 分析單一 token
# --------------------------------------------------------------------------
def analyze_token(token):
    """分析一個 token，回傳 dict。is_candidate 為 True 代表疑似誤打中文。"""
    core, prefix, suffix = strip_wrappers(token)
    result = {'token': token, 'core': core, 'is_candidate': False}

    reason = exclusion_reason(core)
    if reason:
        result['reason'] = reason
        return result

    symbols = keys_to_symbols(core)
    if symbols is None:
        result['reason'] = 'unmappable'
        return result

    syllables = segment(symbols)
    if syllables is None:
        # 手誤可能讓「整段」都切不出音節（「嗎」ㄇㄚ 應打 a8，打成 8a），此時既有的
        # repair 完全輪不到，token 連候選都不會產生。這裡再試一輪相鄰兩鍵對調。
        #
        # 這條路徑會放寬判定，所以門檻比一般路徑更嚴：變體必須「切得出音節」**且**
        # 「詞典能完整還原成中文詞」才算數（try_transpose_repair 已強制兩者）。
        # 注意順序：先擋掉沒有數字的 token 再談補救。score_candidate 對無數字者
        # 一律壓到 low（不會成為候選），所以這個提前返回不改變任何結果，
        # 卻能讓純英文完全不碰詞典 —— hook 跑在每則訊息上，這個快速路徑很重要。
        if not any(c.isdigit() for c in core):
            result['reason'] = 'not_valid_syllables'
            return result
        # require_word：還原結果必須含至少一個多字詞。整段切不出音節本來就是較弱的
        # 證據，若「修好」之後只是一串單字串接（k8s -> 額哪），那幾乎必然是雜訊。
        repair = try_transpose_repair(core, require_word=True)
        if not repair:
            result['reason'] = 'not_valid_syllables'   # 切不出合法音節 -> 多半是英文
            return result
        rep_syllables = segment(keys_to_symbols(repair[0]['to']))
        # 用變體的音節評分；core 字元組成未變，聲調/數字訊號與原本完全一致，
        # 不會因為「轉置成功」本身而加分。
        conf, tier, signals = score_candidate(core, rep_syllables)
        if tier == 'low':
            result['reason'] = 'not_valid_syllables'
            return result
        syllable_strs = [''.join(s) for s in rep_syllables]
        result.update({
            'is_candidate': True,
            # 原字串本身切不出音節，這裡的注音來自對調後的變體，故標記出處。
            'bopomofo': ' '.join(syllable_strs),
            'bopomofo_joined': ''.join(syllable_strs),
            'syllables': syllable_strs,
            'n_syllables': len(rep_syllables),
            'confidence': round(conf, 3),
            'tier': tier,
            'signals': signals + ['from_transpose_repair'],
            'prefix': prefix,
            'suffix': suffix,
            'repair': repair,
        })
        # 刻意不設 chinese：原字串沒有成立的解讀，中文只存在於 repair 建議裡，
        # 由呼叫端依上下文決定要不要採用。
        return result

    conf, tier, signals = score_candidate(core, syllables)
    syllable_strs = [''.join(s) for s in syllables]

    # Phase 2a：用詞典把注音還原成中文。只對 medium/high 候選做，因為純字母英文
    # （已被壓到 low）也可能碰巧對到某些字，不該讓詞典把它「還原」成中文。
    chinese = None
    chinese_alts = None
    if tier in ('medium', 'high'):
        dec = decode_chinese(syllable_strs)
        if dec:
            chinese = dec['chinese']
            chinese_alts = dec['alternatives']
            # 詞典能完整覆蓋且為多音節 -> 幾乎確定是真中文，升到 high
            if tier == 'medium' and len(syllables) >= 2:
                tier = 'high'
                conf = max(conf, 0.90)

    result.update({
        'is_candidate': True,
        'bopomofo': ' '.join(syllable_strs),        # 空白分隔的注音（每音節一組）
        'bopomofo_joined': ''.join(syllable_strs),
        'syllables': syllable_strs,
        'n_syllables': len(syllables),
        'confidence': round(conf, 3),
        'tier': tier,
        'signals': signals,
        'prefix': prefix,
        'suffix': suffix,
    })
    if chinese:
        result['chinese'] = chinese                  # 詞典最佳猜測（LLM 仍應用上下文確認）
        result['chinese_alternatives'] = chinese_alts
    else:
        # 音節切得出來、信心也高，卻還不出中文 -> 很可能是相鄰兩鍵打反。
        # 給建議但不覆蓋原解讀、不調整 confidence，最終由呼叫端依上下文決定。
        if tier in ('medium', 'high') and len(syllables) >= 2:
            repair = try_transpose_repair(core)
            if repair:
                result['repair'] = repair
    return result


# --------------------------------------------------------------------------
# 8. 分析整段文字
# --------------------------------------------------------------------------
def _mask_code_spans(text):
    """把 ``` fenced ``` 與 `inline code` 換成等長空白，避免動到程式碼。"""
    text = re.sub(r'```.*?```', lambda m: ' ' * len(m.group(0)), text, flags=re.DOTALL)
    text = re.sub(r'`[^`]*`', lambda m: ' ' * len(m.group(0)), text)
    return text


def analyze_text(text):
    """
    分析整段輸入。回傳:
      - segments: 每個 token 的分析
      - candidates: 其中疑似誤打中文的（medium/high）
      - reconstructed: 把候選換成中文（詞典可用時）或 [注音] 的整句版本，給 LLM 讀
      - has_candidates: 是否有 medium/high 候選
    詞典給的是最佳猜測；最終選字仍應由 LLM 依上下文確認。
    """
    masked = _mask_code_spans(text)
    # 切 token:不只在空白切,也在「非空白 ASCII 串 vs 其他(中文/空白/被遮的 code)」交界切開。
    # 中文不加空白,誤打常和中文黏在一起(幫我修一下su3cl3a8);用 [!-~]+(可見 ASCII 非空白)
    # 把 ASCII 串單獨抓出來分析,才能涵蓋這個主要情境。re.split 的偶數段=中文/空白/其他
    # (原樣保留),奇數段=ASCII 串(送去分析)。偵測跑遮罩後字串;reconstructed 用原文對應片段,
    # 才不會把行內 code 還原成空白、遺失使用者指令(run `npm install` su3cl3a8 要保留該指令)。
    parts = re.split(r'([!-~]+)', masked)
    segments = []
    rebuilt = []
    candidates = []
    pos = 0
    for idx, part in enumerate(parts):
        orig = text[pos:pos + len(part)]        # 與 masked 等長，對齊回原文
        pos += len(part)
        if idx % 2 == 0:
            rebuilt.append(orig)                # 中文 / 空白 / 被遮成空白的 code -> 原樣保留
            continue
        info = analyze_token(part)
        segments.append(info)
        if info.get('is_candidate') and info.get('tier') in ('medium', 'high'):
            candidates.append(info)
            # 有中文猜測就用中文，否則退回 [注音]
            body = info.get('chinese') or '[%s]' % info['bopomofo_joined']
            rebuilt.append('{prefix}{body}{suffix}'.format(
                prefix=info.get('prefix', ''),
                body=body,
                suffix=info.get('suffix', ''),
            ))
        else:
            rebuilt.append(orig)                # 非候選 -> 用原文重建（而非遮罩後的空白）

    return {
        'original': text,
        'has_candidates': len(candidates) > 0,
        'candidates': candidates,
        'segments': segments,
        'reconstructed': ''.join(rebuilt),
    }


# --------------------------------------------------------------------------
# 9. 自我測試
# --------------------------------------------------------------------------
def selftest():
    """快速 sanity check：對照表大小 + 幾個已知案例。"""
    ok = True

    # 對照表：小寫字母 26 + 數字 10 + 5 個標點(- ; , . /) = 41
    expected_keys = 26 + 10 + 5
    if len(KEY_TO_BOPOMOFO) != expected_keys:
        print('FAIL 對照表鍵數 = %d，預期 %d' % (len(KEY_TO_BOPOMOFO), expected_keys))
        ok = False

    # 正例：應被判為候選，且注音正確
    positives = [
        ('su3cl3a8', 'ㄋㄧˇ ㄏㄠˇ ㄇㄚ'),   # 你好嗎（嗎的輕聲省略）
        ('cl3', 'ㄏㄠˇ'),                    # 好
        ('g4', 'ㄕˋ'),                       # 是
        ('dj94', 'ㄎㄨㄞˋ'),                 # 快
        ('vu,4', 'ㄒㄧㄝˋ'),                 # 謝
    ]
    for keys, expect in positives:
        info = analyze_token(keys)
        if not info['is_candidate']:
            print('FAIL 正例被漏判: %s (%s)' % (keys, info.get('reason')))
            ok = False
        elif info['bopomofo'] != expect:
            print('FAIL 注音不符: %s -> %s，預期 %s' % (keys, info['bopomofo'], expect))
            ok = False

    # 反例：不該進 medium/high（避免誤觸發技術字串）
    negatives = ['npm', 'git', 'http', './src/app.py', '--verbose',
                 '2024.1', 'GitHub', 'config.py', 'issue721',
                 'utf8', 'x86', 'mp3', 'p95', 'sha256', 'base64']
    for tok in negatives:
        res = analyze_text(tok)
        if res['has_candidates']:
            print('FAIL 反例誤觸發: %s -> %s' % (tok, res['candidates']))
            ok = False

    # 回歸（Codex P2）：尾隨 ASCII 標點應保留為後綴，不可被解成多餘音節
    recon = analyze_text('su3cl3a8,')['reconstructed']
    if recon != '你好嗎,':
        print('FAIL 尾標點還原錯誤: %r，預期 %r' % (recon, '你好嗎,'))
        ok = False
    # 回歸（Codex P2）：行內 code 應原樣保留於 reconstructed，不可被還原成空白
    recon2 = analyze_text('run `npm install` su3cl3a8')['reconstructed']
    if 'npm install' not in recon2 or '你好嗎' not in recon2:
        print('FAIL 行內 code 未保留於 reconstructed: %r' % recon2)
        ok = False

    print('SELFTEST', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


# --------------------------------------------------------------------------
# 10. CLI
# --------------------------------------------------------------------------
# --brief 每個候選只保留這些欄位。呼叫端是 LLM，讀進去的每個字都是成本，
# 所以預設只給「判讀所需」：原字串、注音、中文、信心分級，外加 repair 建議。
_BRIEF_FIELDS = ('token', 'bopomofo', 'chinese', 'tier', 'repair')


def brief_result(result):
    """把完整結果壓成精簡版（見 _BRIEF_FIELDS）。"""
    return {
        'has_candidates': result['has_candidates'],
        'reconstructed': result['reconstructed'],
        'candidates': [
            {k: c[k] for k in _BRIEF_FIELDS if k in c}
            for c in result['candidates']
        ],
    }


def main(argv=None):
    # Windows 主控台預設 CP950，會把中文與注音印成亂碼，逼呼叫端補
    # PYTHONIOENCODING=utf-8 重跑一次。這裡直接鎖定 UTF-8，省掉那次往返。
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass        # Python < 3.7 沒有 reconfigure，或 stdout 已被替換

    parser = argparse.ArgumentParser(description='注音鍵盤誤打還原')
    parser.add_argument('text', nargs='*', help='要分析的文字（省略則讀 stdin）')
    parser.add_argument('--text', dest='text_only', action='store_true',
                        help='只印還原後字串，不印 JSON')
    parser.add_argument('--brief', action='store_true',
                        help='精簡 JSON：每個候選只留 token/注音/中文/tier/repair')
    parser.add_argument('--full', action='store_true',
                        help='完整 JSON，含 segments（全部 token 的分析，除錯用）')
    parser.add_argument('--selftest', action='store_true', help='跑自我測試')
    args = parser.parse_args(argv)

    if args.selftest:
        return selftest()

    if args.text:
        source = ' '.join(args.text)
    else:
        source = sys.stdin.read()
    source = source.rstrip('\n')

    result = analyze_text(source)
    if args.text_only:
        print(result['reconstructed'])
        return 0

    if args.brief:
        payload = brief_result(result)
    elif args.full:
        payload = result                     # 完整（含 segments）
    else:
        # 預設不輸出 segments：它是 candidates 的超集，內容重複、純浪費 token
        payload = {k: v for k, v in result.items() if k != 'segments'}
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
