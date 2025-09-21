# Python Strategy Management System - Complete Implementation Guide

## Overview

The Python Strategy Management System is a comprehensive web-based platform for managing, executing, and scheduling Python trading strategies within OpenAlgo. It provides complete process isolation, cross-platform compatibility, and a user-friendly interface.

## Architecture

### Core Components

1. **Backend (Flask Blueprint)**
   - Location: `blueprints/python_strategy.py`
   - Route prefix: `/python`
   - Handles strategy lifecycle management
   - Process isolation using subprocess
   - Scheduling with APScheduler
   - IST timezone support

2. **Frontend Templates**
   - `templates/python_strategy/index.html` - Main dashboard
   - `templates/python_strategy/new.html` - Strategy upload
   - `templates/python_strategy/edit.html` - Code editor
   - `templates/python_strategy/logs.html` - Log viewer

3. **Static Assets**
   - `static/js/python-editor-simple.js` - Code editor
   - `static/css/python-editor-simple.css` - Editor styles
   - No external CDN dependencies

## Features

### 1. Strategy Management

#### Upload Strategy
- Navigate to `/python`
- Click "Upload New Strategy"
- Select Python file
- Provide strategy name
- File is saved to `strategies/scripts/`

#### Start/Stop Strategy
- Each strategy runs in isolated process
- Click "Start" to launch strategy
- Click "Stop" to terminate process
- Process status updated in real-time

#### Edit Strategy
- **Running Strategy**: View-only mode
- **Stopped Strategy**: Full edit capabilities
- Line numbers display
- Tab/Shift+Tab for indentation
- Automatic backup on save
- Syntax preservation (no highlighting to avoid rendering issues)

#### Delete Strategy
- Only available when strategy is stopped
- Confirmation modal prevents accidental deletion
- Removes file and configuration

### 2. Scheduling System

#### How Scheduling Works
- Uses APScheduler with BackgroundScheduler
- All times in IST (Indian Standard Time)
- Cron-based scheduling for flexibility
- Automatic start/stop at specified times

#### Schedule Configuration
- **Start Time**: When to start strategy (IST)
- **Stop Time**: Optional, when to stop (IST)
- **Days**: Select which days to run
  - Monday through Sunday
  - Must select at least one day

#### What Happens Without Scheduling
If a strategy is not scheduled:
- It remains in manual mode
- Must be started/stopped manually
- No automatic execution
- Useful for testing or on-demand trading

### 3. Process Isolation

#### Windows Implementation
```python
subprocess.CREATE_NEW_PROCESS_GROUP  # Separate process group
STARTF_USESHOWWINDOW                # No console window
```

#### Unix/Linux/macOS Implementation
```python
start_new_session = True  # New session
preexec_fn = os.setsid   # Session ID for control
```

#### Benefits
- Strategy crashes don't affect main app
- Clean process termination
- Resource isolation
- Multiple strategies run independently

### 4. Logging System

#### Log Files
- Location: `log/strategies/`
- Format: `{strategy_id}_{timestamp}_IST.log`
- Real-time output capture
- IST timestamps throughout

#### Log Viewer
- Navigate to strategy logs
- View latest log by default
- Auto-scroll option
- File size and line count display

### 5. User Interface

#### Modal Dialogs (No Alerts)
All confirmations use DaisyUI modals:
- **Delete Strategy**: Confirmation before deletion
- **Unschedule Strategy**: Confirm schedule removal
- **Reset Changes**: Confirm discarding edits
- No browser alerts or confirms

#### Toast Notifications
- Success messages (green)
- Error messages (red)
- Info messages (blue)
- Auto-dismiss after 3 seconds

#### Status Indicators
- **Running**: Green badge with pulse animation
- **Stopped**: Gray badge
- **Scheduled**: Clock icon with schedule info
- **Current Time**: IST display in header

## File Structure

```
openalgo/
├── blueprints/
│   └── python_strategy.py          # Core backend logic
├── templates/python_strategy/
│   ├── index.html                  # Dashboard
│   ├── new.html                    # Upload form
│   ├── edit.html                   # Code editor
│   └── logs.html                   # Log viewer
├── static/
│   ├── js/
│   │   └── python-editor-simple.js # Editor implementation
│   └── css/
│       └── python-editor-simple.css # Editor styles
├── strategies/
│   ├── scripts/                    # User strategy files
│   │   └── .gitignore              # Ignores *.py
│   ├── strategy_configs.json       # Configuration storage
│   └── .gitignore                  # Ignores configs
└── log/strategies/
    ├── *.log                       # Strategy logs
    └── .gitignore                  # Ignores logs
```

## Configuration Storage

### strategy_configs.json
```json
{
  "strategy_id": {
    "name": "Strategy Name",
    "file_path": "strategies/scripts/file.py",
    "is_running": false,
    "is_scheduled": false,
    "schedule_start": "09:15",
    "schedule_stop": "15:30",
    "schedule_days": ["mon", "tue", "wed", "thu", "fri"],
    "last_started": "2024-01-01T09:15:00+05:30",
    "last_stopped": "2024-01-01T15:30:00+05:30",
    "pid": null
  }
}
```

## API Endpoints

### GET Routes
- `/python` - Main dashboard
- `/python/new` - Upload form
- `/python/edit/<strategy_id>` - Edit/view strategy
- `/python/logs/<strategy_id>` - View logs
- `/python/status` - System status (JSON)

### POST Routes
- `/python/upload` - Upload new strategy
- `/python/start/<strategy_id>` - Start strategy
- `/python/stop/<strategy_id>` - Stop strategy
- `/python/delete/<strategy_id>` - Delete strategy
- `/python/schedule/<strategy_id>` - Set schedule
- `/python/unschedule/<strategy_id>` - Remove schedule
- `/python/save/<strategy_id>` - Save edited code

## Security Considerations

### Process Isolation
- Each strategy runs in separate process
- No shared memory or resources
- Clean termination on shutdown

### File Safety
- Automatic backups before save
- .gitignore files prevent accidental commits
- UTF-8 encoding for cross-platform compatibility

### Access Control
- Running strategies cannot be edited
- Delete only when stopped
- Schedule validation before save

## Timezone Handling

### IST Throughout
- All times displayed in IST
- Scheduling in IST
- Logs timestamped in IST
- pytz.timezone('Asia/Kolkata')

### Time Display Format
- Dashboard: `HH:MM:SS IST`
- Logs: `YYYY-MM-DD HH:MM:SS IST`
- Schedule: `HH:MM IST`

## Error Handling

### Strategy Errors
- Captured in log files
- Process continues running
- Main app unaffected

### System Errors
- Toast notifications for user
- Detailed logging for debugging
- Graceful degradation

## Testing

### Manual Testing
1. Upload a test strategy
2. Start and verify process creation
3. Stop and verify termination
4. Edit when stopped (should work)
5. View when running (read-only)
6. Schedule and verify execution
7. Delete after stopping

### Test Scripts
- `test/test_python_editor.py` - Editor functionality
- `test/test_simple_editor.html` - Editor UI test

## Troubleshooting

### Strategy Won't Start
- Check file exists
- Verify Python syntax
- Check logs for errors
- Ensure not already running

### Editor Issues
- Clear browser cache
- Check JavaScript console
- Verify file permissions
- Try different browser

### Scheduling Not Working
- Verify IST time is correct
- Check at least one day selected
- Ensure strategy file exists
- Check scheduler is running

### Process Won't Stop
- Check process ID in configs
- Use system task manager
- Restart OpenAlgo if needed

## Best Practices

### Strategy Development
1. Test locally first
2. Use proper error handling
3. Include logging statements
4. Handle graceful shutdown

### Scheduling
1. Allow buffer time between start/stop
2. Consider market hours
3. Test schedule with short intervals
4. Monitor logs regularly

### System Maintenance
1. Regular log cleanup
2. Backup important strategies
3. Monitor resource usage
4. Update configurations carefully

## Platform-Specific Notes

### Windows
- Uses CREATE_NEW_PROCESS_GROUP
- taskkill for force termination
- Handles paths with backslashes

### Linux/macOS
- Uses process sessions (setsid)
- SIGTERM/SIGKILL for termination
- Standard Unix process management

## Updates and Improvements

### Recent Changes
- Replaced alerts with modal dialogs
- Fixed editor text rendering
- Added IST timezone support
- Improved process isolation
- Enhanced cross-platform compatibility

### Future Enhancements
- Strategy performance metrics
- Multiple strategy templates
- Advanced scheduling options
- Real-time strategy monitoring
- Strategy backtesting integration

## Support

For issues or questions:
1. Check logs in `log/strategies/`
2. Review browser console for errors
3. Verify Python environment
4. Contact OpenAlgo support team

---

*This implementation provides a robust, user-friendly system for managing Python trading strategies with proper isolation, scheduling, and cross-platform support.*