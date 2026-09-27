"""AliceBlue EC* error codes, from 15-error-code.md.

AliceBlue answers failures with a bare code like "EC912" and no prose, so an
order rejection surfaced to the user as that string and nothing else. This maps
the published table to the broker's own descriptions.

Generated from the docs rather than hand-typed - 133 codes - so it can be
regenerated when AliceBlue publishes more. Unknown codes pass through
unchanged: inventing a description for a code we do not know would be worse
than showing the raw one.
"""

import re

#: code -> AliceBlue's own description, verbatim from the published table.
ERROR_CODES = {
    "EC003": "An error occurred. Please try again later.",
    "EC900": "'exchange' cannot be empty or null.",
    "EC901": "'exchange' should be one of the following values: { 'NSE', 'BSE', 'MCX', 'NFO', 'BFO', 'CDS', 'BCD'}.",
    "EC902": "'tradingSymbol' cannot be empty or null.",
    "EC903": "'quantity' cannot be empty or null.",
    "EC904": "'quantity' should be a positive number.",
    "EC906": "'product' cannot be empty or null.",
    "EC907": "'transactionType' cannot be empty or null.",
    "EC908": "'token' cannot be empty or null.",
    "EC909": "'disclosedQty' cannot be empty or null.",
    "EC910": "'price' cannot be empty or null.",
    "EC911": "'triggerPrice' cannot be empty or null.",
    "EC912": "Failed to place the order.",
    "EC913": "Failed to retrieve user details.",
    "EC914": "'Request parameter' cannot be empty or null.",
    "EC915": "Failed to retrieve the order book.",
    "EC916": "No orders found for this user.",
    "EC917": "Failed to retrieve order history.",
    "EC918": "No order history found for the given order ID.",
    "EC919": "Failed to retrieve the position book.",
    "EC920": "No positions found for this user.",
    "EC921": "Failed to retrieve holdings.",
    "EC922": "No holdings found for this user.",
    "EC923": "Failed to retrieve profile details.",
    "EC924": "Failed to retrieve RMS limits.",
    "EC925": "'nestOrderNo' cannot be empty or null.",
    "EC926": "No trades found for this user.",
    "EC927": "Failed to retrieve the trade book.",
    "EC929": "'transactionType' should be one of the following values: {'BUY', 'SELL'}.",
    "EC930": "'orderType' should be one of the following values: {'LIMIT', 'MARKET', 'SL', 'SLM'}.",
    "EC932": "'validity' should be one of the following values: {'DAY', 'IOC'}.",
    "EC933": "'priceType' cannot be empty or null.",
    "EC934": "'orderType' cannot be empty or null.",
    "EC935": "Failed to retrieve the single order margin.",
    "EC936": "'product' cannot be empty or null.",
    "EC937": "Failed to cancel all orders.",
    "EC938": "No open orders to cancel from the order book.",
    "EC939": "Failed to retrieve the span margin.",
    "EC941": "'instrumentId' cannot be empty or null.",
    "EC942": "'orderComplexity' cannot be empty or null.",
    "EC944": "'validity' cannot be empty or null.",
    "EC945": "'brokerOrderId' cannot be empty or null.",
    "EC946": "Invalid 'instrumentId'. It must contain only numeric characters.",
    "EC947": "'instrumentId' does not exist.",
    "EC948": "'quantity' cannot exceed 50,000,000.",
    "EC949": "'quantity' should be a positive number.",
    "EC950": "'price' is required and cannot be empty or null.",
    "EC951": "'slTriggerPrice' is required and cannot be empty or null.",
    "EC953": "'targetPrice' is required and cannot be empty or null.",
    "EC954": "'quantity' should be a multiple of the lot size.",
    "EC957": "Invalid 'price'.",
    "EC958": "'price' cannot be zero or negative.",
    "EC959": "Invalid 'slTriggerPrice'.",
    "EC960": "'slTriggerPrice' cannot be zero or negative.",
    "EC962": "'stopLossPrice' cannot be zero or negative.",
    "EC963": "Invalid 'targetPrice'.",
    "EC964": "'targetPrice' cannot be zero or negative.",
    "EC966": "'trailingSlAmount' cannot be empty or null for SL order type.",
    "EC967": "'trailingSlAmount' should be a positive number.",
    "EC968": "'trailingSlAmount' cannot be zero or negative.",
    "EC969": "'Product' should be either 'NORMAL' or 'INTRADAY'.",
    "EC970": "'disclosedQuantity' is not applicable for this segment.",
    "EC971": "'orderTag' should not exceed 50 characters",
    "EC972": "'algoId' should not exceed 12 characters.",
    "EC973": "For a buy order, 'slTriggerPrice' should be less than the 'price'.",
    "EC974": "For a sell order, 'slTriggerPrice' should be greater than the 'price'.",
    "EC975": "'disclosedQuantity' cannot exceed the total order 'quantity'.",
    "EC979": "Invalid 'brokerOrderId'.",
    "EC980": "Invalid 'instrumentId'.",
    "EC981": "Invalid 'disclosedQty'.",
    "EC982": "For 'AMO', 'disclosedQuantity' should be zero.",
    "EC983": "Invalid 'algoId'.",
    "EC984": "Invalid 'orderTag'.",
    "EC986": "SpanMargin is not allowed for 'NSEEQ' and 'BSEEQ'.",
    "EC988": "'marketProtection' should be a positive number.",
    "EC990": "'quantity' should be a multiple of the lot size.",
    "EC991": "'disclosedQuantity' should be a multiple of the lot size.",
    "EC992": "Unable to modify the given order. 'brokerOrderId' is invalid.",
    "EC993": "Provided 'brokerOrderId' is not in a valid state to modify the order.",
    "EC994": "The given 'brokerOrderId' is not in your order book.",
    "EC996": "'validity' of IOC is not allowed for AMO orders.",
    "EC997": "The specified order is not available in the order book and cannot be canceled. Please verify the order details and try again.",
    "EC998": "The specified order is not available in the order book, and order history cannot be retrieved. Please verify the order ID and try again.",
    "EC999": "The specified order is not available in the order book and cannot be modified. Please verify the order details and try again.",
    "EC801": "Orders with exchange 'BSEEQ/BSEFO/BSECURR' cannot be modified to order type 'SL' (Stop Loss).",
    "EC806": "'exchange' accepts only {'NSEEQ', 'BSEEQ'}.",
    "EC807": "'product' - 'NORMAL' is not allowed in cash segment.",
    "EC813": "'deviceId' cannot exceed 98 characters.",
    "EC814": "'brokerOrderId' cannot be empty or null.",
    "EC815": "Invalid 'brokerOrderId'.",
    "EC819": "Only the trigger price field can be modified.",
    "EC822": "SL trigger price should be lower than price.",
    "EC823": "SL trigger price should be higher than price.",
    "EC824": "SL trigger price should be %.2f%% below price.",
    "EC825": "SL trigger price should be %.2f%% above price.",
    "EC826": "Please enter a price.",
    "EC827": "Please enter a target price.",
    "EC828": "Please enter an SL trigger price.",
    "EC829": "AMO is not allowed for this product.",
    "EC830": "AMO is not allowed for this order type.",
    "EC831": "AMO is not allowed for this validity.",
    "EC832": "AMO is not allowed for this segment.",
    "EC834": "Market protection cannot be modified.",
    "EC837": "This product is not allowed for this segment.",
    "EC838": "This order type is not allowed.",
    "EC842": "'disclosedQuantity' should be at least %.2f%% of the total order quantity.",
    "EC843": "Only price and quantity fields can be modified.",
    "EC844": "Only price and order type fields can be modified.",
    "EC846": "SL trigger price should be %.2f%% or %.2f paise below price.",
    "EC847": "SL trigger price should be %.2f%% or %.2f paise above price.",
    "EC848": "Price should be higher than the SL trigger price.",
    "EC849": "Price should be lower than the SL trigger price.",
    "EC850": "Price should be %.2f%% or %.2f paise above the SL trigger price.",
    "EC851": "Price should be %.2f%% or %.2f paise below the SL trigger price.",
    "EC852": "This product is not allowed.",
    "EC855": "Modification is not allowed.",
    "EC856": "SL trigger price should be less than main leg price.",
    "EC857": "SL trigger price should be more than main leg price.",
    "EC858": "Order placement not allowed for this exchange.",
    "EC865": "'product' - 'Delivery' is not allowed in FnO segment.",
    "EC868": "Position not found for the specified instrument.",
    "EC869": "Insufficient buy quantity available for conversion.",
    "EC870": "Insufficient sell quantity available for conversion.",
    "EC871": "Conversion of overnight BUY positions in options is not allowed.",
    "EC873": "Failed to convert positions.",
    "EC082": "Invalid parameter: 'deviceId' cannot be empty or null.",
    "EC086": "You are a read-only user and are not allowed to place, modify, or cancel orders.",
    "EC087": "Session Expired",
    "EC088": "Single order slicing limit exceeded",
    "EC089": "'disclosedQuantity' cannot be same the total order 'quantity'.",
    "EC090": "'exchange' should be one of the following values: { 'NSE', 'BSE', 'MCX', 'NFO', 'BFO'}.",
    "EC091": "'orderComplexity' should be one of the following values: {'REGULAR', 'AMO'}.",
    "EC092": "'product' should be one of the following values: {'INTRADAY', 'LONGTERM', 'MTF'}.",
}

_CODE_RE = re.compile(r"\b(EC\d{3})\b")


def describe(message):
    """Expand any EC codes in a broker message into readable text.

    Returns the message unchanged when it carries no known code, so this is
    safe to wrap around every error path.

        "EC912"                  -> "EC912: Failed to place the order."
        "Rejected: EC904"        -> "Rejected: EC904: 'quantity' should be a
                                     positive number."
        "Some other failure"     -> unchanged
    """
    if not message:
        return message
    text = str(message)

    def _expand(match):
        code = match.group(1)
        description = ERROR_CODES.get(code)
        return f"{code}: {description}" if description else code

    return _CODE_RE.sub(_expand, text)
