from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AppEntry:
    name: str
    target: str
    source: str
    category: str
    arguments: str = ""
    working_dir: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class ShortcutInfo:
    target: str
    arguments: str = ""
    working_dir: str = ""


def _start_menu_roots() -> list[tuple[str, str]]:
    roots: list[tuple[str, str]] = []
    appdata = os.environ.get("APPDATA")
    programdata = os.environ.get("PROGRAMDATA")
    if appdata:
        roots.append(
            (os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs"), "开始菜单")
        )
    if programdata:
        roots.append(
            (os.path.join(programdata, "Microsoft", "Windows", "Start Menu", "Programs"), "开始菜单")
        )

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        desktop = os.path.join(userprofile, "Desktop")
        if os.path.isdir(desktop):
            roots.append((desktop, "桌面"))
    return roots


def _walk_shortcuts(root: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            lower = filename.lower()
            if lower.endswith(".lnk") or lower.endswith(".url"):
                found.append((os.path.join(dirpath, filename), filename))
    return found


def _resolve_shortcuts(paths: list[str]) -> dict[str, ShortcutInfo]:
    if not paths:
        return {}

    script = r'''
$ErrorActionPreference = 'SilentlyContinue'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$inputJson = [Console]::In.ReadToEnd()
$paths = $inputJson | ConvertFrom-Json
$shell = New-Object -ComObject WScript.Shell
$items = @()
foreach ($p in $paths) {
    if ($p -and (Test-Path -LiteralPath $p)) {
        $shortcut = $shell.CreateShortcut($p)
        $target = $shortcut.TargetPath
        $usedFallback = $false
        if (-not $target) {
            $icon = $shortcut.IconLocation
            if ($icon) {
                $iconPath = $icon -replace ',[0-9]+$', ''
                $iconPath = $iconPath.Trim('"')
                $iconPath = [Environment]::ExpandEnvironmentVariables($iconPath)
                if ($iconPath -match '\.exe$' -and $iconPath -notmatch 'Windows\\Installer' -and $iconPath -notmatch 'icon\.exe$' -and (Test-Path -LiteralPath $iconPath)) {
                    $target = $iconPath
                    $usedFallback = $true
                }
            }
        }
        if ($target) {
            $arguments = ''
            $workingDirectory = ''
            if (-not $usedFallback) {
                $arguments = [string]$shortcut.Arguments
                $workingDirectory = [string]$shortcut.WorkingDirectory
            }
            $items += [PSCustomObject]@{
                Path = $p
                Target = $target
                Arguments = $arguments
                WorkingDirectory = $workingDirectory
            }
        }
    }
}
$items | ConvertTo-Json -Compress
'''

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            input=json.dumps(paths),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}

    if proc.returncode != 0:
        return {}

    raw = proc.stdout.strip()
    if not raw or raw in {"null", "{}"}:
        return {}

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    result: dict[str, ShortcutInfo] = {}
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            path = item.get("Path")
            target = item.get("Target")
            if path and target:
                result[str(path)] = ShortcutInfo(
                    target=str(target),
                    arguments=str(item.get("Arguments") or ""),
                    working_dir=str(item.get("WorkingDirectory") or ""),
                )
    return result


def _is_launchable_target(target: str) -> bool:
    lower = target.lower()
    if lower.startswith(("http://", "https://", "steam://")):
        return True

    basename = os.path.basename(target).lower()
    if basename.startswith(("setup", "install")) or basename in {"uninstall.exe", "unins000.exe"}:
        return False
    if "\\windows\\installer\\" in lower or "_icon.exe" in basename or basename == "icon.exe":
        return False

    filename = basename
    if any(token in filename for token in ("uninstall", "unins", "卸载")):
        return False

    if os.path.isdir(target):
        return False

    ext = os.path.splitext(lower)[1]
    if ext in {".pdf", ".htm", ".html", ".chm", ".txt", ".doc", ".docx", ".rtf", ".xls", ".xlsx"}:
        return False

    if ext in {".exe", ".bat", ".cmd", ".com", ".msc", ".cpl", ".lnk", ".url", ".appref-ms"}:
        return True

    return os.path.isfile(target)


def _is_noise_entry(name: str, target: str) -> bool:
    lower_name = name.lower()
    lower_target = target.lower()
    text = f"{lower_name} {lower_target}"
    noise_tokens = (
        "readme",
        "read me",
        "getting started",
        "installation guide",
        "user guide",
        "documentation",
        "migration",
        "uninstall",
        "卸载",
        "帮助",
        "自述",
        "安装指南",
        "许可证",
        "license",
    )
    if any(token in text for token in noise_tokens):
        return True

    target_dir = os.path.dirname(lower_target)
    noise_dirs = ("\\help\\", "\\documentation\\", "\\readme\\")
    return any(token in target_dir for token in noise_dirs)


def scan_apps() -> list[AppEntry]:
    roots = _start_menu_roots()
    shortcut_rows: list[tuple[str, str, str]] = []
    for root, category in roots:
        if not os.path.isdir(root):
            continue
        for path, _filename in _walk_shortcuts(root):
            shortcut_rows.append((path, category, root))

    lnk_paths = [path for path, _category, _root in shortcut_rows if path.lower().endswith(".lnk")]
    resolved = _resolve_shortcuts(lnk_paths)

    seen: set[str] = set()
    entries: list[AppEntry] = []
    for path, category, _root in shortcut_rows:
        info = resolved.get(path)
        if not info or not _is_launchable_target(info.target):
            continue
        if info.target.lower() in seen:
            continue
        seen.add(info.target.lower())
        name = os.path.splitext(os.path.basename(path))[0]
        if _is_noise_entry(name, info.target):
            continue
        entries.append(
            AppEntry(
                name=name,
                target=info.target,
                source=path,
                category=category,
                arguments=info.arguments,
                working_dir=info.working_dir,
            )
        )

    entries.sort(key=lambda item: (item.name.lower(), item.target.lower()))
    return entries
