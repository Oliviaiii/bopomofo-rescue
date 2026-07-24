<#
.SYNOPSIS
  把 bopomofo-input-recovery 這個 skill 安裝 / 同步到一個 Claude Code 專案。

.DESCRIPTION
  本 repo 是這個 skill 的「正式源頭」。此腳本會把技能檔鏡像複製到
  <Target>\.claude\skills\bopomofo-input-recovery(單向:源頭 -> 專案)。
  每次更新本 repo 後,重跑一次就能把目標專案同步到最新。
  注意:這是「鏡像」,會先清掉目標的舊技能資料夾再整包覆蓋,
  目標端對這個技能的本地改動會被蓋掉(源頭才是唯一真相)。

.PARAMETER Target
  Claude Code 專案的根目錄(內含 .claude 的那層)。

.EXAMPLE
  .\install.ps1 -Target C:\path\to\your-project
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Target,

    # 略過 UserPromptSubmit hook 的註冊(只同步 skill 檔案)
    [switch]$SkipHook,

    # hook 要寫進哪個 settings.json。預設使用者層級:注音打錯不分專案,
    # 裝在單一 repo 換個專案就失效。指定其他路徑主要供測試用。
    [string]$SettingsPath = (Join-Path $env:USERPROFILE '.claude\settings.json')
)
$ErrorActionPreference = 'Stop'
# 讓中文訊息在各種 Windows console 都能正常顯示(失敗就算了,不影響同步)
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

if (-not (Test-Path $Target)) {
    throw "找不到目標專案資料夾:$Target"
}

$src  = $PSScriptRoot
$dest = Join-Path $Target '.claude\skills\bopomofo-input-recovery'

# 先清掉舊的技能資料夾再整包覆蓋 -> 乾淨鏡像、可重複執行不殘留
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
New-Item -ItemType Directory -Force -Path $dest | Out-Null

# 要同步的技能內容(排除本腳本自身、.git、快取)
# 含 check.ps1:讓使用端不必回到源頭 repo 也能自我健檢。
# (它在副本裡會自動把「第 4 項路徑比對」標成 SKIP,不會誤報 repo 搬家)
# 不含 hooks\:hook 註冊在使用者層級、對所有專案生效,若指向專案內副本,
# 那個專案一刪 hook 就壞了。
$items = @('SKILL.md', 'README.md', '.gitignore', 'check.ps1', 'scripts', 'data', 'references', 'tests')
foreach ($item in $items) {
    $path = Join-Path $src $item
    if (Test-Path $path) {
        Copy-Item -Recurse -Force -Path $path -Destination $dest
    }
}

# 清掉可能被一併複製過去的 Python 快取
Remove-Item -Recurse -Force (Join-Path $dest 'scripts\__pycache__') -ErrorAction SilentlyContinue

Write-Host "OK  bopomofo-input-recovery 已同步 -> $dest"
Write-Host "    (若目標是 git 專案,記得去該專案 review 並 commit 這次變更)"

# ---------------------------------------------------------------------------
# 註冊 UserPromptSubmit hook
#
# 為什麼指向「源頭 repo」而不是剛剛鏡像過去的副本:hook 註冊在使用者層級、
# 對所有專案生效,若指向某個專案內的副本,那個專案被刪掉 hook 就壞了。
# 也因此 hooks\ 刻意不列入上面的鏡像清單,避免有人誤註冊專案內的副本。
# ---------------------------------------------------------------------------
function ConvertTo-HashtableDeep {
    param($InputObject)
    if ($null -eq $InputObject) { return $null }
    if ($InputObject -is [string]) { return $InputObject }          # 字串也是 IEnumerable,要先擋
    if ($InputObject -is [System.Collections.IDictionary]) {
        $h = [ordered]@{}
        foreach ($k in @($InputObject.Keys)) { $h[$k] = ConvertTo-HashtableDeep $InputObject[$k] }
        return $h
    }
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $h = [ordered]@{}
        foreach ($p in $InputObject.PSObject.Properties) { $h[$p.Name] = ConvertTo-HashtableDeep $p.Value }
        return $h
    }
    if ($InputObject -is [System.Collections.IEnumerable]) {
        # 前面加逗號:PowerShell 的 return 會把「只有一個元素的陣列」拆成純量,
        # 那會讓 hooks:[{...}] 在讀改寫一輪之後變成 hooks:{...}(物件),設定就壞了。
        return ,@(foreach ($i in $InputObject) { ConvertTo-HashtableDeep $i })
    }
    return $InputObject
}

if ($SkipHook) {
    Write-Host "--  已略過 hook 註冊(-SkipHook)"
} else {
    $hookScript = Join-Path $src 'hooks\bopomofo_hook.py'
    if (-not (Test-Path $hookScript)) { throw "找不到 hook 腳本:$hookScript" }

    # hook 由 Claude Code 另開行程執行,PATH 不保證與此處相同 -> 解析成絕對路徑。
    $pythonExe = 'python'
    try {
        $pyCmd = Get-Command python -ErrorAction Stop
        if ($pyCmd.Source) { $pythonExe = $pyCmd.Source }
    } catch { }
    # 用官方的 exec form(帶 args):command 直接當成執行檔啟動、不經 shell,
    # 每個 args 元素原樣當成一個參數 -> 路徑含空白完全不需要引號,也沒有
    # shell 的引號剝除問題。python.exe 是真正的 .exe,符合 Windows exec form 的限制。
    $hookArgs = @(, $hookScript)

    $settingsDir = Split-Path -Parent $SettingsPath
    if ($settingsDir -and -not (Test-Path $settingsDir)) {
        New-Item -ItemType Directory -Force -Path $settingsDir | Out-Null
    }

    # 讀取既有設定並轉成可安全改寫的 hashtable(合併,不是整檔覆蓋)
    $settings = [ordered]@{}
    if (Test-Path $SettingsPath) {
        $raw = Get-Content -Raw -Path $SettingsPath -Encoding UTF8
        if ($raw -and $raw.Trim()) {
            try {
                $settings = ConvertTo-HashtableDeep (ConvertFrom-Json $raw)
            } catch {
                throw "現有 settings.json 不是合法 JSON,為免破壞內容已中止:$SettingsPath"
            }
        }
        Copy-Item -Path $SettingsPath -Destination "$SettingsPath.bak" -Force
    }

    if (-not $settings.Contains('hooks'))                { $settings['hooks'] = [ordered]@{} }
    if (-not $settings['hooks'].Contains('UserPromptSubmit')) { $settings['hooks']['UserPromptSubmit'] = @() }

    # 認出「我們裝的那筆」-> 重跑只更新、不重複。舊版是 shell form(腳本路徑在
    # command 裡),新版是 exec form(在 args 裡),兩種都要能認出來才不會裝兩份。
    $entries = @($settings['hooks']['UserPromptSubmit'])
    $found = $false
    foreach ($entry in $entries) {
        if ($entry -is [System.Collections.IDictionary] -and $entry.Contains('hooks')) {
            foreach ($h in @($entry['hooks'])) {
                if ($h -isnot [System.Collections.IDictionary]) { continue }
                $probe = @()
                if ($h.Contains('command')) { $probe += "$($h['command'])" }
                if ($h.Contains('args'))    { $probe += @($h['args'] | ForEach-Object { "$_" }) }
                if ($probe -join ' ' -like '*bopomofo_hook.py*') {
                    $h['command'] = $pythonExe      # 路徑可能變了 -> 就地更新
                    $h['args']    = $hookArgs
                    $found = $true
                }
            }
        }
    }
    if (-not $found) {
        $newEntry = [ordered]@{
            matcher = '*'
            hooks   = @(, [ordered]@{
                type    = 'command'
                command = $pythonExe
                args    = $hookArgs
                timeout = 10
            })
        }
        $entries = @($entries) + @($newEntry)
    }
    $settings['hooks']['UserPromptSubmit'] = @($entries)

    $json = $settings | ConvertTo-Json -Depth 20
    Set-Content -Path $SettingsPath -Value $json -Encoding UTF8

    if ($found) { Write-Host "OK  UserPromptSubmit hook 已更新 -> $SettingsPath" }
    else        { Write-Host "OK  UserPromptSubmit hook 已註冊 -> $SettingsPath" }
    Write-Host "    command: $pythonExe"
    Write-Host "    args   : $hookScript"
    Write-Host "    (設定為熱重載,不需重開 Claude Code)"

    # 註冊完立刻健檢一次,讓安裝當下就知道到底有沒有真的活起來。
    # 註:check.ps1 失敗會以非 0 離開,但這裡不讓它中斷安裝 —— skill 資料夾
    # 已經同步完成了,健檢結果只是附加資訊。
    $checkScript = Join-Path $src 'check.ps1'
    if (Test-Path $checkScript) {
        Write-Host ""
        & $checkScript -SettingsPath $SettingsPath
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "!!  健檢未全數通過(見上方 FAIL 項目)" -ForegroundColor Yellow
        }
    }
}
