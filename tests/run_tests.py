#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_tests.py — 跑 cases.tsv 驗證 decode_bopomofo。

用法：
  python tests/run_tests.py
  python tests/run_tests.py --verbose      # 連通過的也印出來

離開碼 0 = 全過；非 0 = 有失敗。
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import decode_bopomofo as d  # noqa: E402


def load_cases(path):
    cases = []
    with open(path, encoding='utf-8') as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip('\n')
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            parts = line.split('\t')
            if len(parts) < 4:
                print('略過格式錯誤的行 %d: %r' % (lineno, line))
                continue
            kind, text = parts[0].strip(), parts[1]
            expect_bpm = parts[2].strip()
            expect_cn = parts[3].strip()
            note = parts[4] if len(parts) > 4 else ''
            cases.append((kind, text, expect_bpm, expect_cn, note))
    return cases


def run(verbose=False):
    path = os.path.join(HERE, 'cases.tsv')
    cases = load_cases(path)
    passed = failed = 0
    failures = []

    for kind, text, expect_bpm, expect_cn, note in cases:
        res = d.analyze_text(text)
        cand_bpm = [c['bopomofo_joined'] for c in res['candidates']]
        cand_cn = [c.get('chinese') for c in res['candidates']]

        # repair 建議掃全部 segments（不只 candidates），neg 的回歸檢查才夠嚴格
        repairs = [r for s in res['segments'] for r in s.get('repair', [])]
        repair_cn = [r['chinese'] for r in repairs]

        if kind == 'pos':
            ok = res['has_candidates']
            if ok and expect_bpm != '-':
                ok = expect_bpm in cand_bpm
            if ok and expect_cn != '-':
                ok = expect_cn in cand_cn
            detail = 'has_candidates=%s bpm=%s cn=%s' % (
                res['has_candidates'], cand_bpm, cand_cn)
        elif kind == 'rep':
            # 應該要有 repair 建議，且 expect_chinese 是某個建議的子字串
            ok = bool(repairs)
            if ok and expect_bpm != '-':
                ok = expect_bpm in cand_bpm
            if ok and expect_cn != '-':
                ok = any(expect_cn in cn for cn in repair_cn)
            detail = 'repair=%s' % repair_cn
        elif kind == 'neg':
            # 不可有候選，也不可因為多了轉置嘗試而生出 repair 建議
            ok = (not res['has_candidates']) and not repairs
            detail = 'candidates=%s repair=%s' % (cand_bpm, repair_cn)
        else:
            ok = False
            detail = 'unknown kind %r' % kind

        if ok:
            passed += 1
            if verbose:
                shown = repair_cn if kind == 'rep' else (cand_cn or cand_bpm)
                print('PASS [%s] %-38s -> %s' % (kind, text, shown))
        else:
            failed += 1
            failures.append((kind, text, '%s / %s' % (expect_bpm, expect_cn), detail, note))

    print('\n%d passed, %d failed, %d total' % (passed, failed, passed + failed))
    if failures:
        print('\n--- 失敗 ---')
        for kind, text, expect, detail, note in failures:
            print('[%s] input=%r expect=%r' % (kind, text, expect))
            print('      %s  (%s)' % (detail, note))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()
    sys.exit(run(verbose=args.verbose))
