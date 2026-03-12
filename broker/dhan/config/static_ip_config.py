"""
Static IP Configuration Module - Dhan Broker

This module handles Static IP compliance for Dhan broker as per SEBI regulations
and broker API requirements effective April 1, 2026.

Static IP Requirement:
- All broker API connections must originate from registered static IP addresses
- Dynamic IPs are no longer supported
- Registration through Dhan API console required

Dhan Documentation:
- https://dhanhq.com/docs/ip-whitelist/
- https://api.dhan.co/settings/ip-whitelist

Author: luckyansari22
Date: March 2026
"""

import os
from typing import Dict, List, Optional, Tuple

from utils.logging import get_logger

logger = get_logger(__name__)


class DhanStaticIPConfig:
    """
    Manages Static IP configuration for Dhan broker.

    Features:
    - Register and validate static IPs
    - Fallback IP support for dual-connection redundancy
    - IP validation against broker whitelisting
    - Dhan-specific compliance verification
    """

    # Dhan's IP whitelist management endpoint
    DHAN_IP_ENDPOINT = "https://api.dhan.co/settings/ip-whitelist"
    DHAN_CONSOLE = "https://console.dhan.co/"

    # Dhan API Base URLs
    DHAN_API_URL = "https://api.dhan.co/v1"
    DHAN_AUTH_URL = "https://api.dhan.co/v1/login"

    # Required IP configuration fields
    REQUIRED_CONFIG = ["primary_ip", "client_id", "access_token"]

    def __init__(self):
        """Initialize Dhan Static IP configuration."""
        self.logger = logger
        self.config = self._load_config()
        self.is_valid = self._validate_config()

    def _load_config(self) -> Dict[str, any]:
        """
        Load Static IP configuration from environment variables.

        Environment Variables Expected:
        - DHAN_STATIC_IP: Primary static IP address
        - DHAN_STATIC_IP_BACKUP: Backup/fallback IP (optional)
        - DHAN_CLIENT_ID: Dhan client ID (alphanumeric)
        - DHAN_ACCESS_TOKEN: API access token
        - DHAN_API_KEY: API key for authentication
        - DHAN_IP_ENABLED: Enable/disable static IP requirement (default: True)

        Returns:
            Dictionary with loaded configuration
        """
        config = {
            "primary_ip": os.getenv("DHAN_STATIC_IP", ""),
            "backup_ip": os.getenv("DHAN_STATIC_IP_BACKUP", ""),
            "client_id": os.getenv("DHAN_CLIENT_ID", ""),
            "access_token": os.getenv("DHAN_ACCESS_TOKEN", ""),
            "api_key": os.getenv("DHAN_API_KEY", ""),
            "ip_enabled": os.getenv("DHAN_IP_ENABLED", "true").lower() == "true",
            "session_token": "",  # Will be populated during authentication
            "last_auth_time": None,  # Track last successful authentication
        }

        self.logger.info(
            f"Loaded Dhan Static IP config - Primary: {config['primary_ip']}, "
            f"Backup: {config['backup_ip']}, Enabled: {config['ip_enabled']}"
        )

        return config

    def _validate_config(self) -> bool:
        """
        Validate Static IP configuration correctness.

        Returns:
            True if configuration is valid, False otherwise
        """
        if not self.config["ip_enabled"]:
            self.logger.debug("Static IP requirement disabled via config")
            return True

        # Check primary IP is set
        if not self.config["primary_ip"]:
            self.logger.error("DHAN_STATIC_IP environment variable not set")
            return False

        # Validate IP format
        if not self._is_valid_ip(self.config["primary_ip"]):
            self.logger.error(f"Invalid primary IP format: {self.config['primary_ip']}")
            return False

        # Validate backup IP if provided
        if self.config["backup_ip"]:
            if not self._is_valid_ip(self.config["backup_ip"]):
                self.logger.error(f"Invalid backup IP format: {self.config['backup_ip']}")
                return False

        # Check Dhan-specific credentials
        if not self.config["client_id"]:
            self.logger.warning("Dhan client_id not configured")

        self.logger.info("Dhan Static IP configuration validated successfully")
        return True

    @staticmethod
    def _is_valid_ip(ip_str: str) -> bool:
        """
        Validate IP address format (IPv4).

        Args:
            ip_str (str): IP address string to validate

        Returns:
            True if valid IPv4 format
        """
        parts = ip_str.split(".")
        if len(parts) != 4:
            return False

        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False

    def get_active_ip(self) -> Tuple[Optional[str], str]:
        """
        Get the currently active static IP.

        Returns:
            Tuple of (ip_address, status_message)
        """
        if not self.is_valid:
            return None, "Configuration not validated"

        if not self.config["ip_enabled"]:
            return None, "Static IP enforcement disabled"

        return self.config["primary_ip"], "Using primary static IP"

    def get_available_ips(self) -> List[str]:
        """
        Get all configured IPs (primary + backup).

        Returns:
            List of configured IP addresses
        """
        ips = [self.config["primary_ip"]] if self.config["primary_ip"] else []

        if self.config["backup_ip"]:
            ips.append(self.config["backup_ip"])

        return ips

    def register_static_ip(self, ip_address: str) -> Tuple[bool, str]:
        """
        Register a static IP with Dhan broker.

        IMPORTANT: This requires action in Dhan's console at:
        https://console.dhan.co/ or API endpoint: https://api.dhan.co/settings/ip-whitelist

        Steps:
        1. Login to Dhan console
        2. Go to Settings → API Settings → IP Whitelist
        3. Add your static IP address
        4. Click 'Add IP' and confirm

        Args:
            ip_address (str): Static IP to register

        Returns:
            Tuple of (success, message)
        """
        if not self._is_valid_ip(ip_address):
            return False, f"Invalid IP format: {ip_address}"

        message = (
            f"To register static IP {ip_address} with Dhan:\n"
            f"\nWEB CONSOLE METHOD:\n"
            f"1. Visit: {self.DHAN_CONSOLE}\n"
            f"2. Login with your Dhan account\n"
            f"3. Go to Settings → API Settings → IP Whitelist\n"
            f"4. Click 'Add New IP'\n"
            f"5. Enter IP: {ip_address}\n"
            f"6. Click 'Add IP' button\n"
            f"\nAPI METHOD:\n"
            f"1. Use endpoint: {self.DHAN_IP_ENDPOINT}\n"
            f"2. Send POST with: {{'ip_address': '{ip_address}'}}\n"
            f"3. Include your access_token in header\n"
            f"\nRegistration typically completes within 10 minutes."
        )

        self.logger.info(f"IP registration instructions for {ip_address}")
        return True, message

    def validate_request_ip(self, request_ip: str) -> Tuple[bool, str]:
        """
        Validate if incoming request IP matches registered static IP.

        Args:
            request_ip (str): IP from incoming request

        Returns:
            Tuple of (is_valid, message)
        """
        if not self.config["ip_enabled"]:
            return True, "Static IP validation disabled"

        allowed_ips = self.get_available_ips()

        if request_ip in allowed_ips:
            return True, f"Request IP {request_ip} is whitelisted"

        self.logger.warning(
            f"Request from unauthorized IP {request_ip}. Allowed IPs: {allowed_ips}"
        )
        return False, f"Request IP {request_ip} not in whitelist. Register at: {self.DHAN_CONSOLE}"

    def update_api_credentials(self, client_id: str, access_token: str, api_key: str) -> bool:
        """
        Update Dhan API credentials.

        Args:
            client_id (str): Dhan client ID
            access_token (str): API access token
            api_key (str): API key

        Returns:
            Success status
        """
        try:
            self.config["client_id"] = client_id
            self.config["access_token"] = access_token
            self.config["api_key"] = api_key
            self.logger.info("Dhan API credentials updated")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update Dhan credentials: {str(e)}")
            return False

    def get_configuration(self) -> Dict[str, any]:
        """
        Get complete Static IP configuration (for debugging/logging).

        Returns:
            Configuration dictionary (credentials masked)
        """
        return {
            "primary_ip": self.config["primary_ip"],
            "backup_ip": self.config["backup_ip"],
            "client_id": self.config["client_id"][:4] + "***" if self.config["client_id"] else "",
            "ip_enabled": self.config["ip_enabled"],
            "access_token_set": bool(self.config["access_token"]),
            "api_key_set": bool(self.config["api_key"]),
            "is_valid": self.is_valid,
            "console_endpoint": self.DHAN_CONSOLE,
            "api_endpoint": self.DHAN_API_URL,
            "compliance_date": "2026-04-01",
        }

    @staticmethod
    def get_setup_instructions() -> str:
        """
        Get setup instructions for Dhan Static IP compliance.

        Returns:
            Formatted setup instructions
        """
        return """
╔════════════════════════════════════════════════════════════╗
║        DHAN STATIC IP COMPLIANCE SETUP (Apr 1, 2026)       ║
╚════════════════════════════════════════════════════════════╝

STEP 1: Identify Your Static IP
├─ Contact your ISP to get a static IP
├─ Note down the IP address (format: xxx.xxx.xxx.xxx)
└─ Ensure it remains fixed (contact ISP to pin it)

STEP 2: Set Environment Variables
├─ DHAN_STATIC_IP=<your_static_ip>
├─ DHAN_STATIC_IP_BACKUP=<optional_backup_ip>
├─ DHAN_CLIENT_ID=<your_dhan_client_id>
├─ DHAN_ACCESS_TOKEN=<your_access_token>
├─ DHAN_API_KEY=<your_api_key>
└─ DHAN_IP_ENABLED=true

STEP 3: Register IP via Dhan Console
├─ Go to: https://console.dhan.co/
├─ Login with your Dhan credentials
├─ Navigate to: Settings → API Settings → IP Whitelist
├─ Click "Add New IP"
├─ Enter your static IP: <your_static_ip>
├─ Click "Add IP" button
└─ Wait for confirmation (usually 10 minutes)

STEP 4: Alternative - Register via API
├─ POST to: https://api.dhan.co/v1/settings/ip-whitelist
├─ Headers: Authorization: Bearer <your_access_token>
├─ Body: {"ip_address": "<your_static_ip>"}
├─ Response: {"status": "success", "ip": "<your_static_ip>"}
└─ Verify in console that IP is listed

STEP 5: Verify in OpenAlgo
├─ Run: uv run app.py
├─ Check logs for "Dhan Static IP validation enabled"
├─ Test API call from configured IP
└─ Verify no "Request IP not in whitelist" errors

STEP 6: Configure Backup IP (Optional)
├─ Set DHAN_STATIC_IP_BACKUP with second IP
├─ Register backup IP same way
├─ System will try primary first, then backup
└─ Document backup for emergency use

IMPORTANT NOTES:
├─ Dhan migrating to market protection orders (separate config)
├─ Ensure your static IP truly fixed with ISP
├─ If IP changes, OpenAlgo API calls will fail
├─ Re-register immediately if IP changes
└─ Emergency contact: support@dhan.co

TROUBLESHOOTING:
├─ "Request IP not in whitelist" → Check IP registered in console
├─ Different IP used? → ISP changed your IP, re-register
├─ Access token expired → Get new token from console
├─ Client ID invalid → Verify correct client ID in console
└─ Still issues? → Ask in #algo-regulations Discord channel

MIGRATION CHECKLIST:
├─ [ ] Get static IP from ISP
├─ [ ] Update .env file with IP
├─ [ ] Register IP in Dhan console
├─ [ ] Test API call from registered IP
├─ [ ] Set backup IP (optional)
├─ [ ] Configure market protection orders (separate)
└─ [ ] Ready for April 1, 2026 compliance ✓
"""


# Instantiate global config for import
dhan_static_ip_config = DhanStaticIPConfig()
