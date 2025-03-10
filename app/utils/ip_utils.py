import httpx
import logging
from fastapi import Request
import socket
from typing import Tuple, Optional
import asyncio

logger = logging.getLogger(__name__)

async def get_ip_addresses(request: Request) -> Tuple[str, str]:
    """
    Get both local and public IP addresses from a request
    
    Args:
        request: FastAPI request object
        
    Returns:
        Tuple containing (local_ip, public_ip)
    """
    # Get local IP from request client
    local_ip = request.client.host if request.client else "127.0.0.1"
    
    # Try to get public IP from headers first (in case of proxies)
    public_ip = None
    
    # Check common proxy headers
    for header in ['X-Forwarded-For', 'X-Real-IP', 'CF-Connecting-IP']:
        if header in request.headers:
            ip_list = request.headers.get(header)
            if ip_list:
                # If multiple IPs in header, take the first one (client's IP)
                if ',' in ip_list:
                    public_ip = ip_list.split(',')[0].strip()
                else:
                    public_ip = ip_list.strip()
                
                # Validate IP format
                if public_ip and is_valid_ip(public_ip):
                    break
    
    # If no valid public IP from headers, try external services
    if not public_ip or public_ip in ['127.0.0.1', 'localhost', '::1']:
        # Try to get public IP from external service
        public_ip = await get_external_ip()
    
    # If still no valid public IP, fall back to local IP
    if not public_ip or not is_valid_ip(public_ip):
        public_ip = local_ip
    
    logger.debug(f"Detected local IP: {local_ip}, public IP: {public_ip}")
    return local_ip, public_ip

def is_valid_ip(ip: str) -> bool:
    """Check if a string is a valid IP address"""
    try:
        # Try to parse as IPv4
        socket.inet_pton(socket.AF_INET, ip)
        return True
    except socket.error:
        try:
            # Try to parse as IPv6
            socket.inet_pton(socket.AF_INET6, ip)
            return True
        except socket.error:
            return False

async def get_external_ip() -> Optional[str]:
    """
    Get public IP address from external service
    
    Returns:
        Public IP address as string or None if failed
    """
    services = [
        "https://api.ipify.org/",
        "https://ifconfig.me/ip",
        "https://icanhazip.com/"
    ]
    
    for service in services:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(service)
                if response.status_code == 200:
                    ip = response.text.strip()
                    if is_valid_ip(ip):
                        logger.debug(f"Got external IP {ip} from {service}")
                        return ip
        except Exception as e:
            logger.debug(f"Failed to get IP from {service}: {e}")
            continue
    
    logger.warning("Failed to get external IP from any service")
    return None
