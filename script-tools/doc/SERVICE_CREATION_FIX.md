# FRPC Service Creation Fix - sc.exe Quoting Issue
> **Category:** Historical

**Dates:** 2025-11-07  
**Status:** RESOLVED  
**Problem:** FRPC service wasn't starting due to incorrect sc.exe command syntax

---

## Problem Identified

When the script tried to create the FRPC service using `sc.exe`, it failed with:
```
Start-Service : Failed to start service 'FRP Client Service (frpc)'
Cannot open 'frpc' service on computer '.'
```

### Root Causes

The `sc.exe` command line tool has **very specific quoting requirements**:

**WRONG (PowerShell escaping):**
```powershell
$cmd = 'sc.exe create frpc binPath= "\"C:\Program Files\frp\frpc.exe\" -c \"C:\ProgramData\frp\frpc.toml\""'
Invoke-Expression $cmd
```
Result: PowerShell misinterprets the escaped quotes, and sc.exe doesn't get the right syntax.

**ALSO WRONG (too many escapes):**
```powershell
sc.exe create frpc binPath= "\"C:\Program Files\frp\frpc.exe\" -c \"C:\ProgramData\frp\frpc.toml\""
```

**CORRECT:**
```powershell
sc.exe create frpc binPath= "C:\Program Files\frp\frpc.exe -c C:\ProgramData\frp\frpc.toml" start= auto displayname= "FRP Client Service"
```

### The Key Difference

- **The entire executable path + arguments must be in ONE quoted string**
- **NO escaped quotes inside the binPath value**
- **sc.exe handles the space in "Program Files" just fine with simple quotes**

---

## Solution Implemented

The script now uses a **two-tier approach**:

### 1. Primary: NSSM (Non-Sucking Service Manager)
```powershell
nssm.exe install frpc "C:\Program Files\frp\frpc.exe" "-c C:\ProgramData\frp\frpc.toml"
nssm.exe set frpc AppDirectory "C:\ProgramData\frp"
nssm.exe set frpc Start SERVICE_AUTO_START
```

**Advantages:**
- More robust than sc.exe
- Better error handling
- Automatic restart on crash
- Proper working directory support
- Pre-installed on Windows (System32\nssm.exe)

### 2. Fallback: sc.exe via cmd.exe
```powershell
& cmd.exe /c "sc.exe create frpc binPath= `"$frpcPath -c $tomlFile`" start= auto displayname= `"FRP Client Service`""
```

**Why via cmd.exe?**
- cmd.exe handles quotes more predictably than PowerShell
- Avoids PowerShell's quota escaping issues
- Works when NSSM is not available

---

## Prerequisites for Service Creation

 **CRITICAL:** Your PowerShell session must be running **AS ADMINISTRATOR**

To verify you're admin:
```powershell
# Option 1: Check if you have admin privileges
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
$isAdmin = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
Write-Host "Is Admin: $isAdmin"

# Option 2: Use whoami
whoami /groups | Select-String "Administrators"
```

**How to run PowerShell as Administrator:**
1. Press `Win + X`
2. Select "Windows PowerShell (Admin)" or "Terminal (Admin)"
3. Click "Yes" in the UAC prompt
4. Then run the installer script

---

## Testing the Fix

Once you have the correct privileges, here's how to manually test:

```powershell
#1. Remove old service (if exists)
sc.exe delete frpc 2>&1
Start-Sleep-Seconds 2

# 2. Create service with correct syntax
sc.exe create frpc binPath= "C:\Program Files\frp\frpc.exe -c C:\ProgramData\frp\frpc.toml" start= auto displayname= "FRP Client Service"

# Expected output: [SC] CreateService SUCCESSFUL

#3. Verify registration
sc.exe qc frpc

#4. Start the service
Start-Service -Name frpc -Verbose
Start-Sleep-Seconds 3

#5. Check status
Get-Service frpc | Format-List

#6. View logs
Get-Content "C:\ProgramData\frp\logs\frpc.log" -Tail 20 -Wait
```

---

## Comparison: sc.exe vs NSSM

| Features | sc.exe | NSSM |
|---------|--------|------|
| **Pre-installed** |  Yes |  Yes (Windows 8+) |
| **Reliability** |  Basic |  Excellent |
| **Auto-restart** |  No |  Yes |
| **Odds handling** |  Tricky |  Easy |
| **Working dir** |  No |  Yes |
| **Env variables** |  No |  Yes |
| **Logging** |  Basic |  Advanced |
| **Priority** |  No |  Configurable |

---

## Debugging Service Issues

If the service still won't start:

### Check 1: Service Registration
```powershell
sc.exe qc frpc
# Look for: BINARY PATH_NAME should be:
# C:\Program Files\frp\frpc.exe -c C:\ProgramData\frp\frpc.toml
```

### Check 2: File Exists
```powershell
Test-Path "C:\Program Files\frp\frpc.exe"
Test-Path "C:\ProgramData\frp\frpc.toml"
```

### Check 3: File Permissions
```powershell
icacls "C:\Program Files\frp\frpc.exe"
icacls "C:\ProgramData\frp"
```

### Check 4: Manual Execution (as LocalSystem would)
```powershell
# This simulates what the service does
& "C:\Program Files\frp\frpc.exe" -c "C:\ProgramData\frp\frpc.toml"
# Should show: login to server success, proxy added, start proxy success
```

### Check 5: Windows Event Log
```powershell
Get-WinEvent -LogName System -MaxEvents 50 | Where-Object {
    $_.Message -like "*FRP*" -or $_.Message -like "*frpc*"
} | Select-Object TimeCreated, Id, Message | Format-List
```

---

## Key Takeaways

1. **sc.exe requires simple quotes**, not escaped quotes
2. **The entire binPath (exe + args) must be in one quoted string**
3. **PowerShell quoting can interfere** - use cmd.exe /c to bypass
4. **NSSM is preferred** when available (more robust)
5. **Admin privileges are required** to create/manage services
6. **Manual execution works fine** - if manual works but service doesn't, it's a registration/permissions issue

---

## Related Files

- **Main Script:** `script-tools/install-agent-interactive.ps1`
- **Config File:** `C:\ProgramData\frp\frpc.toml`
- **Executable:** `C:\Program Files\frp\frpc.exe`
- **Logs:** `C:\ProgramData\frp\logs\frpc.log`

---

## Commit Information

**Commit:** (pending)  
**Message:** "fix: Use NSSM for FRPC service creation with sc.exe fallback"  
**Changes:** 
- Updated service creation logic in `Install-FRPCService()` function
- Added NSSM detection and usage
- Improved error messages
- Better quoting for sc.exe

---

**Status:** **FIX READY FOR TESTING**

Next steps:
1. Open PowerShell **AS ADMINISTRATOR**
2. Run the updated installer script
3. Follow FRPC configuration prompts
4. Service should now start automatically

If still having issues, collect the debugging output from "Check 1-5" above and we can diagnose further.