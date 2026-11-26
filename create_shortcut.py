"""
Linux Desktop Shortcut Creator
Creates a standard XDG .desktop file for AI Interview Copilot.
Run this once to add it to your application launcher / taskbar.
"""

import ast
import os
import shlex
import shutil
import stat
import subprocess
import sys


_MEDIA_KEYS_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
_CUSTOM_BINDING_BASE = (
    "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"
)
_CUSTOM_BINDING_NAME = "AI Interview Copilot Window Toggle"


def _is_packaged_install(run_py):
    return (
        os.path.realpath(run_py) == "/opt/ai-interview-copilot/run.py"
        and os.path.isfile("/usr/bin/ai-interview-copilot")
    )


def _gsettings(*arguments):
    return subprocess.run(
        ["gsettings", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def install_gnome_toggle_shortcut(python_executable, run_py):
    desktop = os.getenv("XDG_CURRENT_DESKTOP", "").lower()
    if os.getenv("XDG_SESSION_TYPE") != "wayland" or "gnome" not in desktop:
        return False
    if not shutil.which("gsettings"):
        raise RuntimeError("gsettings is required to configure a GNOME shortcut.")

    raw_paths = _gsettings("get", _MEDIA_KEYS_SCHEMA, "custom-keybindings").stdout.strip()
    if raw_paths.startswith("@as "):
        raw_paths = raw_paths[4:]
    paths = ast.literal_eval(raw_paths)
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise RuntimeError("GNOME returned an invalid custom-keybindings list.")

    bindings = (
        ("ai-interview-copilot", _CUSTOM_BINDING_NAME, "--toggle-window", "<Control><Shift>m"),
        (
            "ai-interview-copilot-disable-pass-through",
            "AI Interview Copilot Disable Click-Through",
            "--disable-click-through",
            "<Control><Alt>m",
        ),
    )
    packaged_install = _is_packaged_install(run_py)
    command_prefix = (
        shlex.quote("/usr/bin/ai-interview-copilot")
        if packaged_install
        else f"{shlex.quote(python_executable)} {shlex.quote(run_py)}"
    )
    paths_changed = False
    for slug, name, argument, binding in bindings:
        candidate = _CUSTOM_BINDING_BASE + f"{slug}/"
        suffix = 2
        command = f"{command_prefix} {argument}"
        while candidate in paths:
            schema = f"{_MEDIA_KEYS_SCHEMA}.custom-keybinding:{candidate}"
            existing_name = ast.literal_eval(_gsettings("get", schema, "name").stdout.strip())
            existing_command = ast.literal_eval(_gsettings("get", schema, "command").stdout.strip())
            if (
                existing_name == name
                and isinstance(existing_command, str)
                and argument in existing_command
            ):
                break
            candidate = _CUSTOM_BINDING_BASE + f"{slug}-{suffix}/"
            suffix += 1

        custom_schema = f"{_MEDIA_KEYS_SCHEMA}.custom-keybinding:{candidate}"
        _gsettings("set", custom_schema, "name", name)
        _gsettings("set", custom_schema, "command", command)
        _gsettings("set", custom_schema, "binding", binding)
        if candidate not in paths:
            paths.append(candidate)
            paths_changed = True

    if paths_changed:
        _gsettings("set", _MEDIA_KEYS_SCHEMA, "custom-keybindings", repr(paths))
    return True


def create_desktop_shortcut():
    try:
        project_dir = os.path.dirname(os.path.abspath(__file__))

        # Prefer venv python if present
        venv_python = os.path.join(project_dir, ".venv", "bin", "python")
        if not os.path.exists(venv_python):
            venv_python = sys.executable  # fall back to current python

        run_py = os.path.join(project_dir, "run.py")
        icon_path = os.path.join(project_dir, "app_icon.png")  # Linux uses PNG; convert .ico if needed
        launcher = (
            "/usr/bin/ai-interview-copilot"
            if _is_packaged_install(run_py)
            else f"{shlex.quote(venv_python)} {shlex.quote(run_py)}"
        )

        desktop_entry = f"""[Desktop Entry]
Version=1.0
Type=Application
Name=AI Interview Copilot
Comment=Realtime AI interview assistant with audio capture and screen vision
Exec={launcher}
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

        try:
            if install_gnome_toggle_shortcut(venv_python, run_py):
                print("SUCCESS: GNOME Wayland window toggle registered (Ctrl+Shift+M).")
        except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
            print(f"WARNING: Could not register the GNOME window toggle: {error}")

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
