#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bopomofo_hook.py — Claude Code UserPromptSubmit hook：訊息送出當下自動解碼注音誤打。

掛上之後，使用者打出 su3cl3a8 時，AI 第一眼就看得到還原結果，不必再花兩次工具
往返（載入 skill + 執行腳本）去問。

行為（刻意保守，因為它會跑在**每一則**訊息上）：
  - 只有偵測到 tier == 'high' 的候選才輸出提示；medium / low 一律靜默。
  - 沒有候選就什麼都不印，不污染 context。
  - 任何例外都吞掉並以離開碼 0 結束。

⚠️ 離開碼務必永遠是 0：依 Claude Code hooks 規格，UserPromptSubmit 的離開碼 2
會**擋下並清除使用者的訊息**，其他非 0 會在 transcript 顯示錯誤。hook 出問題
絕不能影響使用者送訊息，所以這裡把所有失敗都當成「安靜地不做事」。

效能：沒有候選時完全不會載入 4.7MB 詞典（decode_chinese 才會 lazy load），
所以一般英文/中文訊息幾乎零成本。
"""

import sys
import os


def _emit(line):
    """把提示寫到 stdout；UserPromptSubmit 的 stdout 會成為 Claude 的 context。"""
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    sys.stdout.write(line + '\n')


def main():
    try:
        import json
        # stdin 也要鎖 UTF-8:Windows 下預設會用 CP950 解碼,使用者的中文 prompt
        # 會變成亂碼甚至讓 json 解析失敗。
        try:
            sys.stdin.reconfigure(encoding='utf-8')
        except Exception:
            pass
        raw = sys.stdin.read()
        # 有些呼叫端(如 PowerShell 管線)會在 stdin 最前面塞一個 BOM，
        # 直接丟給 json.loads 會 JSONDecodeError；因為本檔吞掉所有例外，
        # 那會變成「安靜地什麼都不做」這種很難查的失敗。
        raw = raw.lstrip('﻿')
        if not raw.strip():
            return 0
        data = json.loads(raw)
        # 依 Claude Code hooks 規格，使用者輸入在 "prompt" 欄位
        prompt = data.get('prompt')
        if not prompt or not isinstance(prompt, str):
            return 0

        # 從本檔位置找到同 repo 的 scripts/decode_bopomofo.py（直接 import，
        # 省下再開一個 Python 行程的啟動時間 —— 這會跑在每則訊息上）
        here = os.path.dirname(os.path.abspath(__file__))
        scripts_dir = os.path.join(os.path.dirname(here), 'scripts')
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import decode_bopomofo as d

        result = d.analyze_text(prompt)
        if not result.get('has_candidates'):
            return 0

        lines = []
        for c in result.get('candidates', []):
            if c.get('tier') != 'high':
                continue                        # medium/low 靜默，避免誤判污染
            token = c.get('token', '')
            if c.get('chinese'):
                lines.append('[注音還原] %s -> %s' % (token, c['chinese']))
            else:
                # 沒有中文但有轉置建議：也值得提示，否則呼叫端只看到一串注音
                for rep in (c.get('repair') or [])[:1]:
                    lines.append('[注音還原] %s -> %s（推測相鄰兩鍵打反，需依上下文確認）'
                                 % (token, rep.get('chinese', '')))

        if lines:
            _emit('\n'.join(lines))
        return 0
    except Exception:
        # 靜默失敗：hook 壞掉不能影響使用者送訊息
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
