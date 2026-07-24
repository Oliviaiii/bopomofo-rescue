<#
.SYNOPSIS
  檢查 bopomofo-rescue 的 UserPromptSubmit hook 是不是還活著。

.DESCRIPTION
  hooks\bopomofo_hook.py 刻意設計成「永遠 exit 0、失敗完全靜默」——
  因為依 Claude Code hooks 規格,UserPromptSubmit 回 2 會擋下並清除使用者的訊息。
  這個設計是對的,但代價是失效無聲無息:使用者只會覺得「AI 不知道從哪天開始
  又要跑工具才看得懂注音了」,可能幾個月後才發現。

  這支腳本就是拿來補這個洞的。

  ⚠ 離開碼策略跟 hook 相反:hook 永遠 exit 0;check 有問題就必須非 0 離開,
  否則它自己也變成靜默失敗,那就完全失去存在意義。

.PARAMETER SettingsPath
  要檢查的 settings.json。預設使用者層級。指向暫時檔可用來製造故障做測試,
  不必動到真正的設定。

.EXAMPLE
  .\check.ps1
  .\check.ps1 -SettingsPath C:\tmp\broken.json
#>
param(
    [string]$SettingsPath = (Join-Path $env:USERPROFILE '.claude\settings.json')
)

# 注意:不要用 $ErrorActionPreference='Stop'。這支腳本的工作是「把壞掉的地方
# 一項一項報出來」,中途拋例外反而會讓後面的檢查跑不完。
$script:Failures = @()

function Report {
    param([bool]$Ok, [string]$Name, [string]$Detail)
    if ($Ok) {
        Write-Host "PASS  $Name" -ForegroundColor Green
    } else {
        Write-Host "FAIL  $Name" -ForegroundColor Red
        $script:Failures += $Name
    }
    if ($Detail) { Write-Host "      $Detail" }
}

function ReportSkip {
    param([string]$Name, [string]$Detail)
    Write-Host "SKIP  $Name" -ForegroundColor DarkGray
    if ($Detail) { Write-Host "      $Detail" }
}

# 用 .NET 直接 spawn,忠實重現 Claude Code 的 exec form(不經 shell)。
# stdin 寫「不含 BOM 的 UTF-8 位元組」——PowerShell 管線會自動加 BOM,
# 那會讓 json.loads 失敗、又被 hook 的 catch-all 吞掉,測出假的失敗。
function Invoke-Hook {
    param([string]$Py, [string]$Script, [string]$Json)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $Py
    $psi.Arguments              = '"{0}"' -f $Script
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardInput  = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8
    $p = [System.Diagnostics.Process]::Start($psi)
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($Json)
    $p.StandardInput.BaseStream.Write($bytes, 0, $bytes.Length)
    $p.StandardInput.BaseStream.Flush()
    $p.StandardInput.Close()
    $out = $p.StandardOutput.ReadToEnd()
    $err = $p.StandardError.ReadToEnd()
    $p.WaitForExit()
    return [pscustomobject]@{ Out = $out; Err = $err; Exit = $p.ExitCode }
}

Write-Host ""
Write-Host "bopomofo-rescue hook 健檢" -ForegroundColor Cyan
Write-Host "設定檔: $SettingsPath"
Write-Host ("-" * 60)

# ---------------------------------------------------------------------------
# 1. 設定檔存在,且找得到本 hook 的註冊
# ---------------------------------------------------------------------------
$reg = $null
$regPython = $null
$regScript = $null

if (-not (Test-Path $SettingsPath)) {
    Report $false '1. hook 已註冊' "設定檔不存在:$SettingsPath"
} else {
    $settings = $null
    try {
        $raw = Get-Content -Raw -Path $SettingsPath -Encoding UTF8
        if ($raw -and $raw.Trim()) { $settings = ConvertFrom-Json $raw }
    } catch {
        Report $false '1. hook 已註冊' "settings.json 不是合法 JSON:$($_.Exception.Message)"
    }

    if ($settings) {
        if (-not $settings.hooks -or -not $settings.hooks.UserPromptSubmit) {
            Report $false '1. hook 已註冊' 'settings.json 裡沒有 hooks.UserPromptSubmit 這段'
        } else {
            foreach ($entry in @($settings.hooks.UserPromptSubmit)) {
                foreach ($h in @($entry.hooks)) {
                    $probe = @()
                    if ($h.command) { $probe += [string]$h.command }
                    if ($h.args)    { $probe += @($h.args | ForEach-Object { [string]$_ }) }
                    if ((($probe -join ' ')) -like '*bopomofo_hook.py*') { $reg = $h; break }
                }
                if ($reg) { break }
            }
            if (-not $reg) {
                Report $false '1. hook 已註冊' 'UserPromptSubmit 存在,但裡面沒有 bopomofo_hook.py 的註冊'
            } else {
                # exec form:腳本在 args;shell form:整串塞在 command 裡
                $regPython = [string]$reg.command
                if ($reg.args) {
                    foreach ($a in @($reg.args)) {
                        if ("$a" -like '*bopomofo_hook.py*') { $regScript = "$a" }
                    }
                }
                if (-not $regScript) {
                    if ($regPython -match '"?([^"]*bopomofo_hook\.py)"?') { $regScript = $Matches[1] }
                    if ($regPython -match '^\s*"?(.+?\.exe)"?\s')         { $regPython = $Matches[1] }
                }
                Report $true '1. hook 已註冊' "python=$regPython`n      script=$regScript"
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 2. 註冊的 python 存在且能執行
# ---------------------------------------------------------------------------
$pythonOk = $false
if (-not $regPython) {
    ReportSkip '2. python 可執行' '前一項失敗,無法取得 python 路徑'
} else {
    $pyPath = $regPython
    if (-not (Test-Path $pyPath)) {
        # 可能註冊的是 PATH 上的名稱(例如 "python")而非絕對路徑
        $resolved = $null
        try { $resolved = (Get-Command $regPython -ErrorAction Stop).Source } catch { }
        if ($resolved) { $pyPath = $resolved }
    }
    if (-not (Test-Path $pyPath)) {
        Report $false '2. python 可執行' "註冊的 python 路徑不存在:$regPython(Python 升級或換裝路徑時會這樣)"
    } else {
        $ver = $null
        try { $ver = (& $pyPath --version 2>&1 | Out-String).Trim() } catch { }
        if ($LASTEXITCODE -ne 0 -or -not $ver) {
            Report $false '2. python 可執行' "找得到檔案但執行失敗:$pyPath"
        } else {
            $pythonOk = $true
            $regPython = $pyPath
            Report $true '2. python 可執行' "$ver  ($pyPath)"
        }
    }
}

# ---------------------------------------------------------------------------
# 3. 註冊的 hook 腳本存在
# ---------------------------------------------------------------------------
$scriptOk = $false
if (-not $regScript) {
    ReportSkip '3. hook 腳本存在' '前面失敗,無法取得腳本路徑'
} elseif (-not (Test-Path $regScript)) {
    Report $false '3. hook 腳本存在' "註冊的 hook 腳本不存在:$regScript(repo 搬走或刪掉時會這樣)"
} else {
    $scriptOk = $true
    Report $true '3. hook 腳本存在' $regScript
}

# ---------------------------------------------------------------------------
# 4. 註冊路徑 == check.ps1 自己所在的這個 repo
# ---------------------------------------------------------------------------
$expected = Join-Path $PSScriptRoot 'hooks\bopomofo_hook.py'
if (-not $regScript) {
    ReportSkip '4. 註冊路徑與本 repo 一致' '前面失敗,無從比對'
} elseif (-not (Test-Path $expected)) {
    # 這支 check.ps1 旁邊沒有 hooks\,代表它不是待在源頭 repo,而是在安裝副本裡
    # (install.ps1 刻意不鏡像 hooks\)。此時拿 $PSScriptRoot 去比對必然不相等,
    # 會對一個健康的 hook 誤報「repo 搬過家」—— 假警報比不檢查更糟,所以誠實跳過。
    ReportSkip '4. 註冊路徑與本 repo 一致' `
        "此處是安裝副本(旁邊沒有 hooks\),無從比對;要驗這項請從源頭 repo 執行 check.ps1"
} else {
    $a = $null; $b = $null
    try { $a = (Resolve-Path $regScript -ErrorAction Stop).Path } catch { $a = $regScript }
    try { $b = (Resolve-Path $expected  -ErrorAction Stop).Path } catch { $b = $expected }
    if ($a -ieq $b) {
        Report $true '4. 註冊路徑與本 repo 一致' $a
    } else {
        Report $false '4. 註冊路徑與本 repo 一致' `
            "設定檔指向:$a`n      但本 repo 在:$b`n      => repo 搬過家,設定還指著舊位置,請重跑 install.ps1"
    }
}

# ---------------------------------------------------------------------------
# 5. 端到端實測(最重要:前四項全過仍可能因詞典遺失/import 失敗而壞掉)
# ---------------------------------------------------------------------------
if (-not ($pythonOk -and $scriptOk)) {
    ReportSkip '5. 端到端實測' '前置條件未過,無法實際執行 hook'
} else {
    $vectors = @(
        @{ Name = 'su3cl3a8 -> 你好嗎'
           Json = '{"prompt":"su3cl3a8"}'
           Expect = @('[注音還原] su3cl3a8 -> 你好嗎') }
        @{ Name = '鄰鍵轉置 gp6ak78a -> 什麼嗎'
           Json = '{"prompt":"su3d042k72j/3ji3y94gji gp6ak78a ?"}'
           Expect = @('gp6ak78a', '什麼嗎', '推測相鄰兩鍵打反') }
        @{ Name = '技術字串須靜默'
           Json = '{"prompt":"run npm install then git commit -m fix in ./src/app.py"}'
           Expect = $null }
        @{ Name = '一般中文須靜默'
           Json = '{"prompt":"幫我看一下這個 function 有沒有問題"}'
           Expect = $null }
    )

    foreach ($v in $vectors) {
        $r = Invoke-Hook -Py $regPython -Script $regScript -Json $v.Json
        $out = ($r.Out -replace "`r", '').Trim()

        if ($r.Exit -ne 0) {
            Report $false "5. $($v.Name)" "hook 離開碼應為 0,實際為 $($r.Exit)。stderr: $($r.Err.Trim())"
            continue
        }
        if ($null -eq $v.Expect) {
            if ($out -eq '') {
                Report $true "5. $($v.Name)" '(靜默,符合預期)'
            } else {
                Report $false "5. $($v.Name)" "應完全靜默,卻輸出:$out"
            }
        } else {
            # 用 .Contains 而非 -like:-like 會把 [注音還原] 的中括號當成
            # 字元集萬用字元,導致明明一模一樣卻比對失敗。
            $missing = @($v.Expect | Where-Object { -not $out.Contains($_) })
            if ($missing.Count -eq 0) {
                # 證據行要印「真正對應本項的那一行」,而不是永遠印第一行:轉置案例的
                # 輸出有兩行(前半句 + gp6ak78a 那句),盲取第一行會標題說 A、證據貼 B。
                # 挑命中最多 Expect 字串的那行,顯示才會跟標題對得上。
                $lines = @($out -split "`n" | Where-Object { $_.Trim() -ne '' })
                $evidence = $lines[0]
                $bestHits = -1
                foreach ($ln in $lines) {
                    $hits = @($v.Expect | Where-Object { $ln.Contains($_) }).Count
                    if ($hits -gt $bestHits) { $bestHits = $hits; $evidence = $ln }
                }
                Report $true "5. $($v.Name)" $evidence.Trim()
            } else {
                Report $false "5. $($v.Name)" "輸出缺少:$($missing -join ' / ')`n      實際輸出:$out"
            }
        }
    }
}

# ---------------------------------------------------------------------------
# 6. 結論 + 修復指引
# ---------------------------------------------------------------------------
Write-Host ("-" * 60)
if ($script:Failures.Count -eq 0) {
    Write-Host "OK  全部通過 —— hook 正常運作中,送訊息時會自動解碼注音誤打。" -ForegroundColor Green
    exit 0
}

Write-Host ("有 {0} 項失敗:{1}" -f $script:Failures.Count, ($script:Failures -join '、')) -ForegroundColor Red
Write-Host ""
Write-Host "怎麼修:" -ForegroundColor Yellow
Write-Host "  多數情況重新註冊就好(會用目前的 python 與 repo 位置改寫設定):"
Write-Host "      .\install.ps1 -Target <你的專案路徑>"
Write-Host "  例如:"
Write-Host "      .\install.ps1 -Target C:\path\to\your-project"
Write-Host ""
Write-Host "  若第 5 項失敗但 1~4 都過,代表註冊沒問題、是 hook 本身跑不動,"
Write-Host "  多半是詞典檔遺失。先確認 data\bopomofo_dict.tsv 在不在,再跑:"
Write-Host "      python tests\run_tests.py"

# ⚠ 與 hook 相反:這裡必須非 0 離開,否則這支工具自己也變成靜默失敗。
exit 1
