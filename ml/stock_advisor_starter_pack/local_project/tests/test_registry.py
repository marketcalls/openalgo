from pathlib import Path

from strategies.registry import build_strategy_registry


def test_strategy_registry_initializes():
    strategy_root = Path(r"D:\test1")
    registry = build_strategy_registry(strategy_root)
    assert registry
    assert "twin_range_filter" in registry
    assert registry["flowscope_hapharmonic"].unsupported_reason is not None
