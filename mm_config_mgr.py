#!/usr/bin/env python3

import os
import shutil
import json
import re
import subprocess
from pathlib import Path

# ------------------------------------------------------------
# Paths & Globals
# ------------------------------------------------------------

HOME = Path.home()
MM_HOME = Path(os.environ.get("MAGICMIRROR_HOME", HOME / "MagicMirror"))
MODULES_DIR = MM_HOME / "modules"
DEFAULTS_DIR = MODULES_DIR / "default"
CONFIG_DIR = MM_HOME / "config"
CONFIG_JS = CONFIG_DIR / "config.js"

MY_CONFIG = HOME / "my_config"
MASTER = MY_CONFIG / "config.Master"
MASTER_BAK = MY_CONFIG / "config.Master.bak"
CONFIG_JS_BAK = MY_CONFIG / "config.js.bak"
TEMPLATES_DIR = MY_CONFIG / "templates"

PAGES_MODULE = "MMM-pages"

# ------------------------------------------------------------
# Utility
# ------------------------------------------------------------

def die(msg):
    print(f"\nERROR: {msg}")
    rollback()
    exit(1)

def confirm(prompt):
    return input(f"{prompt} [y/N]: ").lower() == "y"

def backup():
    if MASTER.exists():
        shutil.copy2(MASTER, MASTER_BAK)
    if CONFIG_JS.exists():
        shutil.copy2(CONFIG_JS, CONFIG_JS_BAK)

def rollback():
    print("Rolling back…")
    if MASTER_BAK.exists():
        shutil.copy2(MASTER_BAK, MASTER)
    if CONFIG_JS_BAK.exists():
        shutil.copy2(CONFIG_JS_BAK, CONFIG_JS)

def get_pm2_process_name():
    """Detect the PM2 process name for MagicMirror."""
    try:
        result = subprocess.run(
            ["pm2", "jlist"],
            capture_output=True,
            text=True,
            check=True
        )
        processes = json.loads(result.stdout)
        
        # Look for process with MagicMirror in the path or name
        for proc in processes:
            name = proc.get("name", "")
            script = proc.get("pm2_env", {}).get("pm_exec_path", "")
            
            # Check if it's a MagicMirror process
            if "MagicMirror" in script or "magicmirror" in script.lower():
                print(f"Detected PM2 process: {name}")
                return name
            
            # Also check common names
            if name.lower() in ["magicmirror", "mm", "magic-mirror"]:
                print(f"Detected PM2 process: {name}")
                return name
        
        # Default fallback
        print("⚠ Could not detect PM2 process, using 'MagicMirror'")
        return "MagicMirror"
        
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError):
        print("⚠ Could not query PM2, using 'MagicMirror'")
        return "MagicMirror"

# ------------------------------------------------------------
# Discovery
# ------------------------------------------------------------
def find_modules():
    mods = set()

    for d in MODULES_DIR.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name != "default":
            mods.add(d.name)

    return sorted(mods)

def uses_pages(master_text):
    return PAGES_MODULE in master_text

# ------------------------------------------------------------
# Master / Templates
# ------------------------------------------------------------

def init_my_config():
    MY_CONFIG.mkdir(exist_ok=True)
    TEMPLATES_DIR.mkdir(exist_ok=True)

    if not MASTER.exists():
        print("Creating config.Master from config.js")
        shutil.copy2(CONFIG_JS, MASTER)

def extract_module_block(text, module):
    """
    Extract a module block by finding the module: line and counting braces.
    """
    lines = text.split('\n')
    
    # Find the line with the module declaration
    module_line_idx = None
    for i, line in enumerate(lines):
        # Match module: "ModuleName" or module: 'ModuleName'
        if re.search(rf'module:\s*["\']' + re.escape(module) + r'["\']', line):
            module_line_idx = i
            break
    
    if module_line_idx is None:
        return None
    
    # Search backwards to find the opening brace
    start_idx = module_line_idx
    while start_idx > 0:
        if re.match(r'^\s*\{\s*$', lines[start_idx]):
            break
        start_idx -= 1
    
    if start_idx == 0 and not re.match(r'^\s*\{\s*$', lines[0]):
        # Couldn't find opening brace
        return None
    
    # Count braces forward from start to find the matching closing brace
    brace_count = 0
    end_idx = start_idx
    
    for i in range(start_idx, len(lines)):
        line = lines[i]
        brace_count += line.count('{')
        brace_count -= line.count('}')
        
        if brace_count == 0 and i > start_idx:
            end_idx = i
            break
    
    if brace_count != 0:
        # Couldn't find matching closing brace
        return None
    
    # Extract the block
    block_lines = lines[start_idx:end_idx + 1]
    return '\n'.join(block_lines)

def write_template(module, block):
    tpl = TEMPLATES_DIR / f"{module}.js"
    tpl.write_text(block)
    print(f"✓ Template written: {tpl.name}")

def populate_templates(installed_modules):
    master_text = MASTER.read_text()

    for module in installed_modules:
        if module.startswith("default/"):
           continue
        
        tpl = TEMPLATES_DIR / f"{module}.js"
        if tpl.exists():
            print(f"✓ Template exists: {module}")
            continue

        print(f"Creating template for {module}...", end=" ")

        # Try extracting from master config
        block = extract_module_block(master_text, module)
        if block:
            write_template(module, block)
            continue

        # Try extracting from README
        readme = MODULES_DIR / module / "README.md"
        if readme.exists():
            text = readme.read_text(errors="ignore")
            block = extract_module_block(text, module)
            if block:
                write_template(module, block)
                continue

        # Try sample directory
        sample = MODULES_DIR / module / "sample" / f"{module}.js"
        if sample.exists():
            write_template(module, sample.read_text())
            continue

        print(f"⚠ No template source found for {module}, skipping")

# ------------------------------------------------------------
# Config Generation
# ------------------------------------------------------------

def generate_config(modules, use_pages=False, pages_module_name=None):
    """Generate config.js from head, module templates, and tail."""
    
    head_file = MY_CONFIG / "head"
    tail_file = MY_CONFIG / "tail"
    pages_file = MY_CONFIG / "pages"
    
    # Check if head and tail exist
    if not head_file.exists():
        die(f"Missing head file: {head_file}")
    if not tail_file.exists():
        die(f"Missing tail file: {tail_file}")
    
    # Start with head
    config_content = head_file.read_text()
    
    # Add each module template
    for i, m in enumerate(modules):
        tpl = TEMPLATES_DIR / f"{m}.js"
        if not tpl.exists():
            die(f"Missing template for {m}")
        
        module_content = tpl.read_text().rstrip()
        
        # Remove trailing comma if it exists
        if module_content.endswith(','):
            module_content = module_content[:-1]
        
        # Add proper indentation (assuming templates don't have leading indentation)
        config_content += "      " + module_content
        
        # Add comma if not the last module or if we're adding pages next
        if i < len(modules) - 1 or use_pages:
            config_content += ","
        
        config_content += "\n"
    
    # Add pages if requested
    if use_pages:
        if not pages_file.exists():
            die(f"Missing pages file: {pages_file}")
        
        pages_content = pages_file.read_text()
        
        # Replace MODULE placeholder with actual module name
        if pages_module_name:
            pages_content = pages_content.replace("MODULE", pages_module_name)
        
        config_content += pages_content
    
    # Add tail
    config_content += tail_file.read_text()
    
    CONFIG_JS.write_text(config_content)

def run_mm_test():
    pm2_name = get_pm2_process_name()
    print(f"Restarting MagicMirror ({pm2_name})...")
    subprocess.run(["pm2", "restart", pm2_name], check=False)

# ------------------------------------------------------------
# Menu Actions
# ------------------------------------------------------------

def test_flow(modules, allow_pages, pages_module_name=None, allow_master_update=False):
    backup()
    try:
        generate_config(modules, use_pages=allow_pages, pages_module_name=pages_module_name)
        run_mm_test()
    except Exception as e:
        die(str(e))

    # Only prompt to update master if allowed
    if allow_master_update:
        if not confirm("Update Master?"):
            rollback()
            return False
        
        MASTER.write_text(CONFIG_JS.read_text())
        print("Master updated.")
        return True
    
    return False

def menu():
    while True:
        print("""
MagicMirror Config Manager

1) Test a Module
2) Remove Module
3) Change Module Parameters
4) Modify Pages
5) Exit
""")
        choice = input("Select: ")

        if choice == "1":
            test_module()
        elif choice == "2":
            remove_module()
        elif choice == "3":
            change_params()
        elif choice == "4":
            modify_pages()
        elif choice == "5":
            exit(0)

# ------------------------------------------------------------
# Selection Helpers
# ------------------------------------------------------------

def select_module(prompt="Select module"):
    """Display a menu of available modules and return the selected one."""
    modules = parse_master_modules()
    
    if not modules:
        print("No modules found in master config")
        return None
    
    print(f"\n{prompt}:")
    print("-" * 40)
    for i, mod in enumerate(modules, 1):
        print(f"{i:2d}) {mod}")
    print()
    
    try:
        choice = int(input("Enter number: "))
        if 1 <= choice <= len(modules):
            return modules[choice - 1]
        else:
            print("Invalid selection")
            return None
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled")
        return None

def select_from_list(items, prompt="Select item"):
    """Generic selection from a list."""
    if not items:
        print("No items available")
        return None
    
    print(f"\n{prompt}:")
    print("-" * 40)
    for i, item in enumerate(items, 1):
        print(f"{i:2d}) {item}")
    print()
    
    try:
        choice = int(input("Enter number: "))
        if 1 <= choice <= len(items):
            return items[choice - 1]
        else:
            print("Invalid selection")
            return None
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled")
        return None

# ------------------------------------------------------------
# Menu Implementations (Skeletons)
# ------------------------------------------------------------

def test_module():
    module = select_module("Select module to test")
    if not module:
        return
    
    master_modules = parse_master_modules()
    has_pages_in_master = PAGES_MODULE in master_modules

    # Step 1: Test just the module
    print("\n=== Testing module alone ===")
    test_flow([module], False)

    # Step 2: Test with pages if available (using simple pages template)
    if has_pages_in_master and confirm("Test with 2 pages?"):
        print("\n=== Testing module with pages ===")
        test_flow(["clock", module], True, pages_module_name=module)

    # Step 3: Test with full master config (only if user wants to)
    if not confirm("Test with full master?"):
        print("Testing cancelled.")
        rollback()
        return
    
    print("\n=== Testing with full master config ===")
    
    # Build final module list
    final_modules = []
    
    # Add all existing modules from master
    for m in master_modules:
        final_modules.append(m)
    
    # Only add the test module if it's not already in master
    if module not in final_modules:
        print(f"Adding {module} to master config...")
        final_modules.append(module)
    else:
        print(f"{module} already in master config")
    
    # For full master test, DON'T use the pages template - it's already in the modules
    test_flow(final_modules, False, allow_master_update=True)

def remove_module():
    module = select_module("Select module to remove")
    if not module:
        return
    
    if not confirm(f"Remove {module} from config?"):
        return
    
    mods = [m for m in parse_master_modules() if m != module]
    has_pages = PAGES_MODULE in mods
    
    # Don't use pages template - it's in the module list if needed
    test_flow(mods, False, allow_master_update=True)

def change_params():
    module = select_module("Select module to edit parameters")
    if not module:
        return
    
    print(f"Parameter editor for {module} not yet implemented (safe stub).")

def modify_pages():
    if not uses_pages(MASTER.read_text()):
        print("Pages not in use.")
        return
    print("Page modification stub.")

def parse_master_modules():
    text = MASTER.read_text()
    return re.findall(r"module:\s*[\"']([^\"']+)[\"']", text)

# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    if not MM_HOME.exists():
        die("MagicMirror directory not found")

    init_my_config()
    installed = find_modules()
    populate_templates(installed)
    menu()

if __name__ == "__main__":
    main()
