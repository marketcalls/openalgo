#!/usr/bin/env python3
"""
OpenAlgo Systemd Service Timeout Update Migration

Updates systemd service files and Nginx configuration with 300s timeout.
This migration ensures timeout settings persist through upgrades.

It is idempotent - safe to run multiple times.
"""

import subprocess
import sys
import re
import tempfile
import os


def write_file_with_sudo(filepath, content):
    """Safely write file content using sudo via stdin piping"""
    try:
        # Use printf to avoid echo escaping issues and pipe directly to tee
        process = subprocess.Popen(
            ['sudo', 'tee', filepath],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = process.communicate(input=content)
        return process.returncode == 0
    except Exception as e:
        print(f"Failed to write {filepath}: {e}")
        return False


def update_systemd_service(service_file, service_name):
    """Update a single systemd service file with timeout settings"""
    try:
        with open(service_file, 'r') as f:
            content = f.read()

        original_content = content

        # Update Gunicorn timeout in ExecStart
        content = re.sub(r'--timeout\s+\d+', '--timeout 300', content)
        content = re.sub(r'--timeout=\d+', '--timeout=300', content)

        # Update or add TimeoutSec
        if 'TimeoutSec=' in content:
            content = re.sub(r'TimeoutSec=\d+', 'TimeoutSec=300', content)
        else:
            # Add TimeoutSec after [Service] section or after Restart line
            if '\n[Service]' in content or content.startswith('[Service]'):
                # Find first non-empty line after [Service]
                lines = content.split('\n')
                insert_index = None
                for i, line in enumerate(lines):
                    if '[Service]' in line:
                        # Insert after [Service] or after the next non-comment line
                        insert_index = i + 1
                        while insert_index < len(lines) and (not lines[insert_index].strip() or lines[insert_index].strip().startswith('#')):
                            insert_index += 1
                        break

                if insert_index:
                    lines.insert(insert_index, 'TimeoutSec=300')
                    content = '\n'.join(lines)
            else:
                # Fallback: add before [Install] section
                if '\n[Install]' in content:
                    content = content.replace('\n[Install]', '\nTimeoutSec=300\n\n[Install]')
                else:
                    # Last resort: append at end
                    content = content.rstrip() + '\nTimeoutSec=300\n'

        if content != original_content:
            return write_file_with_sudo(service_file, content)
        return True

    except Exception as e:
        print(f"Error updating {service_name}: {e}")
        return False


def update_nginx_config(config_path):
    """Update a single Nginx configuration file with timeout settings"""
    try:
        with open(config_path, 'r') as f:
            content = f.read()

        original_content = content

        # Update proxy timeouts
        content = re.sub(r'proxy_read_timeout\s+\d+s', 'proxy_read_timeout 300s', content)
        content = re.sub(r'proxy_connect_timeout\s+\d+s', 'proxy_connect_timeout 300s', content)
        content = re.sub(r'proxy_send_timeout\s+\d+s', 'proxy_send_timeout 300s', content)

        if content != original_content:
            return write_file_with_sudo(config_path, content)
        return True

    except FileNotFoundError:
        # File doesn't exist, skip silently
        return True
    except Exception as e:
        print(f"Error updating {config_path}: {e}")
        return False


def update_timeout_in_files():
    """Update timeout settings in all systemd and Nginx files"""

    # Find all OpenAlgo systemd services
    service_names = []
    try:
        result = subprocess.run(
            "systemctl list-units --type=service 2>/dev/null | grep openalgo | awk '{print $1}'",
            shell=True, capture_output=True, text=True, timeout=10
        )
        service_names = [name.replace('.service', '') for name in result.stdout.strip().split('\n') if name.strip()]
    except subprocess.TimeoutExpired:
        print("systemctl list-units timed out")
        return False
    except Exception as e:
        print(f"Error listing systemd services: {e}")
        return False

    # Update systemd services
    if service_names:
        for service_name in service_names:
            service_file = f"/etc/systemd/system/{service_name}.service"
            try:
                if os.path.exists(service_file):
                    update_systemd_service(service_file, service_name)
            except Exception as e:
                print(f"Error processing {service_name}: {e}")

    # Update Nginx configuration
    nginx_files = [
        "/etc/nginx/sites-enabled/openalgo",
        "/etc/nginx/conf.d/openalgo.conf",
        "/etc/nginx/sites-available/openalgo",
    ]

    for config_path in nginx_files:
        try:
            if os.path.exists(config_path):
                update_nginx_config(config_path)
        except Exception as e:
            print(f"Error processing {config_path}: {e}")

    # Reload systemd daemon
    try:
        subprocess.run(['sudo', 'systemctl', 'daemon-reload'],
                      capture_output=True, timeout=10, check=True)
    except Exception as e:
        print(f"Warning: Failed to reload systemd daemon: {e}")

    # Reload Nginx
    try:
        subprocess.run(['sudo', 'systemctl', 'reload', 'nginx'],
                      capture_output=True, timeout=10)
    except Exception as e:
        # Nginx may not be installed, don't fail
        pass

    # Restart services
    for service_name in service_names:
        try:
            subprocess.run(['sudo', 'systemctl', 'restart', service_name],
                          capture_output=True, timeout=30, check=True)
        except Exception as e:
            print(f"Warning: Failed to restart {service_name}: {e}")

    return True


def main():
    if sys.platform not in ("linux", "linux2"):
        return 0

    try:
        success = update_timeout_in_files()
        return 0 if success else 1
    except Exception as e:
        print(f"Migration error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
