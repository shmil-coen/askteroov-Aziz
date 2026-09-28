<#
  הסקטארוב — "תקן דרייבר למכשיר המחובר"
  מצמיד דרייבר חתום (מתיקיית tools) להתקן Android/MediaTek שמחובר בלי דרייבר —
  בדיוק מה ש"עדכן מנהל התקן ← יש לי תקליטור" עושה במנהל ההתקנים, גם כשהמזהה
  (VID/PID) של המכשיר לא כתוב בקובץ ה-INF.
  דורש הרשאת מנהל. כותב דוח לקובץ -ReportPath (שורה לכל התקן).
#>
param(
  [Parameter(Mandatory=$true)][string]$ToolsDir,
  [string]$ReportPath = "",
  [string]$OnlyInstance = ""
)
$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class HskDrv {
  [StructLayout(LayoutKind.Sequential)]
  public struct SP_DEVINFO_DATA { public int cbSize; public Guid ClassGuid; public int DevInst; public IntPtr Reserved; }

  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct SP_DEVINSTALL_PARAMS {
    public int cbSize; public int Flags; public int FlagsEx; public IntPtr hwndParent;
    public IntPtr InstallMsgHandler; public IntPtr InstallMsgHandlerContext; public IntPtr FileQueue;
    public UIntPtr ClassInstallReserved; public int Reserved;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string DriverPath;
  }

  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
  public struct SP_DRVINFO_DATA {
    public int cbSize; public int DriverType; public UIntPtr Reserved;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string Description;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string MfgName;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 256)] public string ProviderName;
    public long DriverDate; public ulong DriverVersion;
  }

  const int DIGCF_PRESENT = 0x2, DIGCF_ALLCLASSES = 0x4;
  const int DI_ENUMSINGLEINF = 0x00010000;
  const int DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000800;
  const int SPDIT_CLASSDRIVER = 1, SPDIT_COMPATDRIVER = 2;
  const int SPDRP_HARDWAREID = 1, SPDRP_COMPATIBLEIDS = 2;

  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern IntPtr SetupDiGetClassDevs(IntPtr classGuid, string enumerator, IntPtr hwnd, int flags);
  [DllImport("setupapi.dll", SetLastError = true)]
  static extern bool SetupDiEnumDeviceInfo(IntPtr set, int index, ref SP_DEVINFO_DATA data);
  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool SetupDiGetDeviceInstanceId(IntPtr set, ref SP_DEVINFO_DATA data, StringBuilder id, int size, out int req);
  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool SetupDiGetDeviceRegistryProperty(IntPtr set, ref SP_DEVINFO_DATA data, int prop, out int regType, byte[] buf, int size, out int req);
  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool SetupDiGetDeviceInstallParams(IntPtr set, ref SP_DEVINFO_DATA data, ref SP_DEVINSTALL_PARAMS p);
  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool SetupDiSetDeviceInstallParams(IntPtr set, ref SP_DEVINFO_DATA data, ref SP_DEVINSTALL_PARAMS p);
  [DllImport("setupapi.dll", SetLastError = true)]
  static extern bool SetupDiBuildDriverInfoList(IntPtr set, ref SP_DEVINFO_DATA data, int type);
  [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool SetupDiEnumDriverInfo(IntPtr set, ref SP_DEVINFO_DATA data, int type, int index, ref SP_DRVINFO_DATA drv);
  [DllImport("setupapi.dll", SetLastError = true)]
  static extern bool SetupDiDestroyDeviceInfoList(IntPtr set);
  [DllImport("newdev.dll", CharSet = CharSet.Unicode, SetLastError = true)]
  static extern bool DiInstallDevice(IntPtr hwnd, IntPtr set, ref SP_DEVINFO_DATA data, ref SP_DRVINFO_DATA drv, int flags, out bool reboot);

  static string MultiSz(IntPtr set, ref SP_DEVINFO_DATA d, int prop) {
    int t, req; byte[] b = new byte[4096];
    if (!SetupDiGetDeviceRegistryProperty(set, ref d, prop, out t, b, b.Length, out req)) return "";
    return Encoding.Unicode.GetString(b, 0, Math.Max(0, req)).Replace('\0', '|').ToLowerInvariant();
  }

  // מחזיר רשימת התקני USB נוכחיים: InstanceId \t HardwareIds \t CompatibleIds
  public static string ListUsb() {
    IntPtr set = SetupDiGetClassDevs(IntPtr.Zero, "USB", IntPtr.Zero, DIGCF_PRESENT | DIGCF_ALLCLASSES);
    var sb = new StringBuilder();
    try {
      var d = new SP_DEVINFO_DATA(); d.cbSize = Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
      for (int i = 0; SetupDiEnumDeviceInfo(set, i, ref d); i++) {
        var id = new StringBuilder(512); int req;
        SetupDiGetDeviceInstanceId(set, ref d, id, 512, out req);
        sb.Append(id.ToString()).Append('\t').Append(MultiSz(set, ref d, SPDRP_HARDWAREID))
          .Append('\t').Append(MultiSz(set, ref d, SPDRP_COMPATIBLEIDS)).Append('\n');
      }
    } finally { SetupDiDestroyDeviceInfoList(set); }
    return sb.ToString();
  }

  // מתקין על ההתקן instanceId את הדגם מקובץ inf שתיאורו מכיל keyword. מחזיר תיאור הדגם שהותקן.
  public static string Install(string instanceId, string inf, string keyword) {
    IntPtr set = SetupDiGetClassDevs(IntPtr.Zero, "USB", IntPtr.Zero, DIGCF_PRESENT | DIGCF_ALLCLASSES);
    try {
      var d = new SP_DEVINFO_DATA(); d.cbSize = Marshal.SizeOf(typeof(SP_DEVINFO_DATA));
      for (int i = 0; SetupDiEnumDeviceInfo(set, i, ref d); i++) {
        var id = new StringBuilder(512); int req;
        SetupDiGetDeviceInstanceId(set, ref d, id, 512, out req);
        if (!string.Equals(id.ToString(), instanceId, StringComparison.OrdinalIgnoreCase)) continue;
        var p = new SP_DEVINSTALL_PARAMS(); p.cbSize = Marshal.SizeOf(typeof(SP_DEVINSTALL_PARAMS));
        if (!SetupDiGetDeviceInstallParams(set, ref d, ref p)) throw new Exception("GetDeviceInstallParams " + Marshal.GetLastWin32Error());
        p.DriverPath = inf; p.Flags |= DI_ENUMSINGLEINF; p.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS;
        if (!SetupDiSetDeviceInstallParams(set, ref d, ref p)) throw new Exception("SetDeviceInstallParams " + Marshal.GetLastWin32Error());
        if (!SetupDiBuildDriverInfoList(set, ref d, SPDIT_CLASSDRIVER)) throw new Exception("BuildDriverInfoList " + Marshal.GetLastWin32Error());
        var drv = new SP_DRVINFO_DATA(); drv.cbSize = Marshal.SizeOf(typeof(SP_DRVINFO_DATA));
        for (int j = 0; SetupDiEnumDriverInfo(set, ref d, SPDIT_CLASSDRIVER, j, ref drv); j++) {
          if (drv.Description.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) < 0) continue;
          bool reboot;
          if (!DiInstallDevice(IntPtr.Zero, set, ref d, ref drv, 0, out reboot))
            throw new Exception("DiInstallDevice " + Marshal.GetLastWin32Error());
          return drv.Description + (reboot ? " (נדרשת הפעלה מחדש)" : "");
        }
        throw new Exception("לא נמצא בקובץ הדרייבר דגם שמתאים ל-" + keyword);
      }
      throw new Exception("ההתקן לא נמצא (נותק?)");
    } finally { SetupDiDestroyDeviceInfoList(set); }
  }
}
"@

$report = New-Object System.Collections.Generic.List[string]
function Say($s) { $report.Add($s) }

# התקנים שכרגע בלי דרייבר (או בבעיה)
$bad = @(Get-PnpDevice -PresentOnly | Where-Object {
  $_.InstanceId -like 'USB\VID_*' -and $_.Status -ne 'OK'
})
if ($OnlyInstance) { $bad = @($bad | Where-Object { $_.InstanceId -eq $OnlyInstance }) }

$ids = @{}
foreach ($line in [HskDrv]::ListUsb().Split("`n")) {
  $p = $line.Split("`t"); if ($p.Count -ge 3) { $ids[$p[0].ToLower()] = $p }
}

$fbInf  = Join-Path $ToolsDir "fastboot_driver\android_winusb.inf"
$mtkInf = Join-Path $ToolsDir "mediatek_driver\cdc-acm.inf"

$fixed = 0
foreach ($dev in $bad) {
  $info = $ids[$dev.InstanceId.ToLower()]
  $hw = if ($info) { $info[1] } else { "" }
  $cp = if ($info) { $info[2] } else { "" }
  $inf = $null; $kw = $null; $what = $null
  if ($cp -match 'class_ff&subclass_42&prot_03') { $inf = $fbInf; $kw = 'Bootloader'; $what = 'Fastboot' }
  elseif ($cp -match 'class_ff&subclass_42&prot_01') {
    $inf = $fbInf; $what = 'ADB'
    $kw = if ($dev.InstanceId -match '&MI_') { 'Composite ADB' } else { 'ADB Interface' }
  }
  elseif ($hw -match 'vid_0e8d&pid_(0003|2000)') { $inf = $mtkInf; $what = 'BROM/Preloader'
    $kw = if ($hw -match 'pid_0003') { 'MediaTek USB Port' } else { 'PreLoader' } }
  if (-not $inf) { continue }   # לא התקן Android/MediaTek שאנחנו מטפלים בו
  if (-not (Test-Path $inf)) { Say("ERR`t$what`tקובץ הדרייבר חסר: $inf"); continue }
  try {
    $r = [HskDrv]::Install($dev.InstanceId, $inf, $kw)
    Say("OK`t$what`t$r"); $fixed++
  } catch {
    Say("ERR`t$what`t$($_.Exception.Message)")
  }
}
if ($fixed -eq 0 -and $report.Count -eq 0) { Say("NONE`t`tלא נמצא מכשיר Android מחובר שחסר לו דרייבר") }
if ($ReportPath) { $report | Set-Content -Path $ReportPath -Encoding UTF8 }
$report | ForEach-Object { Write-Output $_ }
