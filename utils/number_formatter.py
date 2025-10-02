# utils/number_formatter.py
"""
Number formatting utilities for Indian numbering system
Formats large numbers in Crores (Cr) and Lakhs (L)
"""

def format_indian_number(value):
    """
    Format number in Indian format with Cr/L suffixes

    Examples:
        10000000.0 -> 1.00Cr
        9978000.0 -> 99.78L
        10000.0 -> 10000.00
        -5000000.0 -> -50.00L

    Args:
        value: Number to format (int, float, or string)

    Returns:
        Formatted string with Cr/L suffix or decimal format
    """
    try:
        # Convert to float
        num = float(value)

        # Handle sign
        is_negative = num < 0
        num = abs(num)

        # Format based on magnitude
        if num >= 10000000:  # 1 Crore or more
            formatted = f"{num / 10000000:.2f}Cr"
        elif num >= 100000:  # 1 Lakh or more
            formatted = f"{num / 100000:.2f}L"
        else:
            # For numbers less than 1L, show with 2 decimal places
            formatted = f"{num:.2f}"

        # Add negative sign if needed
        if is_negative:
            formatted = f"-{formatted}"

        return formatted

    except (ValueError, TypeError):
        # If conversion fails, return original value as string
        return str(value)


def format_indian_currency(value):
    """
    Format number as Indian currency (₹)

    Examples:
        10000000.0 -> ₹1.00Cr
        9978000.0 -> ₹99.78L
        10000.0 -> ₹10000.00

    Args:
        value: Number to format

    Returns:
        Formatted string with ₹ prefix
    """
    formatted = format_indian_number(value)
    return f"₹{formatted}"
