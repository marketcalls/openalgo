"""
Minimal implementation of nkeys functionality for Groww WebSocket
Based on NATS nkeys specification using cryptography library for Ed25519
"""

import base64
import os
from typing import Tuple, Optional
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

# NATS nkeys prefix bytes
PREFIX_BYTE_SEED = 18 << 3  # Base32-encodes to 'S...'
PREFIX_BYTE_PRIVATE = 15 << 3  # Base32-encodes to 'P...'
PREFIX_BYTE_USER = 20 << 3  # Base32-encodes to 'U...'

# CRC16 table for checksum
CRC16TAB = [
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50a5, 0x60c6, 0x70e7,
    0x8108, 0x9129, 0xa14a, 0xb16b, 0xc18c, 0xd1ad, 0xe1ce, 0xf1ef,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52b5, 0x4294, 0x72f7, 0x62d6,
    0x9339, 0x8318, 0xb37b, 0xa35a, 0xd3bd, 0xc39c, 0xf3ff, 0xe3de,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64e6, 0x74c7, 0x44a4, 0x5485,
    0xa56a, 0xb54b, 0x8528, 0x9509, 0xe5ee, 0xf5cf, 0xc5ac, 0xd58d,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76d7, 0x66f6, 0x5695, 0x46b4,
    0xb75b, 0xa77a, 0x9719, 0x8738, 0xf7df, 0xe7fe, 0xd79d, 0xc7bc,
    0x48c4, 0x58e5, 0x6886, 0x78a7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xc9cc, 0xd9ed, 0xe98e, 0xf9af, 0x8948, 0x9969, 0xa90a, 0xb92b,
    0x5af5, 0x4ad4, 0x7ab7, 0x6a96, 0x1a71, 0x0a50, 0x3a33, 0x2a12,
    0xdbfd, 0xcbdc, 0xfbbf, 0xeb9e, 0x9b79, 0x8b58, 0xbb3b, 0xab1a,
    0x6ca6, 0x7c87, 0x4ce4, 0x5cc5, 0x2c22, 0x3c03, 0x0c60, 0x1c41,
    0xedae, 0xfd8f, 0xcdec, 0xddcd, 0xad2a, 0xbd0b, 0x8d68, 0x9d49,
    0x7e97, 0x6eb6, 0x5ed5, 0x4ef4, 0x3e13, 0x2e32, 0x1e51, 0x0e70,
    0xff9f, 0xefbe, 0xdfdd, 0xcffc, 0xbf1b, 0xaf3a, 0x9f59, 0x8f78,
    0x9188, 0x81a9, 0xb1ca, 0xa1eb, 0xd10c, 0xc12d, 0xf14e, 0xe16f,
    0x1080, 0x00a1, 0x30c2, 0x20e3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83b9, 0x9398, 0xa3fb, 0xb3da, 0xc33d, 0xd31c, 0xe37f, 0xf35e,
    0x02b1, 0x1290, 0x22f3, 0x32d2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xb5ea, 0xa5cb, 0x95a8, 0x8589, 0xf56e, 0xe54f, 0xd52c, 0xc50d,
    0x34e2, 0x24c3, 0x14a0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xa7db, 0xb7fa, 0x8799, 0x97b8, 0xe75f, 0xf77e, 0xc71d, 0xd73c,
    0x26d3, 0x36f2, 0x0691, 0x16b0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xd94c, 0xc96d, 0xf90e, 0xe92f, 0x99c8, 0x89e9, 0xb98a, 0xa9ab,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18c0, 0x08e1, 0x3882, 0x28a3,
    0xcb7d, 0xdb5c, 0xeb3f, 0xfb1e, 0x8bf9, 0x9bd8, 0xabbb, 0xbb9a,
    0x4a75, 0x5a54, 0x6a37, 0x7a16, 0x0af1, 0x1ad0, 0x2ab3, 0x3a92,
    0xfd2e, 0xed0f, 0xdd6c, 0xcd4d, 0xbdaa, 0xad8b, 0x9de8, 0x8dc9,
    0x7c26, 0x6c07, 0x5c64, 0x4c45, 0x3ca2, 0x2c83, 0x1ce0, 0x0cc1,
    0xef1f, 0xff3e, 0xcf5d, 0xdf7c, 0xaf9b, 0xbfba, 0x8fd9, 0x9ff8,
    0x6e17, 0x7e36, 0x4e55, 0x5e74, 0x2e93, 0x3eb2, 0x0ed1, 0x1ef0,
]


def crc16(data: bytes) -> int:
    """Calculate CRC16 checksum"""
    crc = 0
    for c in data:
        crc = ((crc << 8) & 0xffff) ^ CRC16TAB[((crc >> 8) ^ c) & 0x00FF]
    return crc


def crc16_checksum(data: bytes) -> bytes:
    """Calculate CRC16 checksum and return as bytes"""
    crc = crc16(data)
    return crc.to_bytes(2, byteorder='little')


def encode_seed(src: bytes, prefix: int) -> bytes:
    """
    Encode a seed with NATS nkey format
    
    Args:
        src: A 32-byte seed
        prefix: Prefix byte (e.g., PREFIX_BYTE_USER)
    
    Returns:
        Base32-encoded nkey seed
    """
    if len(src) != 32:
        raise ValueError("Seed must be 32 bytes")
    
    # First byte: PREFIX_BYTE_SEED with first 3 bits of prefix
    first_byte = PREFIX_BYTE_SEED | (prefix >> 5)
    
    # Second byte: Last 5 bits of prefix in first 5 bits
    second_byte = (31 & prefix) << 3
    
    header = bytes([first_byte, second_byte])
    checksum = crc16_checksum(header + src)
    final_bytes = header + src + checksum
    
    return base64.b32encode(final_bytes).rstrip(b'=')


def decode_seed(seed: bytes) -> Tuple[int, bytes]:
    """
    Decode a NATS nkey seed
    
    Args:
        seed: Base32-encoded seed
    
    Returns:
        Tuple of (prefix, raw_seed)
    """
    # Add padding if needed
    padding = b'=' * ((-len(seed)) % 8)
    base32_decoded = base64.b32decode(seed + padding)
    
    # Remove checksum (last 2 bytes)
    raw = base32_decoded[:-2]
    
    if len(raw) < 34:  # 2 header bytes + 32 seed bytes
        raise ValueError("Invalid seed length")
    
    # Extract prefix from header
    b1 = raw[0] & 248  # First 5 bits
    b2 = ((raw[0] & 7) << 5) | ((raw[1] & 248) >> 3)  # Last 3 + first 5
    
    if b1 != PREFIX_BYTE_SEED:
        raise ValueError("Invalid seed prefix")
    
    return b2, raw[2:]


class Ed25519SigningKey:
    """Ed25519 signing key implementation using cryptography library"""
    
    def __init__(self, seed: bytes):
        """Initialize with 32-byte seed"""
        if len(seed) != 32:
            raise ValueError("Seed must be 32 bytes")
        self.seed = seed
        # Create Ed25519 private key from seed
        self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(seed)
        self._public_key = self._private_key.public_key()
        
    def sign(self, message: bytes) -> 'SignedMessage':
        """Sign a message using Ed25519"""
        signature = self._private_key.sign(message)
        return SignedMessage(signature)
    
    @property
    def verify_key(self) -> 'Ed25519VerifyKey':
        """Get the verify key (public key)"""
        # Get raw public key bytes (32 bytes)
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return Ed25519VerifyKey(public_bytes)
    
    @property
    def private_bytes(self) -> bytes:
        """Get the raw private key bytes"""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )


class SignedMessage:
    """Container for signed message"""
    
    def __init__(self, signature: bytes):
        self.signature = signature


class Ed25519VerifyKey:
    """Ed25519 verify key (public key) implementation"""
    
    def __init__(self, key_bytes: bytes):
        if len(key_bytes) != 32:
            raise ValueError("Public key must be 32 bytes")
        self.key_bytes = key_bytes
    
    def __bytes__(self):
        return self.key_bytes


class GrowwKeyPair:
    """Minimal KeyPair implementation for NATS nkeys"""
    
    def __init__(self, seed: bytes = None):
        """
        Initialize a keypair
        
        Args:
            seed: Optional 32-byte seed. If not provided, generates random seed.
        """
        if seed is None:
            seed = os.urandom(32)
        elif len(seed) != 32:
            raise ValueError("Seed must be 32 bytes")
        
        self._raw_seed = seed
        self._signing_key = Ed25519SigningKey(seed)
        self._encoded_seed = encode_seed(seed, PREFIX_BYTE_USER)
        self._public_key = None
        self._private_key = None
    
    @property
    def seed(self) -> bytes:
        """Get the encoded seed"""
        return self._encoded_seed
    
    @property
    def public_key(self) -> bytes:
        """Get the encoded public key"""
        if self._public_key is None:
            # Get public key bytes
            verify_key = self._signing_key.verify_key
            src = bytearray(bytes(verify_key))
            
            # Add prefix
            src.insert(0, PREFIX_BYTE_USER)
            
            # Add checksum
            checksum = crc16_checksum(bytes(src))
            src.extend(checksum)
            
            # Encode to base32
            self._public_key = base64.b32encode(bytes(src)).rstrip(b'=')
        
        return self._public_key
    
    @property
    def private_key(self) -> bytes:
        """Get the encoded private key"""
        if self._private_key is None:
            # Get private key bytes (64 bytes for Ed25519)
            src = bytearray(self._signing_key.private_bytes)
            
            # Add prefix
            src.insert(0, PREFIX_BYTE_PRIVATE)
            
            # Add checksum
            checksum = crc16_checksum(bytes(src))
            src.extend(checksum)
            
            # Encode to base32
            self._private_key = base64.b32encode(bytes(src)).rstrip(b'=')
        
        return self._private_key
    
    def sign(self, message: bytes) -> bytes:
        """Sign a message"""
        signed = self._signing_key.sign(message)
        return signed.signature
    
    @property
    def signing_key(self):
        """Access to the underlying signing key"""
        return self._signing_key


def generate_keypair() -> GrowwKeyPair:
    """Generate a new NATS keypair"""
    return GrowwKeyPair()


def from_seed(encoded_seed: bytes) -> GrowwKeyPair:
    """Create keypair from an encoded seed"""
    _, raw_seed = decode_seed(encoded_seed)
    return GrowwKeyPair(raw_seed)