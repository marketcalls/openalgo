"""Live streaming for SMIFS God Quant is not supported by this plugin yet.

SMIFS publishes a binary market feed over WebSocket (see
https://smifsgq.smifs.com/api.html#feed), but no OpenAlgo WebSocket proxy
adapter is provided here, so OpenAlgo's streaming features are unavailable
when SMIFS is the active broker: the proxy answers "Unsupported broker:
smifs. No adapter available." REST trading, quotes, depth, history, funds
and margin all work.
"""
