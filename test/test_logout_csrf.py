#!/usr/bin/env python3
"""
Test script for logout CSRF protection

This script tests that the logout endpoint properly requires POST method
and CSRF token to prevent CSRF attacks via GET requests.
"""

import requests
import sys
import re

def test_logout_csrf_protection(base_url="http://127.0.0.1:5000"):
    """Test logout CSRF protection"""
    print(f"\n{'='*60}")
    print(f"Testing Logout CSRF Protection")
    print(f"Server: {base_url}")
    print(f"{'='*60}\n")
    
    session = requests.Session()
    results = []
    
    # Test 1: GET request should fail
    print("Test 1: GET request to logout (should fail)")
    try:
        response = session.get(f"{base_url}/auth/logout", allow_redirects=False)
        if response.status_code == 405:  # Method Not Allowed
            print("✓ PASS: GET request properly rejected with 405 Method Not Allowed")
            results.append(True)
        else:
            print(f"✗ FAIL: GET request returned {response.status_code} instead of 405")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error making GET request: {e}")
        results.append(False)
    
    # Test 2: POST without CSRF token should fail
    print("\nTest 2: POST request without CSRF token (should fail)")
    try:
        response = session.post(f"{base_url}/auth/logout", allow_redirects=False)
        if response.status_code in [400, 403]:  # Bad Request or Forbidden
            print(f"✓ PASS: POST without CSRF token rejected with {response.status_code}")
            results.append(True)
        else:
            print(f"✗ FAIL: POST without CSRF returned {response.status_code}")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error making POST request: {e}")
        results.append(False)
    
    # Test 3: Verify logout form has CSRF token
    print("\nTest 3: Check if logout forms include CSRF token")
    try:
        # Get a page with logout button (e.g., dashboard if logged in, or 500 error page)
        response = session.get(f"{base_url}/500")
        
        # Check for logout form with CSRF token
        has_post_form = 'method="POST"' in response.text and 'auth.logout' in response.text
        has_csrf_token = 'name="csrf_token"' in response.text
        
        if has_post_form and has_csrf_token:
            print("✓ PASS: Logout form uses POST method with CSRF token")
            results.append(True)
        else:
            print(f"✗ FAIL: Logout form missing POST method or CSRF token")
            print(f"  Has POST form: {has_post_form}")
            print(f"  Has CSRF token: {has_csrf_token}")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error checking logout form: {e}")
        results.append(False)
    
    # Test 4: Verify no GET logout links remain
    print("\nTest 4: Check for any remaining GET logout links")
    try:
        pages_to_check = ["/", "/500", "/login"]
        get_logout_found = False
        
        for page in pages_to_check:
            try:
                response = session.get(f"{base_url}{page}")
                # Look for old-style GET logout links
                if re.search(r'<a[^>]*href=["\'][^"\']*auth\.logout[^"\']*["\']', response.text):
                    get_logout_found = True
                    print(f"  ✗ Found GET logout link in {page}")
            except:
                continue
        
        if not get_logout_found:
            print("✓ PASS: No GET logout links found")
            results.append(True)
        else:
            print("✗ FAIL: GET logout links still exist")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error checking for GET links: {e}")
        results.append(False)
    
    # Summary
    print(f"\n{'='*60}")
    passed = sum(results)
    total = len(results)
    print(f"Test Summary: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All tests passed! Logout is protected against CSRF attacks.")
    else:
        print("❌ Some tests failed. Please review the logout implementation.")
    
    print(f"{'='*60}\n")
    
    return passed == total

if __name__ == "__main__":
    base_url = "http://127.0.0.1:5000"
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    
    success = test_logout_csrf_protection(base_url)
    sys.exit(0 if success else 1)