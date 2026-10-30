# 部署脚本：仓库 -> 部署目录（唯一同步入口，请在 commit 之后运行）
# 用法：
#   powershell -File scripts\deploy.ps1        # 预览（dry-run）
#   powershell -File scripts\deploy.ps1 -Go    # 实际部署，结束后恢复部署目录只读
param([switch]$Go)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$dest = Join-Path $env:USERPROFILE '.agents\skills\bo-equity-researcher'
$legacy = Join-Path $env:USERPROFILE '.agents\skills\stock-deep-analysis'
$legacyBackup = Join-Path $env:USERPROFILE '.agents\retired-skills\stock-deep-analysis-pre-bo-equity-researcher'
# /XD 目录排除：golden=快照测试基线（仅 test_golden.py 消费，运行时零依赖）
$xd = @('.git', '__pycache__', '.pytest_cache', 'artifacts', 'handoffs', 'tasks', 'golden')
# /XF 文件排除：测试与维护侧文件（test_*/conftest=pytest 侧；CHANGELOG/README/AGENTS/deploy=仓库维护侧）
$xf = @('test_*.py', 'conftest.py', 'CHANGELOG.md', 'README.md', 'AGENTS.md', 'deploy.ps1')

# 文档超长行闸（v4.10.1）：单行 >1500 字符会触发 v4.9.2 立案的 Read 截断陷阱，warn-only
function Test-DocLines {
    $bad = 0
    Get-ChildItem (Join-Path $repo 'references\*.md'), (Join-Path $repo 'SKILL.md'), (Join-Path $repo 'CHANGELOG.md') | ForEach-Object {
        $f = $_.FullName; $n = 0
        Get-Content $f -Encoding UTF8 | ForEach-Object { $n++; if ($_.Length -gt 1500) { Write-Host "  超长行 $($_.Length) 字符: $f 行 $n"; $bad++ } }
    }
    if ($bad -gt 0) { Write-Host "提示：文档超长行 $bad 处（>1500 字符，v4.9.2 截断陷阱立案阈值），建议拆行后再部署。" }
}

# /MIR 删除可见性（审计#19）：/MIR 会删除部署目录里仓库侧不存在的文件（robocopy 的 *EXTRA 行），
# 此前 robocopy 输出被丢弃，用户手工放的文件被静默删除。输出存变量筛出 *EXTRA 行，预览与
# 实跑都打印。注意：中文系统 robocopy 输出本地化为「*多余文件/目录」，故同时匹配英文标记。
function Show-ExtraLines {
    param($out)
    $hit = @($out | Select-String -Pattern '\*EXTRA', '\*多')
    if ($hit.Count -gt 0) {
        Write-Host '注意：以下部署目录内容仅存在于目标侧，/MIR 将删除：'
        $hit | ForEach-Object { Write-Host "  $($_.Line.Trim())" }
    }
}

function Move-LegacyDeployment {
    param(
        [string]$LegacyDir,
        [string]$BackupDir
    )
    if (-not (Test-Path -LiteralPath $LegacyDir -PathType Container)) {
        Write-Host '未发现旧部署目录，无需退休。'
        return
    }
    if (Test-Path -LiteralPath $BackupDir) {
        throw "备份目录已存在，拒绝覆盖：$BackupDir"
    }
    $backupParent = Split-Path -Parent $BackupDir
    if (-not (Test-Path -LiteralPath $backupParent -PathType Container)) {
        New-Item -ItemType Directory -Path $backupParent -Force | Out-Null
    }
    Move-Item -LiteralPath $LegacyDir -Destination $BackupDir -ErrorAction Stop
    Write-Host "旧部署目录已迁入备份：$BackupDir"
}

function Invoke-MirroredDeployment {
    param(
        [string]$Repo,
        [string]$Dest
    )
    $backup = "$Dest.deploy-backup"
    if (Test-Path -LiteralPath $backup) {
        throw "部署备份已存在，拒绝覆盖且未改动原目录：$backup"
    }
    if ((Test-Path -LiteralPath $Dest) -and -not (Test-Path -LiteralPath $Dest -PathType Container)) {
        throw "部署目标已存在但不是目录，拒绝处理且未改动该路径：$Dest"
    }
    $hasDest = Test-Path -LiteralPath $Dest -PathType Container
    $backupCreated = $false
    $deployed = $false
    try {
        if ($hasDest) {
            $out = robocopy $Repo $Dest /MIR /L /XD $xd /XF $xf /NJH
            $rc = $LASTEXITCODE
            Show-ExtraLines $out
            if ($rc -ge 8) { throw "robocopy 预检失败 (code $rc)，未改动原部署" }
            attrib -R "$Dest\*" /S /D | Out-Null
            Move-Item -LiteralPath $Dest -Destination $backup -ErrorAction Stop
            $backupCreated = $true
        }
        $out = robocopy $Repo $Dest /MIR /XD $xd /XF $xf
        $rc = $LASTEXITCODE
        Show-ExtraLines $out
        if ($rc -ge 8) { throw "robocopy 部署失败 (code $rc)，将恢复原部署" }
        $deployed = $true
    }
    finally {
        if (-not $deployed) {
            if (($backupCreated -or -not $hasDest) -and (Test-Path -LiteralPath $Dest)) {
                attrib -R "$Dest\*" /S /D | Out-Null
                Remove-Item -LiteralPath $Dest -Recurse -Force -ErrorAction Stop
            }
            if ($backupCreated) {
                Move-Item -LiteralPath $backup -Destination $Dest -ErrorAction Stop
            }
        }
        if (Test-Path -LiteralPath $Dest) {
            attrib +R "$Dest\*" /S /D | Out-Null
        }
        if ($deployed -and $backupCreated) {
            attrib -R "$backup\*" /S /D | Out-Null
            Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction Stop
        }
    }
}
Test-DocLines

if (-not $Go) {
    if (Test-Path -LiteralPath $legacy -PathType Container) {
        Write-Host "旧部署目录将在新目录部署成功后迁移到：$legacyBackup"
        if (Test-Path -LiteralPath $legacyBackup) {
            Write-Host '注意：备份目录已存在，正式部署将拒绝覆盖且不会退休旧目录。'
        }
    }
    $out = robocopy $repo $dest /MIR /L /XD $xd /XF $xf /NJH
    $rc = $LASTEXITCODE
    Show-ExtraLines $out
    if ($rc -ge 8) { Write-Host "robocopy 预览失败 (code $rc)"; exit 1 }
    if ($rc -eq 0) { Write-Host '预览完成：部署目录已是最新，无需变更。' }
    else { Write-Host "预览完成：有变更待部署 (code $rc)。确认无误后运行: powershell -File scripts\deploy.ps1 -Go" }
    exit 0
}

Invoke-MirroredDeployment -Repo $repo -Dest $dest
try {
    Move-LegacyDeployment -LegacyDir $legacy -BackupDir $legacyBackup
}
catch {
    Write-Host "新目录已部署、旧目录尚未退休：$($_.Exception.Message)"
    exit 1
}
Write-Host '部署完成，新部署目录已恢复只读。'
exit 0
