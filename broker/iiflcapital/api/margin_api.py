from types import SimpleNamespace

from broker.iiflcapital.baseurl import BASE_URL
from broker.iiflcapital.mapping.transform_data import transform_data
from database.token_db import get_token
from utils.httpx_client import get_httpx_client


def calculate_margin_api(positions, auth):
    """Calculate margin using IIFL Capital span/exposure endpoint."""
    transformed_positions = []

    for position in positions:
        token = get_token(position.get("symbol"), position.get("exchange"))
        if not token:
            continue
        transformed_positions.append(transform_data(position, token))

    if not transformed_positions:
        return (
            SimpleNamespace(status=400, status_code=400),
            {
                "status": "error",
                "message": "No valid positions for margin calculation",
            },
        )

    client = get_httpx_client()
    headers = {
        "Authorization": f"Bearer {auth}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    response = client.post(f"{BASE_URL}/spanexposure", headers=headers, json=transformed_positions)

    try:
        payload = response.json()
    except Exception:
        payload = {"status": "error", "message": "Invalid broker response"}

    response_wrapper = SimpleNamespace(status=response.status_code, status_code=response.status_code)

    if response.status_code == 200:
        result = payload.get("result", payload)
        return (
            response_wrapper,
            {
                "status": "success",
                "data": {
                    "span": result.get("span", 0),
                    "exposure_margin": result.get("exposureMargin", 0),
                    "total_margin": result.get("totalMargin", 0),
                    "buy_premium": result.get("buyPremium", 0),
                },
            },
        )

    return response_wrapper, {
        "status": "error",
        "message": payload.get("message", "Failed to calculate margin"),
    }
