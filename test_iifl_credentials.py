#!/usr/bin/env python3
"""
Test script for IIFL API credentials
Usage: python test_iifl_credentials.py
"""

import requests
import json
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def test_iifl_credentials():
    """Test IIFL authentication with current credentials"""
    
    # Get credentials from environment
    api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')
    
    print(f"🔑 Testing IIFL credentials...")
    print(f"API Key: {api_key[:10]}...")
    print(f"API Secret: {api_secret[:5]}...")
    
    # Test main authentication
    payload = {
        "appKey": api_key,
        "secretKey": api_secret,
        "source": "WebAPI"
    }
    
    headers = {
        'Content-Type': 'application/json'
    }
    
    try:
        print("\n🔄 Testing Interactive API authentication...")
        response = requests.post(
            "https://blazemum.indiainfoline.com/interactive/user/session",
            json=payload,
            headers=headers,
            timeout=30
        )
        
        print(f"Status Code: {response.status_code}")
        result = response.json()
        print(f"Response: {json.dumps(result, indent=2)}")
        
        if response.status_code == 200 and result.get('type') == 'success':
            print("✅ Interactive API authentication: SUCCESS")
            token = result['result']['token']
            print(f"Auth Token: {token[:20]}...")
            
            # Test market data authentication
            print("\n🔄 Testing Market Data API authentication...")
            market_api_key = os.getenv('BROKER_API_KEY_MARKET')
            market_api_secret = os.getenv('BROKER_API_SECRET_MARKET')
            
            market_payload = {
                "appKey": market_api_key,
                "secretKey": market_api_secret,
                "source": "WebAPI"
            }
            
            market_response = requests.post(
                "https://blazemum.indiainfoline.com/apimarketdata/auth/login",
                json=market_payload,
                headers=headers,
                timeout=30
            )
            
            print(f"Market Data Status Code: {market_response.status_code}")
            market_result = market_response.json()
            print(f"Market Data Response: {json.dumps(market_result, indent=2)}")
            
            if market_response.status_code == 200 and market_result.get('type') == 'success':
                print("✅ Market Data API authentication: SUCCESS")
                print("\n🎉 All IIFL credentials are working correctly!")
                return True
            else:
                print("❌ Market Data API authentication: FAILED")
                return False
                
        else:
            print("❌ Interactive API authentication: FAILED")
            if result.get('code') == 'e-user-00013':
                print("\n💡 Error 'e-user-00013' typically means:")
                print("   - Invalid API Key/Secret")
                print("   - Expired credentials")
                print("   - Wrong environment (sandbox vs live)")
            return False
            
    except Exception as e:
        print(f"❌ Error during authentication test: {e}")
        return False

if __name__ == "__main__":
    test_iifl_credentials()
