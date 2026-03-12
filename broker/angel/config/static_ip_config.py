"""
Static IP Configuration Module - Angel One Broker

This module handles Static IP compliance for Angel One broker as per SEBI regulations
and broker API requirements effective April 1, 2026.

Static IP Requirement:
- All broker API connections must originate from registered static IP addresses
- Dynamic IPs are no longer supported
- Registration through Angel Admin portal required

Angel One Documentation:
- https://apiconnect.angel.in/docs#ip-whitelist
- https://admin.angelone.in/settings/api

Author: luckyansari22
Date: March 2026
"""

import os
from typing import Dict, List, Optional, Tuple

from utils.logging import get_logger

logger = get_logger(__name__)


class AngelOneStaticIPConfig:
    """
    Manages Static IP configuration for Angel One broker.

    Features:
    - Register and validate static IPs
    - Fallback IP support for redundancy
    - IP validation against broker settings
    - Angel-specific compliance verification
    """

    # Angel One's IP whitelist management endpoint
    ANGEL_IP_ENDPOINT = "https://admin.angelone.in/settings/api"

    # Angel One API Base URLs
    ANGEL_API_URL = "https://apiconnect.angel.in/rest/secure"
    ANGEL_AUTH_URL = "https://apiconnect.angel.in/rest/auth"

    # Required IP configuration fields
    REQUIRED_CONFIG = ["primary_ip", "client_code", "password"]

    def __init__(self):
        """Initialize Angel One Static IP configuration."""
        self.logger = logger
        self.config = self._load_config()
        self.is_valid = self._validate_config()

    def _load_config(self) -> Dict[str, any]:
        """
        Load Static IP configuration from environment variables.

        Environment Variables Expected:
        - ANGEL_STATIC_IP: Primary static IP address
        - ANGEL_STATIC_IP_BACKUP: Backup/fallback IP (optional)
        - ANGEL_CLIENT_CODE: Angel One client code (e.g., A123456)
        - ANGEL_PASSWORD: API password
        - ANGEL_API_KEY: API key from admin panel
        - ANGEL_IP_ENABLED: Enable/disable static IP requirement (default: True)

        Returns:
            Dictionary with loaded configuration
        """
        config = {
            "primary_ip": os.getenv("ANGEL_STATIC_IP", ""),
            "backup_ip": os.getenv("ANGEL_STATIC_IP_BACKUP", ""),
            "client_code": os.getenv("ANGEL_CLIENT_CODE", ""),
            "password": os.getenv("ANGEL_PASSWORD", ""),
            "api_key": os.getenv("ANGEL_API_KEY", ""),
            "ip_enabled": os.getenv("ANGEL_IP_ENABLED", "true").lower() == "true",
            "auth_token": "",  # Will be populated during JWT authentication
            "refresh_token": "",  # Angel One uses auth tokens only (no refresh)
        }

        self.logger.info(
            f"Loaded Angel One Static IP config - Primary: {config['primary_ip']}, "
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
            self.logger.error("ANGEL_STATIC_IP environment variable not set")
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

        # Check Angel-specific credentials
        if not self.config["client_code"] or not self.config["password"]:
            self.logger.warning("Angel One client_code or password not configured")
            # Don't fail validation, but warn

        self.logger.info("Angel One Static IP configuration validated successfully")
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
        Register a static IP with Angel One broker.

        IMPORTANT: This requires manual action in Angel One's admin portal at:
        https://admin.angelone.in/settings/api

        Steps:
        1. Login to Angel One admin portal
        2. Go to Settings → API Settings → IP Whitelist
        3. Add your static IP address
        4. Save changes

        Args:
            ip_address (str): Static IP to register

        Returns:
            Tuple of (success, message)
        """
        if not self._is_valid_ip(ip_address):
            return False, f"Invalid IP format: {ip_address}"

        message = (
            f"To register static IP {ip_address} with Angel One:\n"
            f"1. Visit: {self.ANGEL_IP_ENDPOINT}\n"
            f"2. Login with your Angel One account (ANT/Angel Trading)\n"
            f"3. Go to Settings → API Settings → IP Whitelist\n"
            f"4. Add IP: {ip_address}\n"
            f"5. Click 'Configure' and confirm\n"
            f"6. Save changes\n"
            f"Registration typically completes within 15 minutes."
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
        return False, f"Request IP {request_ip} not in whitelist. Register in Angel admin: {self.ANGEL_IP_ENDPOINT}"

    def update_api_credentials(self, client_code: str, password: str, api_key: str) -> bool:
        """
        Update Angel One API credentials.

        Args:
            client_code (str): Angel One client code
            password (str): API password
            api_key (str): API key

        Returns:
            Success status
        """
        try:
            self.config["client_code"] = client_code
            self.config["password"] = password
            self.config["api_key"] = api_key
            self.logger.info("Angel One API credentials updated")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update Angel One credentials: {str(e)}")
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
            "client_code": self.config["client_code"][:3] + "***" if self.config["client_code"] else "",
            "ip_enabled": self.config["ip_enabled"],
            "api_key_set": bool(self.config["api_key"]),
            "password_set": bool(self.config["password"]),
            "is_valid": self.is_valid,
            "admin_endpoint": self.ANGEL_IP_ENDPOINT,
            "api_endpoint": self.ANGEL_API_URL,
            "compliance_date": "2026-04-01",
        }

    @staticmethod
    def get_setup_instructions() -> str:
        """
        Get setup instructions for Angel One Static IP compliance.

        Returns:
            Formatted setup instructions
        """
        return """
╔════════════════════════════════════════════════════════════╗
║     ANGEL ONE STATIC IP COMPLIANCE SETUP (Apr 1, 2026)     ║
╚════════════════════════════════════════════════════════════╝

STEP 1: Identify Your Static IP
├─ Contact your ISP to get a static IP
├─ Note down the IP address (format: xxx.xxx.xxx.xxx)
└─ Ensure it remains fixed (contact ISP to pin it)

STEP 2: Set Environment Variables
├─ ANGEL_STATIC_IP=<your_static_ip>
├─ ANGEL_STATIC_IP_BACKUP=<optional_backup_ip>
├─ ANGEL_CLIENT_CODE=<your_client_code>  # e.g., A123456
├─ ANGEL_PASSWORD=<your_api_password>
├─ ANGEL_API_KEY=<your_api_key>
└─ ANGEL_IP_ENABLED=true

STEP 3: Register with Angel One
├─ Go to: https://admin.angelone.in/settings/api
├─ Login with your ANT/Angel Trading account
├─ Navigate to: Settings → API Settings → IP Whitelist
├─ Click "Add IP Address"
├─ Enter your static IP: <your_static_ip>
├─ Click "Configure"
├─ Confirm and Save
└─ Wait for confirmation (usually 15 minutes)

STEP 4: Verify in OpenAlgo
├─ Run: uv run app.py
├─ Check logs for "Angel One Static IP validation enabled"
├─ Test API call from configured IP
└─ Verify no "Request IP not in whitelist" errors

STEP 5: Configure Backup IP (Optional)
├─ Set ANGEL_STATIC_IP_BACKUP with backup IP
├─ Register same way as primary IP
├─ Test failover scenarios
└─ Document for emergency use

IMPORTANT NOTES:
├─ Angel One uses only AUTH TOKENS (no refresh tokens)
├─ Ensure your static IP is truly fixed with ISP
├─ If IP changes, re-register immediately
├─ Emergency contact: support@angelone.in
└─ Need help? → Ask in #algo-regulations Discord channel

TROUBLESHOOTING:
├─ "Request IP not in whitelist" → IP not registered or registered IP different
├─ Auth token expired → Re-authenticate with new credentials
├─ Connection timeout → Check firewall allows port 443
├─ API key invalid → Regenerate in Angel admin panel
└─ Still having issues? → Contact Angel support or ask in Discord
"""


# Instantiate global config for import
angel_static_ip_config = AngelOneStaticIPConfig()
