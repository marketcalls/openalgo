from services import option_chain_service


def test_reference_metadata_preserves_resolved_contract():
    assert option_chain_service._reference_metadata("NIFTY26AUGFUT", "NFO") == {
        "underlying_symbol": "NIFTY26AUGFUT",
        "underlying_exchange": "NFO",
    }
