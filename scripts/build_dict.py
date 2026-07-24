#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dict.py — 把 libtabe/libchewing 的 tsi.src 處理成精簡的注音字典。

輸入 tsi.src 每行格式：
    詞 頻率 注音1 注音2 ...
例如：
    你好 1227 ㄋㄧˇ ㄏㄠˇ
    是 182405 ㄕˋ

輸出 data/bopomofo_dict.tsv 每行：
    toneless_key <TAB> 詞 <TAB> toned_key <TAB> 頻率
其中 key 以「空白分隔的注音音節」保留音節邊界（避免 ㄊㄧㄢ 與 ㄊㄧ+ㄢ 混淆）：
    toneless_key = 去聲調的音節序列，如 "ㄋㄧ ㄏㄠ"
    toned_key    = 含聲調，如 "ㄋㄧˇ ㄏㄠˇ"

用法：
    python scripts/build_dict.py <tsi.src 路徑> [--phrase-min N] [--topk K]

資料來源與授權見 data/NOTICE.md（BSD，出自 libtabe，經 libchewing 散布）。
"""

import sys
import os
import argparse
from collections import defaultdict

_TONE_CHARS = set('ˊˇˋ˙')
# 所有注音符號 + 聲調：用來判斷某個「詞」其實只是注音符號（雜訊，非漢字）
_BPMF_ALL = set('ㄅㄆㄇㄈㄉㄊㄋㄌㄍㄎㄏㄐㄑㄒㄓㄔㄕㄖㄗㄘㄙ'
                'ㄚㄛㄜㄝㄞㄟㄠㄡㄢㄣㄤㄥㄦㄧㄨㄩ') | _TONE_CHARS


def strip_tones(syllable):
    return ''.join(c for c in syllable if c not in _TONE_CHARS)


def is_noise_word(word):
    """整個『詞』都是注音/聲調符號 -> 是 tsi.src 表頭那種雜訊，不是真的詞。"""
    return all(c in _BPMF_ALL for c in word)


def build(src_path, out_path, phrase_min, topk):
    # (toneless_key, word) -> (best_freq, toned_of_best)
    best = {}
    stats = defaultdict(int)
    max_nsyll = 0

    with open(src_path, encoding='utf-8') as f:
        for raw in f:
            parts = raw.split()
            if len(parts) < 3:
                continue
            word = parts[0]
            try:
                freq = int(parts[1])
            except ValueError:
                continue
            zhuyin = parts[2:]

            if freq < 1:
                stats['skip_freq0'] += 1
                continue
            if is_noise_word(word):
                stats['skip_noise'] += 1
                continue

            nsyll = len(zhuyin)
            if nsyll >= 2 and freq < phrase_min:
                stats['skip_rare_phrase'] += 1
                continue

            toned_key = ' '.join(zhuyin)
            toneless_key = ' '.join(strip_tones(z) for z in zhuyin)
            max_nsyll = max(max_nsyll, nsyll)

            k = (toneless_key, word)
            if k not in best or freq > best[k][0]:
                best[k] = (freq, toned_key)

    # 依 toneless_key 分組，組內依頻率排序，並限制每個 key 的候選數
    groups = defaultdict(list)
    for (toneless_key, word), (freq, toned_key) in best.items():
        groups[toneless_key].append((word, toned_key, freq))

    rows = 0
    singles = phrases = 0
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as out:
        for toneless_key in sorted(groups):
            cands = sorted(groups[toneless_key], key=lambda t: -t[2])[:topk]
            for word, toned_key, freq in cands:
                out.write('%s\t%s\t%s\t%d\n' % (toneless_key, word, toned_key, freq))
                rows += 1
                if ' ' in toneless_key:
                    phrases += 1
                else:
                    singles += 1

    size = os.path.getsize(out_path)
    print('來源           : %s' % src_path)
    print('輸出           : %s' % out_path)
    print('輸出行數       : %d  (單字 %d, 詞 %d)' % (rows, singles, phrases))
    print('distinct keys  : %d' % len(groups))
    print('最長音節數     : %d' % max_nsyll)
    print('輸出大小       : %.2f MB' % (size / 1024 / 1024))
    print('跳過(freq=0)   : %d' % stats['skip_freq0'])
    print('跳過(雜訊)     : %d' % stats['skip_noise'])
    print('跳過(冷門詞)   : %d  (phrase_min=%d)' % (stats['skip_rare_phrase'], phrase_min))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src', help='tsi.src 路徑')
    ap.add_argument('--out', default=None, help='輸出路徑（預設 data/bopomofo_dict.tsv）')
    ap.add_argument('--phrase-min', type=int, default=3,
                    help='多字詞的最低頻率（單字一律保留），預設 3')
    ap.add_argument('--topk', type=int, default=20,
                    help='每個 key 最多保留幾個候選，預設 20')
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    out_path = args.out or os.path.join(root, 'data', 'bopomofo_dict.tsv')
    build(args.src, out_path, args.phrase_min, args.topk)


if __name__ == '__main__':
    main()
