"""
Static IP Configuration Module - Zerodha Broker

This module handles Static IP compliance for Zerodha broker as per SEBI regulations
and broker API requirements effective April 1, 2026.

Static IP Requirement:
- All broker API connections must originate from registered static IP addresses
- Dynamic IPs are no longer supported
- Registration through broker admin consoles required

Zerodha Documentation:
- https://kite.trade/docs/connect/v3/#ip-whitelist
- https://console.kite.trade/settings/api

Author: luckyansari22
Date: March 2026
"""

import os
from typing import Dict, List, Optional, Tuple

from utils.logging import get_logger

logger = get_logger(__name__)


class ZerodhaStaticIPConfig:
    """
    Manages Static IP configuration for Zerodha broker.

    Features:
    - Register and validate static IPs
    - Fallback IP support for redundancy
    - IP validation against broker settings
    - Compliance verification
    """

    # Zerodha's IP whitelist endpoint
    ZERODHA_IP_ENDPOINT = "https://console.kite.trade/settings/api"

    # Required IP configuration fields
    REQUIRED_CONFIG = ["primary_ip", "api_key", "api_secret"]

    def __init__(self):
        """Initialize Zerodha Static IP configuration."""
        self.logger = logger
        self.config = self._load_config()
        self.is_valid = self._validate_config()

    def _load_config(self) -> Dict[str, any]:
        """
        Load Static IP configuration from environment variables.

        Environment Variables Expected:
        - ZERODHA_STATIC_IP: Primary static IP address
        - ZERODHA_STATIC_IP_BACKUP: Backup/fallback IP (optional)
        - ZERODHA_API_KEY: Broker API key
        - ZERODHA_API_SECRET: Broker API secret
        - ZERODHA_IP_ENABLED: Enable/disable static IP requirement (default: True)

        Returns:
            Dictionary with loaded configuration
        """
        config = {
            "primary_ip": os.getenv("ZERODHA_STATIC_IP", ""),
            "backup_ip": os.getenv("ZERODHA_STATIC_IP_BACKUP", ""),
            "api_key": os.getenv("ZERODHA_API_KEY", os.getenv("BROKER_API_KEY", "")),
            "api_secret": os.getenv("ZERODHA_API_SECRET", os.getenv("BROKER_API_SECRET", "")),
            "ip_enabled": os.getenv("ZERODHA_IP_ENABLED", "true").lower() == "true",
            "session_token": "",  # Will be populated during authentication
            "request_token": "",  # OAuth request token
        }

        self.logger.info(
            f"Loaded Zerodha Static IP config - Primary: {config['primary_ip']}, "
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
            self.logger.error("ZERODHA_STATIC_IP environment variable not set")
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

        self.logger.info("Static IP configuration validated successfully")
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
        Register a static IP with Zerodha broker.

        IMPORTANT: This requires manual action in Zerodha's admin console at:
        https://console.kite.trade/settings/api

        Steps:
        1. Login to Zerodha console
        2. Go to Settings → API → IP Whitelist
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
            f"To register static IP {ip_address} with Zerodha:\n"
            f"1. Visit: {self.ZERODHA_IP_ENDPOINT}\n"
            f"2. Login with your Zerodha account\n"
            f"3. Go to Settings → API → IP Whitelist\n"
            f"4. Add IP: {ip_address}\n"
            f"5. Save and confirm\n"
            f"Registration typically completes within 30 minutes."
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
        return False, f"Request IP {request_ip} not in whitelist. Register in console: {self.ZERODHA_IP_ENDPOINT}"

    def update_api_credentials(self, api_key: str, api_secret: str) -> bool:
        """
        Update API credentials.

        Args:
            api_key (str): New API key
            api_secret (str): New API secret

        Returns:
            Success status
        """
        try:
            self.config["api_key"] = api_key
            self.config["api_secret"] = api_secret
            self.logger.info("API credentials updated")
            return True
        except Exception as e:
            self.logger.error(f"Failed to update API credentials: {str(e)}")
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
            "ip_enabled": self.config["ip_enabled"],
            "api_key_set": bool(self.config["api_key"]),
            "api_secret_set": bool(self.config["api_secret"]),
            "is_valid": self.is_valid,
            "static_ip_endpoint": self.ZERODHA_IP_ENDPOINT,
            "compliance_date": "2026-04-01",
        }

    @staticmethod
    def get_setup_instructions() -> str:
        """
        Get setup instructions for Static IP compliance.

        Returns:
            Formatted setup instructions
        """
        return """
╔════════════════════════════════════════════════════════════╗
║      ZERODHA STATIC IP COMPLIANCE SETUP (Apr 1, 2026)      ║
╚════════════════════════════════════════════════════════════╝

STEP 1: Identify Your Static IP
├─ Contact your ISP to get a static IP
├─ Note down the IP address (format: xxx.xxx.xxx.xxx)
└─ Ensure it remains fixed (contact ISP to pin it)

STEP 2: Set Environment Variables
├─ ZERODHA_STATIC_IP=<your_static_ip>
├─ ZERODHA_STATIC_IP_BACKUP=<optional_backup_ip>
└─ ZERODHA_IP_ENABLED=true

STEP 3: Register with Zerodha
├─ Go to: https://console.kite.trade/settings/api
├─ Login with your account
├─ Navigate to: Settings → API → IP Whitelist
├─ Click "Add IP" and enter your static IP
├─ Click "Save"
└─ Wait for confirmation (usually 30 minutes)

STEP 4: Verify in OpenAlgo
├─ Run: uv run app.py
├─ Check logs for "Static IP validation enabled"
├─ Test API call from configured IP
└─ Verify no "unauthorized IP" errors

STEP 5: Test Fallback (Optional)
├─ Set ZERODHA_STATIC_IP_BACKUP with backup IP
├─ Test failover scenarios
└─ Document backup IP for emergency use

TROUBLESHOOTING:
├─ IP not whitelisted → Check registration status in console
├─ Old sessions failing → Clear browser cache and logout/login
├─ Connection timeout → Verify firewall allows port 443
└─ Need help? → Ask in #algo-regulations Discord channel
"""


# Instantiate global config for import
zerodha_static_ip_config = ZerodhaStaticIPConfig()
