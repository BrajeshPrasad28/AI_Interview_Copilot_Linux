import os
import sys
import shutil
import zipfile
import subprocess
import winreg
import ctypes
import urllib.request
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

def fetch_latest_terms_for_installer(payload_dir: Optional[str] = None, dashboard_url: Optional[str] = None) -> str:
    """Fetch latest published Terms & Conditions from backend API, falling back to bundled TERMS_AND_CONDITIONS.txt."""
    base_url = (dashboard_url or os.getenv("DASHBOARD_API_URL", "http://localhost:5000")).rstrip("/")
    endpoint = f"{base_url}/api/terms-conditions?format=txt"
    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            if resp.status == 200:
                text = resp.read().decode("utf-8", errors="replace").strip()
                if len(text) >= 20:
                    return text
    except Exception:
        pass

    candidate_paths = []
    if payload_dir:
        candidate_paths.append(os.path.join(payload_dir, "TERMS_AND_CONDITIONS.txt"))
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate_paths.append(os.path.join(meipass, "TERMS_AND_CONDITIONS.txt"))
    candidate_paths.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "TERMS_AND_CONDITIONS.txt"))

    for path in candidate_paths:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if content:
                        return content
        except Exception:
            pass

    return (
        "TERMS AND CONDITIONS - INTERVIEW COPILOT SOFTWARE\n\n"
        "By installing and using this software, you agree to be bound by the license, "
        "single-device binding, credit usage, and privacy terms configured by the administrator."
    )


def prompt_terms_acceptance(terms_text: str) -> bool:
    """Display interactive Windows License Agreement dialog (with CLI fallback). Returns True only if user accepts."""
    try:
        import tkinter as tk
        from tkinter import scrolledtext

        accepted = {"value": False}
        root = tk.Tk()
        root.title(f"{APP_NAME} - Terms & Conditions")
        root.geometry("620x460")
        root.resizable(False, False)

        header = tk.Label(
            root,
            text="Please read and accept the Terms & Conditions before installing:",
            font=("Segoe UI", 10, "bold"),
            anchor="w",
            padx=16,
            pady=10,
        )
        header.pack(fill="x")

        text_box = scrolledtext.ScrolledText(root, wrap="word", font=("Segoe UI", 9), height=18, padx=10, pady=8)
        text_box.insert("1.0", terms_text)
        text_box.configure(state="disabled")
        text_box.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        agree_var = tk.BooleanVar(value=False)
        btn_frame = tk.Frame(root, padx=16, pady=12)
        btn_frame.pack(fill="x")

        install_btn = tk.Button(btn_frame, text="Accept & Install", width=16, state="disabled")

        def on_toggle():
            install_btn.configure(state="normal" if agree_var.get() else "disabled")

        chk = tk.Checkbutton(
            btn_frame,
            text="I have read and agree to the Terms & Conditions",
            variable=agree_var,
            command=on_toggle,
        )
        chk.pack(side="left")

        def on_accept():
            accepted["value"] = True
            root.destroy()

        def on_decline():
            accepted["value"] = False
            root.destroy()

        install_btn.configure(command=on_accept)
        cancel_btn = tk.Button(btn_frame, text="Decline", width=10, command=on_decline)
        cancel_btn.pack(side="right", padx=(8, 0))
        install_btn.pack(side="right")

        root.protocol("WM_DELETE_WINDOW", on_decline)
        root.mainloop()
        return bool(accepted["value"])
    except Exception:
        print("=" * 65)
        print(terms_text)
        print("=" * 65)
        try:
            ans = input("Do you accept these Terms & Conditions? [y/N]: ").strip().lower()
            return ans in ("y", "yes")
        except Exception:
            return False


def install_app(source_bundle_dir: str, target_dir: str = DEFAULT_INSTALL_DIR) -> bool:
    """Require T&C acceptance, then silently extract payload without creating desktop/start menu shortcuts."""
    terms_text = fetch_latest_terms_for_installer(source_bundle_dir)
    if not prompt_terms_acceptance(terms_text):
        print("\n[CANCELLED] Installation aborted because Terms & Conditions were declined.")
        return False

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

    # Ensure latest synced T&C text is also written to installed app dir
    try:
        with open(os.path.join(target_dir, "TERMS_AND_CONDITIONS.txt"), "w", encoding="utf-8") as tf:
            tf.write(terms_text)
    except Exception:
        pass

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
    return True

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

