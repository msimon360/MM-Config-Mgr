#!/usr/bin/env python3

import os
import shutil
import json
import re
import subprocess
import time
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
        shutil.copy2(MASTER_BAK, CONFIG_JS)
    run_mm_test()

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

def extract_module_name_from_template(template_name):
    """Extract the actual MagicMirror module name from a template file."""
    tpl = TEMPLATES_DIR / f"{template_name}.js"
    if not tpl.exists():
        return template_name  # safe fallback

    text = tpl.read_text()
    match = re.search(r'module:\s*["\']([^"\']+)["\']', text)
    if match:
        return match.group(1)

    return template_name

# ------------------------------------------------------------
# Discovery
# ------------------------------------------------------------
import json
import re

def find_modules():
    # Directory names to exclude from processing
    exclude_dirs = ["default", "cheerio", "OLDMMM-MyStandings", "MMM-Template", "Template", "calendars"]
    
    mods = set()
    
    # Process directories, excluding those in the exclusion list
    for d in MODULES_DIR.iterdir():
        if d.is_dir() and not d.name.startswith(".") and d.name not in exclude_dirs:
            mods.add(d.name)
    
    # Add default modules from MODULES_DIR/default/defaultmodules.js
    default_modules_file = MODULES_DIR / "default" / "defaultmodules.js"
    if default_modules_file.exists():
        try:
            content = default_modules_file.read_text()
            # Extract the defaultModules array from the JS file
            # Look for: const defaultModules = [...]
            match = re.search(r'const\s+defaultModules\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if match:
                # Extract the array content and parse module names
                array_content = match.group(1)
                # Find all quoted strings (module names)
                module_names = re.findall(r'["\']([^"\']+)["\']', array_content)
                mods.update(module_names)
        except Exception as e:
            # Handle any errors reading or parsing the file
            print(f"Warning: Could not read default modules: {e}")
    
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
        
        # Try exact match first, then pattern match
        tpl = TEMPLATES_DIR / f"{module}.js"
        if not tpl.exists():
            # Look for module-(something).js pattern
            pattern_files = list(TEMPLATES_DIR.glob(f"{module}-*.js"))
            if pattern_files:
                tpl = pattern_files[0]  # Use the first match
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
    """Generate config.js from head, module templates, and tail.
    
    Args:
        modules: List of template names (e.g., ["clock", "weather-current", "weather-forecast"])
        use_pages: Whether to append the simple pages template
        pages_module_name: Module name to replace MODULE placeholder in pages template
    """
    
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
    for i, template_name in enumerate(modules):
        tpl = TEMPLATES_DIR / f"{template_name}.js"
        if not tpl.exists():
            die(f"Missing template for {template_name}")
        
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

import subprocess
import time

def check_magicmirror_running(url="http://127.0.0.1:8080", timeout=30, retries=3):
    """
    Check if MagicMirror webpage is available.
    Args:
        url: The MagicMirror URL to check
        timeout: Maximum time to wait for response
        retries: Number of times to retry before giving up
    Returns:
        True if webpage is accessible, False otherwise
    """
    for attempt in range(retries):
        try:
            # print(f"Checking MagicMirror (attempt {attempt + 1}/{retries})...")
            # Using curl to check if webpage is available
            result = subprocess.run(
                ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", 
                 "--connect-timeout", "5", "--max-time", str(timeout), url],
                capture_output=True,
                text=True,
                timeout=timeout + 5
            )
            
            http_code = result.stdout.strip()
            # print(f"Received HTTP code: '{http_code}'")  # Debug output
            
            if http_code == "200":
                # print(f"✓ MagicMirror is responding (HTTP {http_code})")
                return True

        except Exception as e:
            print(f"✗ Error checking MagicMirror: {e}")
        
        # Only retry if not the last attempt
        if attempt < retries - 1:
            print(f"Retrying attempt ({attempt +2}) in 3 seconds...")
            time.sleep(3)
    
    # If we get here, all retries failed
    print("✗ All retry attempts failed")
    return False


def run_mm_test():
    pm2_name = get_pm2_process_name()
    print(f"Restarting MagicMirror ({pm2_name})...")
    subprocess.run(["pm2", "restart", pm2_name], check=False)
    
    # Give MagicMirror time to start
    # print("Waiting for MagicMirror to start...")
    time.sleep(5)
    
    # print("Testing if MagicMirror is accessible...")
    result = check_magicmirror_running()
    # print(f"DEBUG: check_magicmirror_running returned: {result}")
    
    if result:
        print(f"✓ MagicMirror is running successfully")
        return True
    else:
        print(f"✗ MagicMirror is not accessible")
        die("=== Test Failed to Run Exiting ===")

# ------------------------------------------------------------
# Menu Actions
# ------------------------------------------------------------

def test_flow(modules, use_pages=False, pages_module_name=None, allow_master_update=False):
    backup()
    try:
        generate_config(modules, use_pages=use_pages, pages_module_name=pages_module_name)
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

def list_available_templates():
    """List all available templates including multi-instance modules."""
    templates = []
    
    for tpl_file in sorted(TEMPLATES_DIR.glob("*.js")):
        # Remove the .js extension
        name = tpl_file.stem
        templates.append(name)
    
    return templates

def select_template(prompt="Select template"):
    """Display a menu of available templates and return the selected one."""
    templates = list_available_templates()
    
    if not templates:
        print("No templates found")
        return None
    
    print(f"\n{prompt}:")
    print("-" * 40)
    for i, tpl in enumerate(templates, 1):
        print(f"{i:2d}) {tpl}")
    print()
    
    try:
        choice = int(input("Enter number: "))
        if 1 <= choice <= len(templates):
            return templates[choice - 1]
        else:
            print("Invalid selection")
            return None
    except (ValueError, KeyboardInterrupt):
        print("\nCancelled")
        return None

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
    template = select_template("Select template to test")
    if not template:
        return
    
    # Extract the base module name (everything before the first hyphen, or the whole name)
    # Examples: "weather-current" -> "weather", "clock" -> "clock"
    module = extract_module_name_from_template(template)
   
    master_modules = parse_master_modules()
    has_pages_in_master = PAGES_MODULE in master_modules

    # Step 1: Test just the module
    print(f"\n=== Testing {template} alone ===")
    test_flow([template], use_pages=False)

    # Step 2: Test with pages if available (using simple pages template)
    if has_pages_in_master and confirm("Test with 2 pages?"):
        print(f"\n=== Testing {template} with pages ===")
        test_flow(["clock", template], use_pages=True, pages_module_name=module)

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
    
    # Only add the test template if it's not already in master
    if template not in final_modules:
        print(f"Adding {template} to master config...")
        final_modules.append(template)
    else:
        print(f"{template} already in master config")
    
    # For full master test, DON'T use the pages template - it's already in the modules
    test_flow(final_modules, use_pages=False, allow_master_update=True)

def remove_module():
    module = select_module("Select module to remove")
    if not module:
        return
    
    if not confirm(f"Remove {module} from config?"):
        return
    
    mods = [m for m in parse_master_modules() if m != module]
    has_pages = PAGES_MODULE in mods
    
    # Don't use pages template - it's in the module list if needed
    test_flow(mods, use_pages=False, allow_master_update=True)

def change_params():
    module = select_module("Select module to edit parameters")
    if not module:
        return
    
    print(f"Parameter editor for {module} not yet implemented (safe stub).")

def parse_pages_from_master():
    """Parse the pages configuration from master and return a dict of page -> modules."""
    text = MASTER.read_text()
    # Find the MMM-pages module block
    lines = text.split('\n')
    in_pages_module = False
    in_modules_array = False
    pages = {}
    page_num = 1
    
    for line in lines:
        # Check if we're entering the MMM-pages module
        if re.search(r'module:\s*["\']MMM-pages["\']', line):
            in_pages_module = True
            continue
        
        # Look for the modules array within MMM-pages
        if in_pages_module and 'modules:' in line and '[' in line:
            in_modules_array = True
            continue
        
        # Parse page entries
        if in_modules_array:
            # Look for array entries like ["module1", "module2"] with optional comment
            # First check if there's a PAGE number comment
            match_with_page = re.search(r'\[(.*?)\].*?//\s*PAGE(\d+)\s*(.*)', line)
            # Otherwise just look for any array with optional comment
            match_basic = re.search(r'\[(.*?)\](?:\s*//\s*(.*))?', line)
            
            if match_with_page:
                modules_str = match_with_page.group(1)
                page_number = match_with_page.group(2)
                description = match_with_page.group(3).strip()
                
                # Parse module names from the array
                modules = re.findall(r'["\']([^"\']+)["\']', modules_str)
                
                page_key = f"PAGE{page_number}"
                pages[page_key] = {
                    'description': description,
                    'modules': modules,
                    'number': int(page_number)
                }
                page_num = max(page_num, int(page_number) + 1)
                
            elif match_basic:
                modules_str = match_basic.group(1)
                description = match_basic.group(2).strip() if match_basic.group(2) else ""
                
                # Parse module names from the array
                modules = re.findall(r'["\']([^"\']+)["\']', modules_str)
                
                # Use sequential numbering
                page_key = f"PAGE{page_num}"
                pages[page_key] = {
                    'description': description,
                    'modules': modules,
                    'number': page_num
                }
                page_num += 1
            
            # Check if we're at the end of the modules array
            if re.match(r'^\s*\]', line):
                in_modules_array = False
                in_pages_module = False
                break
    
    return pages

def update_pages_in_master(pages_dict):
    """Update the pages configuration in master with the new pages."""
    text = MASTER.read_text()
    lines = text.split('\n')
    
    # Find the MMM-pages module and rebuild the modules array
    in_pages_module = False
    in_modules_array = False
    new_lines = []
    skip_until_close_array = False
    
    for i, line in enumerate(lines):
        # Check if we're entering the MMM-pages module
        if re.search(r'module:\s*["\']MMM-pages["\']', line):
            in_pages_module = True
            new_lines.append(line)
            continue
        
        # Look for the modules array
        if in_pages_module and 'modules:' in line and '[' in line:
            in_modules_array = True
            new_lines.append(line)
            
            # Insert the new pages
            sorted_pages = sorted(pages_dict.items(), key=lambda x: x[1]['number'])
            for page_num, (page_key, page_info) in enumerate(sorted_pages, start=1):
                modules_str = ', '.join([f'"{m}"' for m in page_info['modules']])
                page_line = f'                  [{modules_str}],     // PAGE{page_num} {page_info["description"]}'
                new_lines.append(page_line)
            
            skip_until_close_array = True
            continue
        
        # Skip old page entries until we find the closing bracket
        if skip_until_close_array:
            if re.match(r'^\s*\]', line):
                skip_until_close_array = False
                in_modules_array = False
                in_pages_module = False
                new_lines.append(line)
            continue
        
        new_lines.append(line)
    
    MASTER.write_text('\n'.join(new_lines))

def modify_pages():
    if not uses_pages(MASTER.read_text()):
        print("Pages not in use.")
        return
    
    pages = parse_pages_from_master()
    
    if not pages:
        print("No pages found in master config.")
        return
    
    while True:
        print("\n" + "=" * 50)
        print("Current Pages Configuration")
        print("=" * 50)
        
        sorted_pages = sorted(pages.items(), key=lambda x: x[1]['number'])
        page_list = []
        
        for page_key, page_info in sorted_pages:
            modules_str = ", ".join(page_info['modules'])
            print(f"\n{page_key} - {page_info['description']}")
            print(f"  Modules: {modules_str}")
            page_list.append(page_key)
        
        print("\n" + "=" * 50)
        print("\nOptions:")
        for i, page_key in enumerate(page_list, 1):
            print(f"{i}) Edit {page_key}")
        print(f"{len(page_list) + 1}) Add new page")
        print(f"r Reorder Pages")
        print("0) Save and exit")
        print("q) Quit without saving")
        
        choice = input("\nSelect: ").strip()
        
        if choice == '0':
            # Save changes
            backup()
            update_pages_in_master(pages)
 
            # Copy Master → config.js directly
            shutil.copy2(MASTER, CONFIG_JS)

            # Restart MagicMirror to test
            run_mm_test()

            print("Pages updated and tested.")
            return
        elif choice.lower() == 'r':
            reorder_pages()
            return

        elif choice.lower() == 'q':
            print("Changes discarded.")
            return
        
        elif choice == str(len(page_list) + 1):
            # Add new page
            add_new_page(pages)
        
        elif choice.isdigit() and 1 <= int(choice) <= len(page_list):
            # Edit existing page
            page_key = page_list[int(choice) - 1]
            edit_page(pages, page_key)
        
        else:
            print("Invalid selection")

def reorder_pages():
    """Allow user to change the order of pages."""
    pages = parse_pages_from_master()
    
    if not pages:
        print("No pages found in configuration.")
        return
    
    # Display current pages
    print("\n=== Current Page Order ===")
    sorted_pages = sorted(pages.items(), key=lambda x: x[1]['number'])
    for i, (page_key, page_info) in enumerate(sorted_pages, start=1):
        modules_str = ', '.join(page_info['modules'])
        desc = page_info['description'] or "(no description)"
        print(f"{i}. [{modules_str}] - {desc}")
    
    print("\n=== Reorder Pages ===")
    print("Enter the new order as numbers separated by spaces.")
    print(f"Example: To swap first and second page, enter: 2 1 3 4...")
    print("Or press Enter to cancel.")
    
    user_input = input("\nNew order: ").strip()
    
    if not user_input:
        print("Cancelled.")
        return
    
    try:
        # Parse the new order
        new_order = [int(x) for x in user_input.split()]
        
        # Validate the input
        if len(new_order) != len(sorted_pages):
            print(f"Error: You must specify {len(sorted_pages)} page numbers.")
            return
        
        if set(new_order) != set(range(1, len(sorted_pages) + 1)):
            print(f"Error: Invalid page numbers. Use numbers 1 to {len(sorted_pages)}.")
            return
        
        # Reorder the pages
        reordered_pages = {}
        for new_pos, old_pos in enumerate(new_order, start=1):
            old_page_key, old_page_info = sorted_pages[old_pos - 1]
            reordered_pages[f"PAGE{new_pos}"] = {
                'description': old_page_info['description'],
                'modules': old_page_info['modules'],
                'number': new_pos
            }
        
        # Show the new order for confirmation
        print("\n=== New Page Order ===")
        for i, (page_key, page_info) in enumerate(sorted(reordered_pages.items(), key=lambda x: x[1]['number']), start=1):
            modules_str = ', '.join(page_info['modules'])
            desc = page_info['description'] or "(no description)"
            print(f"{i}. [{modules_str}] - {desc}")
        
        confirm = input("\nApply this new order? [y/N]: ").strip().lower()
        if confirm == 'y':
            # Now update config.js with the new page order
            update_pages_in_file(CONFIG_JS, reordered_pages)
            
            # Test MagicMirror with new order
            if run_mm_test():
                print("✓ MagicMirror is running successfully")
                
                # Ask if Master should be updated
                update_master = input("\nUpdate Master with this order? [Y/n]: ").strip().lower()
                if update_master != 'n':
                    update_pages_in_master(reordered_pages)
                    print("✓ Page order updated successfully in Master!")
                else:
                    print("Master not updated. Config.js has the new order, but Master remains unchanged.")
            else:
                print("✗ MagicMirror failed to start with new order")
        else:
            print("Cancelled.")
    
    except ValueError:
        print("Error: Invalid input. Please enter numbers separated by spaces.")
    except Exception as e:
        print(f"Error reordering pages: {e}")

def update_pages_in_file(filepath, pages_dict):
    """Update the pages configuration in a specific file with the new pages."""
    text = filepath.read_text()
    lines = text.split('\n')
    # Find the MMM-pages module and rebuild the modules array
    in_pages_module = False
    in_modules_array = False
    new_lines = []
    skip_until_close_array = False
    
    for i, line in enumerate(lines):
        # Check if we're entering the MMM-pages module
        if re.search(r'module:\s*["\']MMM-pages["\']', line):
            in_pages_module = True
            new_lines.append(line)
            continue
        
        # Look for the modules array
        if in_pages_module and 'modules:' in line and '[' in line:
            in_modules_array = True
            new_lines.append(line)
            # Insert the new pages
            sorted_pages = sorted(pages_dict.items(), key=lambda x: x[1]['number'])
            for page_num, (page_key, page_info) in enumerate(sorted_pages, start=1):
                modules_str = ', '.join([f'"{m}"' for m in page_info['modules']])
                page_line = f'                  [{modules_str}],     // PAGE{page_num} {page_info["description"]}'
                new_lines.append(page_line)
            skip_until_close_array = True
            continue
        
        # Skip old page entries until we find the closing bracket
        if skip_until_close_array:
            if re.match(r'^\s*\]', line):
                skip_until_close_array = False
                in_modules_array = False
                in_pages_module = False
                new_lines.append(line)
            continue
        
        new_lines.append(line)
    
    filepath.write_text('\n'.join(new_lines))

def add_new_page(pages):
    """Add a new page to the pages dictionary."""
    # Find the next page number
    max_page = max([p['number'] for p in pages.values()]) if pages else 0
    next_page_num = max_page + 1
    page_key = f"PAGE{next_page_num}"
    
    description = input("Enter page description: ").strip()
    if not description:
        description = "New Page"
    
    # Get all available templates (not just base module names)
    available_templates = get_all_template_names()
    # Exclude MMM-pages
    available_templates = [t for t in available_templates if not t.startswith("MMM-pages")]
    
    print("\nSelect modules for this page:")
    selected = select_multiple_modules(available_templates)
    
    if not selected:
        print("No modules selected, page not created.")
        return
    
    pages[page_key] = {
        'description': description,
        'modules': selected,
        'number': next_page_num
    }
    
    print(f"✓ {page_key} created")

def edit_page(pages, page_key):
    """Edit an existing page."""
    page_info = pages[page_key]
    
    print(f"\nEditing {page_key} - {page_info['description']}")
    print(f"Current modules: {', '.join(page_info['modules'])}")
    
    print("\nOptions:")
    print("1) Edit module list")
    print("2) Edit description")
    print("3) Delete page")
    print("0) Back")
    
    choice = input("Select: ").strip()
    
    if choice == '1':
        # Edit modules - use all available templates
        available_templates = get_all_template_names()
        # Exclude MMM-pages
        available_templates = [t for t in available_templates if not t.startswith("MMM-pages")]
        
        print("\nSelect modules for this page:")
        print("(Currently selected modules will be marked)")
        selected = select_multiple_modules(available_templates, current=page_info['modules'])
        
        if not selected:
            print("\nNo modules selected. Delete this page? [y/N]: ", end='')
            if input().lower() == 'y':
                del pages[page_key]
                print(f"✓ {page_key} deleted")
        else:
            pages[page_key]['modules'] = selected
            print(f"✓ {page_key} updated")
    
    elif choice == '2':
        # Edit description
        new_desc = input(f"Enter new description [{page_info['description']}]: ").strip()
        if new_desc:
            pages[page_key]['description'] = new_desc
            print(f"✓ Description updated")
    
    elif choice == '3':
        # Delete page
        if confirm(f"Delete {page_key}?"):
            del pages[page_key]
            print(f"✓ {page_key} deleted")

def select_multiple_modules(modules, current=None):
    """Allow user to select multiple modules from a list.
    
    Args:
        modules: List of template names to choose from
        current: List of currently selected template names
    """
    current = current or []
    selected = set(current)
    
    while True:
        print("\n" + "-" * 40)
        for i, mod in enumerate(modules, 1):
            marker = "✓" if mod in selected else " "
            print(f"{i:2d}) [{marker}] {mod}")
        
        print("\nCommands:")
        print("  <number>  - Toggle module")
        print("  done      - Finish selection")
        print("  clear     - Clear all selections")
        print("  cancel    - Cancel changes")
        
        if selected:
            print(f"\nCurrently selected: {', '.join(sorted(selected))}")
        
        choice = input("\nSelect: ").strip().lower()
        
        if choice == 'done':
            return list(selected)
        elif choice == 'clear':
            selected.clear()
        elif choice == 'cancel':
            return current
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(modules):
                mod = modules[idx]
                if mod in selected:
                    selected.remove(mod)
                else:
                    selected.add(mod)
            else:
                print("Invalid selection")
        else:
            print("Invalid command")

def get_all_template_names():
    """Get all template names (for use in pages, etc.)."""
    templates = []
    for tpl_file in sorted(TEMPLATES_DIR.glob("*.js")):
        templates.append(tpl_file.stem)
    return templates

def parse_master_modules():
    """Parse module/template names from master config.
    
    Returns the actual template names as they appear in the templates directory.
    """
    text = MASTER.read_text()
    base_modules = re.findall(r"module:\s*[\"']([^\"']+)[\"']", text)
    
    # For each module instance in the config, try to find a matching template
    result = []
    module_counts = {}
    available_templates = set(get_all_template_names())
    
    for module in base_modules:
        # Count how many times we've seen this module
        module_counts[module] = module_counts.get(module, 0) + 1
        count = module_counts[module]
        
        if count == 1:
            # First instance - check what templates exist
            if module in available_templates:
                # Base template exists (e.g., "clock")
                result.append(module)
            else:
                # Look for descriptive template (e.g., "weather-current")
                # Find all templates that start with this module name
                matching = [t for t in available_templates if t.startswith(f"{module}-")]
                if matching:
                    # Use the first matching template
                    result.append(sorted(matching)[0])
                else:
                    # No template found, use base name anyway
                    result.append(module)
        else:
            # Multiple instances - find the next available template
            matching = [t for t in available_templates if t.startswith(f"{module}-")]
            if matching:
                # Sort and use the appropriate one based on count
                sorted_matching = sorted(matching)
                if count - 1 < len(sorted_matching):
                    result.append(sorted_matching[count - 1])
                else:
                    # Fallback to numbered
                    result.append(f"{module}-{count}")
            else:
                result.append(f"{module}-{count}")
    
    return result

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
