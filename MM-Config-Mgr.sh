#!/usr/bin/env bash
set -e

BASE_DIR="$HOME/MagicMirror/my_config"
CONFIG_DIR="$HOME/MagicMirror/config"
MASTER_CONFIG="$BASE_DIR/config.Master"

# Function to wait for user approval
wait_for_approval() {
  local prompt="$1"
  echo
  echo "$prompt"
  read -rp "Continue? (Y/n): " response
  if [[ "$response" =~ ^[Nn] ]]; then
    echo "Stopping. Restoring backup..."
    cp "$CONFIG_DIR/config.BAK" "$CONFIG_DIR/config.js"
    pm2 restart MagicMirror
    exit 0
  fi
}

# Function to update position in template file
update_template_position() {
  local template="$1"
  local new_position="$2"
  
  awk -v pos="$new_position" '
    /position:[[:space:]]*"/ {
      sub(/position:[[:space:]]*"[^"]*"/, "position: \"" pos "\"")
    }
    { print }
  ' "$template" > "$template.tmp"
  
  mv "$template.tmp" "$template"
  echo "Template updated with new position: $new_position"
}

# Function to list available module templates
list_module_templates() {
  echo "Available Module Templates:"
  echo "---------------------------"
  
  mapfile -t TEMPLATES < <(
    for file in "$BASE_DIR"/*; do
      # Skip special files
      basename "$file"
    done | grep -v "^head$" | grep -v "^tail$" | grep -v "^clock$" | grep -v "^pages$" | \
           grep -v "^config\." | grep -v "\.backup" | grep -v "\.tmp$" | sort
  )
  
  if [[ ${#TEMPLATES[@]} -eq 0 ]]; then
    echo "No module templates found in $BASE_DIR"
    return 1
  fi
  
  for i in "${!TEMPLATES[@]}"; do
    printf "%2d) %s\n" $((i+1)) "${TEMPLATES[$i]}"
  done
  
  echo
  read -rp "Select module template number: " TEMPLATE_CHOICE
  
  local idx=$((TEMPLATE_CHOICE-1))
  if [[ $idx -lt 0 || $idx -ge ${#TEMPLATES[@]} ]]; then
    echo "Invalid selection"
    return 1
  fi
  
  SELECTED_TEMPLATE="${TEMPLATES[$idx]}"
  return 0
}

# Function to list modules in master config
list_modules_in_master() {
  echo "Modules in Master Config:"
  echo "-------------------------"
  
  mapfile -t MODULES < <(
    awk '
      /modules:[[:space:]]*\[/ { in_modules=1; next }
      in_modules && /module:[[:space:]]*"/ {
        match($0, /module:[[:space:]]*"([^"]+)"/, arr)
        if (arr[1] != "") print arr[1]
      }
      in_modules && /^[[:space:]]*\]/ { in_modules=0 }
    ' "$MASTER_CONFIG" | sort -u
  )
  
  if [[ ${#MODULES[@]} -eq 0 ]]; then
    echo "No modules found in master config"
    return 1
  fi
  
  for i in "${!MODULES[@]}"; do
    printf "%2d) %s\n" $((i+1)) "${MODULES[$i]}"
  done
  
  echo
  read -rp "Select module number to remove: " MODULE_CHOICE
  
  local idx=$((MODULE_CHOICE-1))
  if [[ $idx -lt 0 || $idx -ge ${#MODULES[@]} ]]; then
    echo "Invalid selection"
    return 1
  fi
  
  SELECTED_MODULE="${MODULES[$idx]}"
  return 0
}

# Function to remove module from page
remove_module_from_page() {
  local config_file="$1"
  local module_name="$2"
  
  echo
  echo "Detected Pages with $module_name:"
  echo "----------------------------------"
  
  # Find pages containing this module
  mapfile -t MODULE_PAGES < <(
    awk -v mod="$module_name" '
      /MMM-pages/ { in_pages=1 }
      in_pages && /\[[^]]+\].*PAGE/ {
        if (index($0, mod)) {
          match($0, /PAGE[0-9]+/)
          page=substr($0, RSTART, RLENGTH)
          desc=$0
          sub(/.*PAGE[0-9]+/, "", desc)
          gsub(/^[[:space:]]*\/\/[[:space:]]*/, "", desc)
          printf "%s|%s\n", page, desc
        }
      }
      in_pages && /\]/ { close_count++ }
      close_count > 3 { in_pages=0 }
    ' "$config_file"
  )
  
  if [[ ${#MODULE_PAGES[@]} -eq 0 ]]; then
    echo "Module $module_name is not on any pages."
    return 1
  fi
  
  for i in "${!MODULE_PAGES[@]}"; do
    IFS="|" read -r page desc <<< "${MODULE_PAGES[$i]}"
    printf "%2d) %-6s %s\n" $((i+1)) "$page" "$desc"
  done
  
  echo " a) Remove from ALL pages"
  echo " c) Cancel"
  echo
  
  read -rp "Select page to remove from: " REMOVE_CHOICE
  
  if [[ "$REMOVE_CHOICE" == "c" ]]; then
    echo "Cancelled."
    return 1
  fi
  
  local timestamp=$(date +"%Y%m%d_%H%M%S")
  local temp_file="$config_file.remove.$timestamp"
  
  if [[ "$REMOVE_CHOICE" == "a" ]]; then
    echo "Removing $module_name from ALL pages..."
    
    awk -v mod="$module_name" '
      /MMM-pages/ { in_pages=1 }
      
      in_pages && /PAGE[0-9]+/ {
        if (index($0, mod)) {
          # Remove the module from the array
          gsub(", *\"" mod "\"", "")
          gsub("\"" mod "\" *, *", "")
          gsub("\"" mod "\"", "")
        }
      }
      
      in_pages && /\]/ { close_count++ }
      close_count > 3 { in_pages=0 }
      
      { print }
    ' "$config_file" > "$temp_file"
    
  else
    local idx=$((REMOVE_CHOICE-1))
    if [[ $idx -lt 0 || $idx -ge ${#MODULE_PAGES[@]} ]]; then
      echo "Invalid selection"
      return 1
    fi
    
    local target_page=$(echo "${MODULE_PAGES[$idx]}" | cut -d'|' -f1)
    echo "Removing $module_name from $target_page..."
    
    awk -v page="$target_page" -v mod="$module_name" '
      $0 ~ page {
        # Remove the module from the array
        gsub(", *\"" mod "\"", "")
        gsub("\"" mod "\" *, *", "")
        gsub("\"" mod "\"", "")
      }
      { print }
    ' "$config_file" > "$temp_file"
  fi
  
  mv "$temp_file" "$config_file"
  echo "Module removed successfully."
  return 0
}

# Main menu
echo "=========================================="
echo "MagicMirror Module Configuration Tool"
echo "=========================================="
echo "1) Add new module"
echo "2) Remove module from page(s)"
echo "3) Exit"
echo
read -rp "Select option: " MAIN_OPTION

case "$MAIN_OPTION" in
  2)
    # Remove module option
    [[ -f "$MASTER_CONFIG" ]] || {
      echo "ERROR: $MASTER_CONFIG not found"
      exit 1
    }
    
    echo
    if ! list_modules_in_master; then
      exit 1
    fi
    
    REMOVE_MODULE="$SELECTED_MODULE"
    echo "Selected: $REMOVE_MODULE"
    echo
    
    if remove_module_from_page "$MASTER_CONFIG" "$REMOVE_MODULE"; then
      echo
      read -rp "Test the updated config? (Y/n): " TEST_REMOVAL
      if [[ "$TEST_REMOVAL" =~ ^[Yy]$ ]] || [[ -z "$TEST_REMOVAL" ]]; then
        cp "$CONFIG_DIR/config.js" "$CONFIG_DIR/config.BAK"
        cp "$MASTER_CONFIG" "$CONFIG_DIR/config.js"
        pm2 restart MagicMirror
        
        wait_for_approval "Check if the removal worked correctly."
        
        echo "Master config updated with module removed."
      fi
    fi
    exit 0
    ;;
    
  3)
    echo "Exiting."
    exit 0
    ;;
    
  1)
    # Continue with add module workflow
    ;;
    
  *)
    echo "Invalid option"
    exit 1
    ;;
esac

# Check if master config exists
[[ -f "$MASTER_CONFIG" ]] || {
  echo "ERROR: $MASTER_CONFIG not found"
  exit 1
}

# Select module template from list
echo
if ! list_module_templates; then
  exit 1
fi

MODULE_FILE="$SELECTED_TEMPLATE"
MODULE_PATH="$BASE_DIR/$MODULE_FILE"

[[ -f "$MODULE_PATH" ]] || {
  echo "ERROR: Module template file not found: $MODULE_PATH"
  exit 1
}

# Extract module name from template
MODULE_NAME=$(grep -m1 "module:" "$MODULE_PATH" | sed -E "s/.*module:[[:space:]]*['\"]([^'\"]+)['\"].*/\1/")

[[ -n "$MODULE_NAME" ]] || {
  echo "ERROR: Could not determine module name from template"
  exit 1
}

echo
echo "Module detected: $MODULE_NAME"

# Extract current position from template
CURRENT_POSITION=$(grep -m1 "position:" "$MODULE_PATH" | sed -E "s/.*position:[[:space:]]*['\"]([^'\"]+)['\"].*/\1/")

if [[ -n "$CURRENT_POSITION" ]]; then
  echo "Current position: $CURRENT_POSITION"
  echo
  read -rp "Change position? (y/N): " CHANGE_POS
  
  if [[ "$CHANGE_POS" =~ ^[Yy]$ ]]; then
    echo
    echo "Available positions:"
    echo "  top_bar, top_left, top_center, top_right"
    echo "  upper_third, middle_center, lower_third"
    echo "  bottom_left, bottom_center, bottom_right, bottom_bar"
    echo "  fullscreen_above, fullscreen_below"
    echo
    read -rp "Enter new position: " NEW_POSITION
    
    # Create a temporary copy for testing
    TEMP_MODULE_PATH="$MODULE_PATH.tmp"
    cp "$MODULE_PATH" "$TEMP_MODULE_PATH"
    update_template_position "$TEMP_MODULE_PATH" "$NEW_POSITION"
    
    # Use temp template for testing
    MODULE_PATH="$TEMP_MODULE_PATH"
    USING_TEMP_TEMPLATE=true
  fi
fi

echo

# Backup current config
cp "$CONFIG_DIR/config.js" "$CONFIG_DIR/config.BAK"

# ============================================================
# STEP 1: Test module in minimal config
# ============================================================
echo "=========================================="
echo "STEP 1: Testing module in minimal config"
echo "=========================================="

cat "$BASE_DIR/head" "$MODULE_PATH" "$BASE_DIR/tail" > "$CONFIG_DIR/config.js"
pm2 restart MagicMirror

wait_for_approval "Check if the module works in minimal config."

# Ask about position update after seeing it
if [[ "$USING_TEMP_TEMPLATE" == "true" ]]; then
  echo
  read -rp "Keep the new position ($NEW_POSITION) and update template? (Y/n): " KEEP_POS
  
  if [[ "$KEEP_POS" =~ ^[Yy]$ ]] || [[ -z "$KEEP_POS" ]]; then
    # Update the original template
    ORIGINAL_MODULE_PATH="$BASE_DIR/$MODULE_FILE"
    cp "$MODULE_PATH" "$ORIGINAL_MODULE_PATH"
    echo "Template file updated with new position."
    MODULE_PATH="$ORIGINAL_MODULE_PATH"
  else
    # Revert to original template
    MODULE_PATH="$BASE_DIR/$MODULE_FILE"
    echo "Using original position."
  fi
  
  # Clean up temp file
  rm -f "$BASE_DIR/$MODULE_FILE.tmp"
  USING_TEMP_TEMPLATE=false
fi

# ============================================================
# STEP 2: Test module with simple pages config
# ============================================================
echo "=========================================="
echo "STEP 2: Testing module with simple pages"
echo "=========================================="

cat "$BASE_DIR/head" "$BASE_DIR/clock" "$MODULE_PATH" "$BASE_DIR/pages" | \
  sed "s/MODULE/${MODULE_NAME}/" > "$CONFIG_DIR/config.js"

pm2 restart MagicMirror

wait_for_approval "Check if the module works with pages."

# ============================================================
# STEP 3: Add module to master config
# ============================================================
echo "=========================================="
echo "STEP 3: Adding module to master config"
echo "=========================================="

# Extract pages from master config
echo "Detected Pages:"
echo "----------------"

mapfile -t PAGES < <(
  awk '
    /MMM-pages/ { in_pages=1 }
    in_pages && /\[[^]]+\].*PAGE/ {
      match($0, /PAGE[0-9]+/)
      page=substr($0, RSTART, RLENGTH)
      desc=$0
      sub(/.*PAGE[0-9]+/, "", desc)
      gsub(/^[[:space:]]*\/\/[[:space:]]*/, "", desc)
      printf "%s|%s\n", page, desc
    }
    in_pages && /\]/ { close_count++ }
    close_count > 3 { in_pages=0 }
  ' "$MASTER_CONFIG"
)

for i in "${!PAGES[@]}"; do
  IFS="|" read -r page desc <<< "${PAGES[$i]}"
  printf "%2d) %-6s %s\n" $((i+1)) "$page" "$desc"
done

echo " n) Create a NEW page"
echo

read -rp "Select a page number or 'n': " PAGE_CHOICE

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
OUT_FILE="$BASE_DIR/config.generated.$TIMESTAMP.js"

# Step 3a: Ensure module block exists in master config
awk -v mod="$MODULE_NAME" -v tpl="$MODULE_PATH" '
  BEGIN {
    inserted = 0
    found = 0
  }

  /modules:[[:space:]]*\[/ {
    print
    in_modules = 1
    next
  }

  in_modules && /\]/ {
    if (!found) {
      # Check if we need to add a comma to the previous line
      if (prev_line ~ /\}[[:space:]]*$/ && prev_line !~ /,$/) {
        # Previous line ends with } but no comma - add one
        sub(/\}[[:space:]]*$/, "},", prev_line)
      }
      if (prev_line != "") print prev_line
      
      print "      // --- Auto-added module ---"
      while ((getline line < tpl) > 0) {
        print "      " line
      }
      close(tpl)
      prev_line = ""
    } else {
      if (prev_line != "") print prev_line
      prev_line = ""
    }
    in_modules = 0
  }

  in_modules {
    if (index($0, "module:") && index($0, mod)) {
      found = 1
    }
    if (prev_line != "") print prev_line
    prev_line = $0
    next
  }

  {
    if (prev_line != "") print prev_line
    prev_line = $0
  }
  
  END {
    if (prev_line != "") print prev_line
  }
' "$MASTER_CONFIG" > "$OUT_FILE"

# Step 3b: Update MMM-pages
if [[ "$PAGE_CHOICE" == "n" ]]; then
  read -rp "Enter page description (e.g. Weather Page, Devotional Page): " PAGE_DESC

  NEXT_PAGE_NUM=$(
    awk '
      BEGIN { max = 0 }
      /PAGE[0-9]+/ {
        match($0, /PAGE[0-9]+/)
        num = substr($0, RSTART+4, RLENGTH-4)
        if (num > max) max = num
      }
      END { print max + 1 }
    ' "$MASTER_CONFIG"
  )

  echo "Adding PAGE$NEXT_PAGE_NUM ($PAGE_DESC) with module $MODULE_NAME"
  
  awk -v mod="$MODULE_NAME" \
      -v pnum="$NEXT_PAGE_NUM" \
      -v pdesc="$PAGE_DESC" '
    /MMM-pages/ { in_pages=1 }

    in_pages && /modules:[[:space:]]*\[/ {
      print
      in_array=1
      next
    }

    in_array && /^[[:space:]]*\]/ {
      print "                  [\"" mod "\"],                                       // PAGE" pnum " - " pdesc
      print
      in_array=0
      in_pages=0
      next
    }

    { print }
  ' "$OUT_FILE" > "$OUT_FILE.tmp"

else
  IDX=$((PAGE_CHOICE-1))
  [[ $IDX -ge 0 && $IDX -lt ${#PAGES[@]} ]] || {
    echo "Invalid page selection"
    exit 1
  }

  TARGET_PAGE=$(echo "${PAGES[$IDX]}" | cut -d'|' -f1)
  echo "Adding $MODULE_NAME to $TARGET_PAGE"

  awk -v page="$TARGET_PAGE" -v mod="$MODULE_NAME" '
    $0 ~ page {
      if ($0 ~ mod) { print; next }
      sub(/\]/, ", \"" mod "\"]")
      print
      next
    }
    { print }
  ' "$OUT_FILE" > "$OUT_FILE.tmp"
fi

mv "$OUT_FILE.tmp" "$OUT_FILE"

# Test the generated config
cp "$OUT_FILE" "$CONFIG_DIR/config.js"
pm2 restart MagicMirror

echo
echo "Generated config from master:"
echo "  $OUT_FILE"
echo

wait_for_approval "Check if the module works in the master config."

# ============================================================
# STEP 4: Make this the new master
# ============================================================
echo "=========================================="
echo "STEP 4: Update master config"
echo "=========================================="

read -rp "Make this the new master config? (Y/n): " MAKE_MASTER

if [[ "$MAKE_MASTER" =~ ^[Yy]$ ]] || [[ -z "$MAKE_MASTER" ]]; then
  # Backup old master
  cp "$MASTER_CONFIG" "$MASTER_CONFIG.backup.$TIMESTAMP"
  # Update master
  cp "$OUT_FILE" "$MASTER_CONFIG"
  echo "Master config updated!"
  echo "Backup saved: $MASTER_CONFIG.backup.$TIMESTAMP"
else
  echo "Master config NOT updated."
fi

echo
echo "=========================================="
echo "SUCCESS - All steps completed!"
echo "=========================================="
echo "Final config: $CONFIG_DIR/config.js"
echo "Generated: $OUT_FILE"

exit 0
