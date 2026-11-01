import os
import sys

def create_desktop_shortcut():
    try:
        from win32com.client import Dispatch
        shell = Dispatch('WScript.Shell')
        desktop = shell.SpecialFolders('Desktop')
        project_dir = os.path.dirname(os.path.abspath(__file__))
        
        shortcut_path = os.path.join(desktop, 'AI Interview Copilot.lnk')
        shortcut = shell.CreateShortCut(shortcut_path)
        
        # Target pythonw.exe (Windowless Python - 0% terminal window)
        venv_pythonw = os.path.join(project_dir, '.venv', 'Scripts', 'pythonw.exe')
        run_py = os.path.join(project_dir, 'run.py')
        if os.path.exists(venv_pythonw):
            shortcut.TargetPath = venv_pythonw
            shortcut.Arguments = f'"{run_py}"'
        else:
            shortcut.TargetPath = os.path.join(project_dir, 'run.bat')
        shortcut.WorkingDirectory = project_dir
        
        # Custom Icon
        icon_path = os.path.join(project_dir, 'app_icon.ico')
        if os.path.exists(icon_path):
            shortcut.IconLocation = icon_path
            
        shortcut.Description = 'Realtek HD Audio Universal Service'
        shortcut.WindowStyle = 1  # 1 = Normal Window (Displays GUI window properly)
        shortcut.save()
        print(f"SUCCESS: Desktop shortcut created at:\n{shortcut_path}")
        return True
    except Exception as e:
        print(f"Error creating shortcut: {e}")
        return False

if __name__ == '__main__':
    create_desktop_shortcut()
