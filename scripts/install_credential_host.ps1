# Install only after reviewing the staged package. Run in elevated PowerShell.
# No existing credential, token, cookie or session store is read or migrated.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-fA-F]{64}$')][string]$ExpectedManifestSha256,
    [string]$PackageDirectory = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$principal = [Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator approval is required to create the protected service.' }
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HostInstallPrivilege {
 [StructLayout(LayoutKind.Sequential,Pack=4)] struct TOKEN_PRIVILEGES { public uint count; public long luid; public uint attributes; }
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
 [DllImport("advapi32.dll",CharSet=CharSet.Unicode,SetLastError=true)] static extern bool LookupPrivilegeValue(string system,string name,out long luid);
 [DllImport("advapi32.dll",SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr token,bool disable,ref TOKEN_PRIVILEGES privileges,uint length,IntPtr previous,IntPtr needed);
 [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 public static void EnableRestore() {
  IntPtr token; if(!OpenProcessToken(GetCurrentProcess(),0x28,out token)) throw new InvalidOperationException("Token access failed");
  try { long luid; if(!LookupPrivilegeValue(null,"SeRestorePrivilege",out luid)) throw new InvalidOperationException("Privilege lookup failed");
   var privileges=new TOKEN_PRIVILEGES { count=1,luid=luid,attributes=2 };
   if(!AdjustTokenPrivileges(token,false,ref privileges,0,IntPtr.Zero,IntPtr.Zero) || Marshal.GetLastWin32Error()!=0) throw new InvalidOperationException("Restore privilege unavailable");
  } finally { CloseHandle(token); }
 }
}
'@
[HostInstallPrivilege]::EnableRestore()
$installRoot = Join-Path ([Environment]::GetFolderPath('ProgramFiles')) 'CraftBotCredentialHost'
$stateRoot = Join-Path ([Environment]::GetFolderPath('CommonApplicationData')) 'CraftBotCredentialHost'
$sourceRoot = Join-Path $PackageDirectory 'payload'
$manifestFile = Join-Path $PackageDirectory 'manifest.json'
$manifestBytes = [IO.File]::ReadAllBytes($manifestFile)
$sha = [Security.Cryptography.SHA256]::Create()
try { $manifestDigest = [BitConverter]::ToString($sha.ComputeHash($manifestBytes)).Replace('-','') } finally { $sha.Dispose() }
if ($manifestDigest -ne $ExpectedManifestSha256) { throw 'Manifest digest mismatch.' }
if ((Test-Path -LiteralPath $installRoot) -or (Test-Path -LiteralPath $stateRoot) -or (Get-Service -Name CraftBotCredentialHost -ErrorAction SilentlyContinue)) { throw 'Existing host/state found; this installer never overwrites or resets it.' }
$manifest = [Text.Encoding]::UTF8.GetString($manifestBytes) | ConvertFrom-Json
$sources = Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force
if ($sources | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }) { throw 'Reparse points are not permitted in the package.' }
function Set-ProtectedAcl([string]$LiteralPath, [bool]$RuntimeRead = $false) {
    $acl = Get-Acl -LiteralPath $LiteralPath
    $sddl = 'O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)'
    if ($RuntimeRead) { $sddl += '(A;OICI;GRGX;;;AC)' }
    $acl.SetSecurityDescriptorSddlForm($sddl)
    Set-Acl -LiteralPath $LiteralPath -AclObject $acl
}
$directorySecurity = [Security.AccessControl.DirectorySecurity]::new()
$directorySecurity.SetSecurityDescriptorSddlForm('O:SYG:SYD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)')
$fileSecurity = [Security.AccessControl.FileSecurity]::new()
$fileSecurity.SetSecurityDescriptorSddlForm('O:SYG:SYD:P(A;;FA;;;SY)(A;;FA;;;BA)')
# Create protected objects from birth. Never import source owners/DACLs/links,
# or leave a user-writable handle window between copying and ACL hardening.
[IO.Directory]::CreateDirectory($installRoot,$directorySecurity) | Out-Null
[IO.Directory]::CreateDirectory($stateRoot,$directorySecurity) | Out-Null
[IO.Directory]::CreateDirectory((Join-Path $stateRoot 'runs'),$directorySecurity) | Out-Null
foreach ($protectedRoot in @($installRoot,$stateRoot)) {
    $createdAcl = Get-Acl -LiteralPath $protectedRoot
    if ($createdAcl.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-18' -or -not $createdAcl.AreAccessRulesProtected) { throw 'Protected root creation raced or failed.' }
}
$totalBytes = 0L
foreach ($property in $manifest.PSObject.Properties) {
    $relative = [string]$property.Name
    if ($relative.Contains('\') -or $relative.StartsWith('/') -or ($relative.Split('/') -contains '..') -or $relative.Contains(':') -or $property.Value -notmatch '^[0-9a-f]{64}$') { throw 'Invalid manifest entry.' }
    $target = [IO.Path]::GetFullPath((Join-Path $installRoot $relative))
    if (-not $target.StartsWith($installRoot + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Manifest path outside install root.' }
    [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target),$directorySecurity) | Out-Null
    $inputFile = [IO.File]::OpenRead((Join-Path $sourceRoot $relative))
    try {
        $totalBytes += $inputFile.Length
        if ($inputFile.Length -gt 64MB -or $totalBytes -gt 512MB) { throw 'Package exceeds size limit.' }
        $outputFile = [IO.FileStream]::new($target,[IO.FileMode]::CreateNew,[Security.AccessControl.FileSystemRights]::Write,[IO.FileShare]::None,8192,[IO.FileOptions]::None,$fileSecurity)
        try { $inputFile.CopyTo($outputFile); $outputFile.Flush($true) } finally { $outputFile.Dispose() }
    } finally { $inputFile.Dispose() }
}
$copied = @(Get-ChildItem -LiteralPath $installRoot -File -Recurse -Force)
if ($copied.Count -ne @($manifest.PSObject.Properties).Count) { throw 'Unexpected package files.' }
foreach ($file in $copied) {
    $relative = $file.FullName.Substring($installRoot.Length + 1).Replace('\','/')
    $property = $manifest.PSObject.Properties[$relative]
    if ($null -eq $property -or (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash -ne $property.Value) { throw 'Installed package digest mismatch.' }
}
# The interpreter alone is readable by AppContainers; all code remains immutable.
foreach ($item in @(Get-ChildItem -LiteralPath $installRoot -Recurse -Force)) { Set-ProtectedAcl $item.FullName ($item.FullName.StartsWith((Join-Path $installRoot 'python') + '\') -or $item.FullName -eq (Join-Path $installRoot 'python')) }
$binary = '"' + (Join-Path $installRoot 'CredentialHost.exe') + '"'
New-Service -Name CraftBotCredentialHost -BinaryPathName $binary -DisplayName 'CraftBot protected credential host' -StartupType Automatic -Description 'Isolated source credential storage, native owner consent, and constrained helpers.' | Out-Null
# Ordinary users may query service identity, but cannot change/start/stop it.
& "$env:SystemRoot\System32\sc.exe" sdset CraftBotCredentialHost 'D:(A;;GA;;;SY)(A;;GA;;;BA)(A;;CCLC;;;AU)' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Service security descriptor failed.' }
Start-Service -Name CraftBotCredentialHost
Write-Output 'Protected service installed. Profiles start empty/locked; no legacy credential state was imported.'
