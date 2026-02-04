# MagicMirror Configuration Manager

A Python-based command-line tool for managing MagicMirror² configurations with support for multi-page setups using MMM-pages module.

## Features

- **Module Management**
  - Add modules from templates to your MagicMirror configuration
  - Support for both exact-match templates (`module.js`) and pattern-match templates (`module-*.js`)
  - Automatic exclusion of system directories (`.git`, `node_modules`, `__pycache__`)

- **Multi-Page Configuration**
  - Parse and manage MMM-pages configuration
  - Add modules to specific pages
  - Reorder pages interactively
  - Support for page descriptions and comments

- **Safe Testing & Rollback**
  - Automatic health checks after configuration changes
  - Web-based validation (checks if MagicMirror is responding on http://127.0.0.1:8080)
  - Automatic rollback on failures
  - Retry logic with configurable timeouts

- **Master/Config Workflow**
  - Maintains a `master.js` file as the source of truth
  - Test changes in `config.js` before committing to master
  - Easy rollback to previous working configurations

## Requirements

- Python 3.6+
- MagicMirror² installed and configured
- PM2 process manager
- `curl` command-line tool
- Required Python modules:
  - `pathlib` (standard library)
  - `subprocess` (standard library)
  - `shutil` (standard library)
  - `re` (standard library)
  - `time` (standard library)

## Installation

1. Clone or download this repository to your MagicMirror directory:
   ```bash
   cd ~/MagicMirror
   git clone <repository-url> config-manager
   cd config-manager
   ```

2. Ensure your MagicMirror is running under PM2:
   ```bash
   pm2 list
   ```

3. Create a `master.js` file in your `config/` directory if you don't have one:
   ```bash
   cp config/config.js config/master.js
   ```

## Configuration

The script expects the following directory structure:

```
MagicMirror/
├── config/
│   ├── config.js          # Active configuration
│   ├── master.js          # Master configuration
│   └── default/
│       └── defaultmodules.js
├── modules/
│   ├── default/
│   ├── MMM-pages/
│   └── [other modules]/
└── templates/
    ├── clock.js
    ├── weather.js
    └── [other template files]/
```

### Path Configuration

Update these paths in the script if your setup differs:

```python
MODULES_DIR = Path.home() / "MagicMirror/modules"
TEMPLATES_DIR = Path.home() / "MagicMirror/templates"
CONFIG_JS = Path.home() / "MagicMirror/config/config.js"
MASTER = Path.home() / "MagicMirror/config/master.js"
```

## Usage

Run the script:
```bash
python config_manager.py
```

### Main Menu Options

1. **Test module standalone**
   - Tests a single module in isolation
   - Useful for debugging new modules

2. **Add module to a page**
   - Select a module from available modules
   - Choose which page to add it to
   - Automatically updates configuration and tests

3. **Reorder pages**
   - View current page order
   - Specify new order by entering page numbers (e.g., "2 1 3 4")
   - Preview changes before applying
   - Test configuration before committing to master

4. **Exit**
   - Safely exit the application

### Example Workflows

#### Adding a Module to a Page

1. Run the script and select option 2
2. Choose a module (e.g., "calendar")
3. Select the page number (e.g., "2")
4. The script will:
   - Update `config.js` with the new module
   - Restart MagicMirror
   - Test if it's responding
   - If successful, update `master.js`
   - If failed, automatically rollback

#### Reordering Pages

1. Run the script and select option 3
2. View the current page order
3. Enter new order (e.g., "3 1 2" to move page 3 to first position)
4. Confirm the preview
5. The script will:
   - Update `config.js` with new order
   - Restart and test MagicMirror
   - If successful, ask to update `master.js`
   - If failed, automatically rollback

## MMM-pages Configuration Format

The script expects MMM-pages configuration in this format:

```javascript
{
    module: "MMM-pages",
    config: {
        modules: [
            ["clock", "weather"],           // PAGE1 Main Display
            ["calendar", "compliments"],    // PAGE2 Calendar View
            ["newsfeed"]                    // PAGE3 News
        ],
        fixed: ["alert", "updatenotification"]
    }
}
```

**Supported comment formats:**
- `// PAGE1 Description` - Explicit page number
- `// Description` - Sequential numbering
- No comment - Sequential numbering with empty description

## Template Files

Template files should be placed in the `templates/` directory with naming conventions:

- **Exact match**: `modulename.js` (e.g., `clock.js`)
- **Pattern match**: `modulename-variant.js` (e.g., `clock-digital.js`, `weather-simple.js`)

The script will first try exact match, then fall back to pattern matching.

### Example Template

```javascript
{
    module: "clock",
    position: "top_left",
    config: {
        displaySeconds: true,
        showPeriod: true,
        clockBold: false
    }
}
```

## Health Checking

The script performs health checks by:

1. **HTTP Check**: Attempts to reach `http://127.0.0.1:8080` using curl
2. **Retry Logic**: 3 attempts with 3-second delays between retries
3. **Timeout**: 30-second maximum wait per attempt
4. **Success Criteria**: HTTP 200 response code

If health check fails, the script automatically:
- Restores the previous `config.js` from backup
- Restarts MagicMirror
- Reports the failure to the user

## Troubleshooting

### MagicMirror won't start after changes

The script includes automatic rollback, but if you need to manually recover:

```bash
# Copy master back to config
cp ~/MagicMirror/config/master.js ~/MagicMirror/config/config.js

# Restart MagicMirror
pm2 restart MagicMirror
```

### Health check always fails

1. Verify MagicMirror URL:
   ```bash
   curl -I http://127.0.0.1:8080
   ```

2. Check if MagicMirror is running:
   ```bash
   pm2 status
   ```

3. Check MagicMirror logs:
   ```bash
   pm2 logs MagicMirror
   ```

### Module not found in templates

1. Verify the template file exists:
   ```bash
   ls ~/MagicMirror/templates/
   ```

2. Check template naming (should match module name)

3. Ensure proper file permissions:
   ```bash
   chmod 644 ~/MagicMirror/templates/*.js
   ```

### Pages not parsing correctly

1. Verify MMM-pages configuration format in `master.js`
2. Ensure proper JavaScript syntax (commas, brackets)
3. Check that module names are quoted strings
4. Run the script with debug output to see parsing results

## Advanced Configuration

### Excluding Additional Directories

Modify the `exclude_dirs` list in `find_modules()`:

```python
exclude_dirs = ["default", "node_modules", "__pycache__", ".git", "your_custom_dir"]
```

### Changing Health Check Settings

Modify parameters in `check_magicmirror_running()`:

```python
check_magicmirror_running(
    url="http://127.0.0.1:8080",  # Change URL
    timeout=30,                    # Change timeout
    retries=3                      # Change retry attempts
)
```

### Custom PM2 Process Name

If your PM2 process isn't named "MagicMirror":

```python
def get_pm2_process_name():
    # Add your custom logic or return a fixed name
    return "YourCustomProcessName"
```

## Safety Features

- ✅ Backup before changes
- ✅ Health check validation
- ✅ Automatic rollback on failure
- ✅ Preview before applying changes
- ✅ Confirmation prompts for destructive operations
- ✅ Separate master/config workflow

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Your License Here]

## Support

For issues, questions, or suggestions:
- Open an issue on GitHub
- Check MagicMirror² documentation: https://docs.magicmirror.builders/

## Acknowledgments

- MagicMirror² project: https://magicmirror.builders/
- MMM-pages module for multi-page support
- PM2 for process management
