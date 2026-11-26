"""
Linux Desktop Shortcut Creator
Creates a standard XDG .desktop file for AI Interview Copilot.
Run this once to add it to your application launcher / taskbar.
"""

import os
import sys
import stat


def create_desktop_shortcut():
    try:
        project_dir = os.path.dirname(os.path.abspath(__file__))

        # Prefer venv python if present
        venv_python = os.path.join(project_dir, ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = sys.executable  # fall back to current python

        run_py = os.path.join(project_dir, "run.py")
        icon_path = os.path.join(project_dir, "app_icon.png")  # Linux uses PNG; convert .ico if needed

        desktop_entry = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=AI Interview Copilot
Comment=Realtime AI interview assistant with audio capture and screen vision
Exec={venv_python} {run_py}
Icon={icon_path}
Terminal=false
Categories=Utility;Education;
StartupWMClass=AI Interview Copilot
"""

        # Place shortcut in XDG applications dir and on the Desktop
        xdg_data = os.getenv(
            "XDG_DATA_HOME",
            os.path.join(os.path.expanduser("~"), ".local", "share")
        )
        apps_dir = os.path.join(xdg_data, "applications")
        os.makedirs(apps_dir, exist_ok=True)

        app_entry_path = os.path.join(apps_dir, "ai-interview-copilot.desktop")
        with open(app_entry_path, "w", encoding="utf-8") as f:
            f.write(desktop_entry)
        os.chmod(app_entry_path, os.stat(app_entry_path).st_mode | stat.S_IEXEC)

        # Also place on Desktop if it exists
        desktop_dir = os.path.join(os.path.expanduser("~"), "Desktop")
        if os.path.isdir(desktop_dir):
            desktop_path = os.path.join(desktop_dir, "AI_Interview_Copilot.desktop")
            with open(desktop_path, "w", encoding="utf-8") as f:
                f.write(desktop_entry)
            os.chmod(desktop_path, os.stat(desktop_path).st_mode | stat.S_IEXEC)
            print(f"SUCCESS: Desktop shortcut created at:\n{desktop_path}")

        print(f"SUCCESS: Application launcher entry created at:\n{app_entry_path}")

        # Update desktop database so the launcher picks it up
        try:
            import subprocess
            subprocess.run(["update-desktop-database", apps_dir], check=False, timeout=5)
        except Exception:
            pass

        return True
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False


if __name__ == "__main__":
    create_desktop_shortcut()
