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


def update_timeout_in_files():
    """Update timeout settings in systemd and Nginx files"""

    # Find all OpenAlgo systemd services
    try:
        result = subprocess.run(
            "systemctl list-units --type=service | grep openalgo | awk '{print $1}'",
            shell=True, capture_output=True, text=True
        )
        service_names = [name.replace('.service', '') for name in result.stdout.strip().split('\n') if name.strip()]
    except:
        service_names = []

    if service_names:
        for service_name in service_names:
            service_file = f"/etc/systemd/system/{service_name}.service"
            try:
                with open(service_file, 'r') as f:
                    content = f.read()

                # Update timeout values to 300
                content = re.sub(r'--timeout\s+\d+', '--timeout 300', content)
                content = re.sub(r'--timeout=\d+', '--timeout=300', content)
                if 'TimeoutSec=' in content:
                    content = re.sub(r'TimeoutSec=\d+', 'TimeoutSec=300', content)
                else:
                    content = re.sub(r'(RestartSec=\d+)', r'\1\nTimeoutSec=300', content)

                # Write back with sudo
                subprocess.run(f"echo '{content}' | sudo tee {service_file} > /dev/null",
                             shell=True, capture_output=True)
            except:
                pass

    # Update Nginx configuration
    nginx_files = [
        "/etc/nginx/sites-enabled/openalgo",
        "/etc/nginx/conf.d/openalgo.conf",
        "/etc/nginx/sites-available/openalgo",
    ]

    for config_path in nginx_files:
        try:
            with open(config_path, 'r') as f:
                content = f.read()

            content = re.sub(r'proxy_read_timeout\s+\d+s', 'proxy_read_timeout 300s', content)
            content = re.sub(r'proxy_connect_timeout\s+\d+s', 'proxy_connect_timeout 300s', content)
            content = re.sub(r'proxy_send_timeout\s+\d+s', 'proxy_send_timeout 300s', content)

            subprocess.run(f"echo '{content}' | sudo tee {config_path} > /dev/null",
                         shell=True, capture_output=True)
        except:
            pass

    # Reload systemd
    subprocess.run("sudo systemctl daemon-reload", shell=True, capture_output=True)
    subprocess.run("sudo systemctl reload nginx", shell=True, capture_output=True)

    # Restart services
    for service_name in service_names:
        subprocess.run(f"sudo systemctl restart {service_name}", shell=True, capture_output=True)


def main():
    if sys.platform not in ("linux", "linux2"):
        return 0

    try:
        update_timeout_in_files()
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
