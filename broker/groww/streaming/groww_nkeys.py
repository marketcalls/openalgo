"""
Minimal implementation of nkeys functionality for Groww WebSocket
Based on NATS nkeys specification using cryptography library for Ed25519
"""

import base64
import os
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

# NATS nkeys prefix bytes
PREFIX_BYTE_SEED = 18 << 3  # Base32-encodes to 'S...'
PREFIX_BYTE_PRIVATE = 15 << 3  # Base32-encodes to 'P...'
PREFIX_BYTE_USER = 20 << 3  # Base32-encodes to 'U...'

# CRC16 table for checksum
CRC16TAB = [
    0x0000,
    0x1021,
    0x2042,
    0x3063,
    0x4084,
    0x50A5,
    0x60C6,
    0x70E7,
    0x8108,
    0x9129,
    0xA14A,
    0xB16B,
    0xC18C,
    0xD1AD,
    0xE1CE,
    0xF1EF,
    0x1231,
    0x0210,
    0x3273,
    0x2252,
    0x52B5,
    0x4294,
    0x72F7,
    0x62D6,
    0x9339,
    0x8318,
    0xB37B,
    0xA35A,
    0xD3BD,
    0xC39C,
    0xF3FF,
    0xE3DE,
    0x2462,
    0x3443,
    0x0420,
    0x1401,
    0x64E6,
    0x74C7,
    0x44A4,
    0x5485,
    0xA56A,
    0xB54B,
    0x8528,
    0x9509,
    0xE5EE,
    0xF5CF,
    0xC5AC,
    0xD58D,
    0x3653,
    0x2672,
    0x1611,
    0x0630,
    0x76D7,
    0x66F6,
    0x5695,
    0x46B4,
    0xB75B,
    0xA77A,
    0x9719,
    0x8738,
    0xF7DF,
    0xE7FE,
    0xD79D,
    0xC7BC,
    0x48C4,
    0x58E5,
    0x6886,
    0x78A7,
    0x0840,
    0x1861,
    0x2802,
    0x3823,
    0xC9CC,
    0xD9ED,
    0xE98E,
    0xF9AF,
    0x8948,
    0x9969,
    0xA90A,
    0xB92B,
    0x5AF5,
    0x4AD4,
    0x7AB7,
    0x6A96,
    0x1A71,
    0x0A50,
    0x3A33,
    0x2A12,
    0xDBFD,
    0xCBDC,
    0xFBBF,
    0xEB9E,
    0x9B79,
    0x8B58,
    0xBB3B,
    0xAB1A,
    0x6CA6,
    0x7C87,
    0x4CE4,
    0x5CC5,
    0x2C22,
    0x3C03,
    0x0C60,
    0x1C41,
    0xEDAE,
    0xFD8F,
    0xCDEC,
    0xDDCD,
    0xAD2A,
    0xBD0B,
    0x8D68,
    0x9D49,
    0x7E97,
    0x6EB6,
    0x5ED5,
    0x4EF4,
    0x3E13,
    0x2E32,
    0x1E51,
    0x0E70,
    0xFF9F,
    0xEFBE,
    0xDFDD,
    0xCFFC,
    0xBF1B,
    0xAF3A,
    0x9F59,
    0x8F78,
    0x9188,
    0x81A9,
    0xB1CA,
    0xA1EB,
    0xD10C,
    0xC12D,
    0xF14E,
    0xE16F,
    0x1080,
    0x00A1,
    0x30C2,
    0x20E3,
    0x5004,
    0x4025,
    0x7046,
    0x6067,
    0x83B9,
    0x9398,
    0xA3FB,
    0xB3DA,
    0xC33D,
    0xD31C,
    0xE37F,
    0xF35E,
    0x02B1,
    0x1290,
    0x22F3,
    0x32D2,
    0x4235,
    0x5214,
    0x6277,
    0x7256,
    0xB5EA,
    0xA5CB,
    0x95A8,
    0x8589,
    0xF56E,
    0xE54F,
    0xD52C,
    0xC50D,
    0x34E2,
    0x24C3,
    0x14A0,
    0x0481,
    0x7466,
    0x6447,
    0x5424,
    0x4405,
    0xA7DB,
    0xB7FA,
    0x8799,
    0x97B8,
    0xE75F,
    0xF77E,
    0xC71D,
    0xD73C,
    0x26D3,
    0x36F2,
    0x0691,
    0x16B0,
    0x6657,
    0x7676,
    0x4615,
    0x5634,
    0xD94C,
    0xC96D,
    0xF90E,
    0xE92F,
    0x99C8,
    0x89E9,
    0xB98A,
    0xA9AB,
    0x5844,
    0x4865,
    0x7806,
    0x6827,
    0x18C0,
    0x08E1,
    0x3882,
    0x28A3,
    0xCB7D,
    0xDB5C,
    0xEB3F,
    0xFB1E,
    0x8BF9,
    0x9BD8,
    0xABBB,
    0xBB9A,
    0x4A75,
    0x5A54,
    0x6A37,
    0x7A16,
    0x0AF1,
    0x1AD0,
    0x2AB3,
    0x3A92,
    0xFD2E,
    0xED0F,
    0xDD6C,
    0xCD4D,
    0xBDAA,
    0xAD8B,
    0x9DE8,
    0x8DC9,
    0x7C26,
    0x6C07,
    0x5C64,
    0x4C45,
    0x3CA2,
    0x2C83,
    0x1CE0,
    0x0CC1,
    0xEF1F,
    0xFF3E,
    0xCF5D,
    0xDF7C,
    0xAF9B,
    0xBFBA,
    0x8FD9,
    0x9FF8,
    0x6E17,
    0x7E36,
    0x4E55,
    0x5E74,
    0x2E93,
    0x3EB2,
    0x0ED1,
    0x1EF0,
]


def crc16(data: bytes) -> int:
    """Calculate CRC16 checksum"""
    crc = 0
    for c in data:
        crc = ((crc << 8) & 0xFFFF) ^ CRC16TAB[((crc >> 8) ^ c) & 0x00FF]
    return crc


def crc16_checksum(data: bytes) -> bytes:
    """Calculate CRC16 checksum and return as bytes"""
    crc = crc16(data)
    return crc.to_bytes(2, byteorder="little")


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

    return base64.b32encode(final_bytes).rstrip(b"=")


def decode_seed(seed: bytes) -> tuple[int, bytes]:
    """
    Decode a NATS nkey seed

    Args:
        seed: Base32-encoded seed

    Returns:
        Tuple of (prefix, raw_seed)
    """
    # Add padding if needed
    padding = b"=" * ((-len(seed)) % 8)
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

    def sign(self, message: bytes) -> "SignedMessage":
        """Sign a message using Ed25519"""
        signature = self._private_key.sign(message)
        return SignedMessage(signature)

    @property
    def verify_key(self) -> "Ed25519VerifyKey":
        """Get the verify key (public key)"""
        # Get raw public key bytes (32 bytes)
        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
        return Ed25519VerifyKey(public_bytes)

    @property
    def private_bytes(self) -> bytes:
        """Get the raw private key bytes"""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
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
            self._public_key = base64.b32encode(bytes(src)).rstrip(b"=")

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
            self._private_key = base64.b32encode(bytes(src)).rstrip(b"=")

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
