# Python Strategy Management System - Changelog

All notable changes to the Python Strategy Management System will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.1] - 2024-09-07

### Security
- Moved encryption key from `db/strategy_encryption.key` to `keys/.encryption_key` for better isolation
- Added dedicated `keys/` folder with `.gitignore` to prevent accidental commits
- Enhanced UI security by showing secure variable values as bullets (••••••••)

### Fixed
- Secure environment variables not being retained when closing/reopening the modal
- Secure variables being overwritten with empty values on save
- AttributeError when handling both subprocess.Popen and psutil.Process objects

### Changed
- Updated `save_env_variables()` to merge secure variables instead of replacing them
- Modified UI to preserve existing secure variables and only send modified ones
- Enhanced process handling to support both subprocess and psutil process types

## [1.1.0] - 2024-09-07

### Added
- Master contract dependency checking before strategy start
- Persistent state management across application restarts
- Automatic strategy restoration after login
- Error state handling with recovery options
- Visual indicators for master contract status (Ready/Waiting/Error)
- "Check & Start" button for manual contract verification
- Safety restrictions preventing modifications while strategies are running

### Changed
- Strategies now wait for master contracts to be downloaded before starting
- Enhanced state restoration process to handle various scenarios
- Improved error messages and user feedback

### Fixed
- Strategies failing to start without master contracts
- State loss on application restart
- Process orphaning issues

## [1.0.0] - 2024-09-06

### Initial Release
- Process isolation for each strategy
- Automated scheduling with IST timezone support
- Built-in code editor with syntax highlighting
- Real-time logging system
- Export/Import functionality
- Environment variables support (regular and secure)
- CSRF protection
- Cross-platform support (Windows, Linux, macOS)
- Web-based strategy management interface

---

*For the complete documentation, see the [README](README.md)*