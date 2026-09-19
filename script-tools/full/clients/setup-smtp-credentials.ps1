# Secure SMTP Credentials Setup
# Save encrypted username and password (readable only by this user on this machine)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================================"
Write-Host "CONFIGURATION OF SECURE SMTP CREDENTIALS"
Write-Host "================================================================"
Write-Host ""

$CREDENTIAL_FILE = "C:\CheckMK-Backups\smtp_credential.xml"

Write-Host "[INFO] Your credentials will be encrypted and saved in:" -ForegroundColor Cyan
Write-Host "       $CREDENTIAL_FILE" -ForegroundColor Gray
Write-Host ""
Write-Host "[SECURITY] The file can only be read by:" -ForegroundColor Yellow
Write-Host "- User: $env:USERNAME" -ForegroundColor Gray
Write-Host "            - Computer: $env:COMPUTERNAME" -ForegroundColor Gray
Write-Host ""

# Request credentials
$username = Read-Host "Username SMTP"
$securePassword = Read-Host "Password SMTP" -AsSecureString

# Create credential object
$credential = New-Object System.Management.Automation.PSCredential($username, $securePassword)

# Save encrypted credentials
try {
    $credential | Export-Clixml -Path $CREDENTIAL_FILE -Force
    Write-Host ""
    Write-Host "[OK] Credentials saved successfully!" -ForegroundColor Green
    Write-Host ""
    
    # Reading test
    $testCred = Import-Clixml -Path $CREDENTIAL_FILE
    Write-Host "[TEST] Username salvato: $($testCred.UserName)" -ForegroundColor Green
    Write-Host ""
    
    Write-Host "================================================================"
    Write-Host "CONFIGURATION COMPLETE"
    Write-Host "================================================================"
    Write-Host ""
    Write-Host "[INFO] Now you can perform backup by sending email:" -ForegroundColor Cyan
    Write-Host ".\backup-simple.ps1 -Unattended" -ForegroundColor White
    Write-Host ""
    
} catch {
    Write-Host ""
    Write-Host "[ERROR] Unable to save credentials: $_" -ForegroundColor Red
    exit 1
}
