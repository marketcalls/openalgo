# Python Strategy Editor Guide

## Overview

The Python Strategy Editor provides an integrated code editing experience for managing your trading strategies directly within the OpenAlgo web interface. The editor features syntax highlighting, line numbers, and intelligent access control based on strategy state.

## Features

### 1. Syntax Highlighting
- Full Python syntax highlighting
- Keywords, strings, comments, numbers, functions, and decorators are color-coded
- Dark and light theme support

### 2. Line Numbers
- Line numbers are displayed for easy navigation
- Helps in debugging and locating specific code sections

### 3. Smart Access Control
- **View Mode**: When a strategy is running, the editor is read-only
- **Edit Mode**: When a strategy is stopped, full editing capabilities are enabled
- Prevents accidental modifications to running strategies

### 4. No External Dependencies
- All editor components are hosted locally
- No CDN dependencies
- Works in offline environments

## How to Use

### Accessing the Editor

1. Navigate to the Python Strategies page (`/python`)
2. Each strategy card has an **Edit** or **View** button
3. Click the button to open the editor

### Edit Mode (Strategy Stopped)

When the strategy is **stopped**, you can:
- Modify the code
- Use keyboard shortcuts
- Save changes
- Reset to original content

**Available Actions:**
- **Save Changes** (`Ctrl+S`): Saves your modifications
- **Reset**: Discards changes and reverts to last saved version
- **Tab**: Inserts 4 spaces for proper Python indentation
- **Shift+Tab**: Unindents selected lines

### View Mode (Strategy Running)

When the strategy is **running**, the editor is in read-only mode:
- You can view the code
- Syntax highlighting is active
- You cannot make modifications
- Save button is disabled

To edit a running strategy:
1. Stop the strategy first
2. The editor will automatically enable editing
3. Make your changes
4. Save the modifications
5. Restart the strategy

## Keyboard Shortcuts

| Shortcut | Action | Available When |
|----------|--------|----------------|
| `Tab` | Insert 4 spaces | Edit mode |
| `Shift+Tab` | Unindent | Edit mode |
| `Ctrl+S` | Save changes | Edit mode |
| `Ctrl+Z` | Undo | Edit mode |
| `Ctrl+Y` | Redo | Edit mode |
| `F11` | Toggle fullscreen | Always |

## Editor Interface

### Top Bar
- **Back Button**: Return to strategies list
- **Strategy Name**: Displays the current strategy name
- **Status Badge**: Shows if strategy is running (view-only) or stopped (editable)

### File Information Bar
- **File Name**: The Python file being edited
- **Lines**: Total number of lines in the file
- **Size**: File size in KB
- **Modified**: Last modification timestamp in IST

### Action Buttons
- **Save Changes**: Saves modifications (only in edit mode)
- **Reset**: Discards unsaved changes
- **Theme Toggle**: Switch between dark and light themes
- **Fullscreen**: Enter/exit fullscreen mode

## Best Practices

### Before Editing

1. **Stop the Strategy**: Always stop a running strategy before editing
2. **Review Logs**: Check strategy logs for any errors or issues
3. **Backup Important Code**: The editor creates automatic backups (.bak files)

### While Editing

1. **Use Proper Indentation**: Python requires consistent indentation
2. **Test Incrementally**: Make small changes and test
3. **Save Frequently**: Use `Ctrl+S` to save your work
4. **Check Syntax**: The editor highlights syntax errors

### After Editing

1. **Save Changes**: Ensure all modifications are saved
2. **Test the Strategy**: Run the strategy briefly to verify changes
3. **Monitor Logs**: Check logs for any new errors

## Backup System

The editor automatically creates backups:
- Before saving, a `.bak` file is created
- Located in the same directory as the strategy
- Named as `strategy_name.py.bak`

To restore from backup:
1. Stop the strategy
2. Navigate to the strategies/scripts folder
3. Rename the .bak file to .py
4. Upload or refresh the strategy

## Troubleshooting

### Cannot Edit Strategy

**Problem**: Edit button shows "View" and editor is read-only

**Solution**: 
- Stop the strategy first
- Check if strategy process is actually terminated
- Refresh the page

### Changes Not Saving

**Problem**: Save button doesn't work or shows error

**Solution**:
- Ensure strategy is stopped
- Check file permissions
- Verify disk space availability
- Check browser console for errors

### Syntax Highlighting Not Working

**Problem**: Code appears as plain text

**Solution**:
- Clear browser cache
- Ensure JavaScript is enabled
- Check if python-editor.css is loaded
- Try toggling theme

### Lost Changes

**Problem**: Accidentally closed browser with unsaved changes

**Solution**:
- The editor warns before closing with unsaved changes
- Check for .bak files in strategies/scripts folder
- Use browser's restore session feature

## Security Considerations

1. **Process Isolation**: Each strategy runs in a separate process
2. **Edit Protection**: Running strategies cannot be modified
3. **Automatic Backups**: Previous versions are preserved
4. **IST Timestamps**: All times are in Indian Standard Time

## Technical Details

### File Structure
```
static/
├── js/
│   └── codemirror-python-bundle.js  # Editor JavaScript
├── css/
│   └── python-editor.css            # Editor styles
templates/python_strategy/
└── edit.html                        # Editor template
```

### Supported File Types
- Python files (`.py`)
- UTF-8 encoding
- Unix and Windows line endings

### Browser Compatibility
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile browsers (limited functionality)

## Updates and Improvements

The editor is continuously improved. Recent updates include:
- Local hosting of all dependencies (no CDN)
- Enhanced syntax highlighting
- Better mobile responsiveness
- Improved theme support
- Process isolation verification

For feature requests or bug reports, please contact the OpenAlgo development team.