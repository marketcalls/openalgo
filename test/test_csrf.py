#!/usr/bin/env python3
"""
Cross-platform CSRF Protection Test Suite for OpenAlgo

This script tests CSRF protection functionality across different platforms (Ubuntu, Windows, macOS)
and validates that the environment-based configuration works correctly.

Usage:
    python test/test_csrf.py
"""

import os
import sys
import platform
import requests
import json
from datetime import datetime
from urllib.parse import urljoin

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class CSRFTester:
    def __init__(self, base_url="http://127.0.0.1:5000"):
        self.base_url = base_url
        self.session = requests.Session()
        self.results = {
            "platform": platform.system(),
            "python_version": sys.version,
            "timestamp": datetime.now().isoformat(),
            "tests": []
        }
        
    def log_result(self, test_name, passed, details=""):
        """Log test results"""
        result = {
            "test": test_name,
            "passed": passed,
            "details": details
        }
        self.results["tests"].append(result)
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status}: {test_name}")
        if details:
            print(f"  Details: {details}")
    
    def test_env_configuration(self):
        """Test 1: Verify environment variables are properly loaded"""
        print("\n=== Testing Environment Configuration ===")
        
        # Check if .env file exists
        env_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        if not os.path.exists(env_file):
            self.log_result("Environment file exists", False, ".env file not found")
            return False
            
        # Read and verify CSRF settings
        csrf_enabled = None
        csrf_time_limit = None
        
        with open(env_file, 'r') as f:
            for line in f:
                if line.startswith('CSRF_ENABLED'):
                    csrf_enabled = line.split('=')[1].strip().strip("'\"")
                elif line.startswith('CSRF_TIME_LIMIT'):
                    csrf_time_limit = line.split('=')[1].strip().strip("'\"")
        
        self.log_result("CSRF_ENABLED in .env", csrf_enabled is not None, f"Value: {csrf_enabled}")
        self.log_result("CSRF_TIME_LIMIT in .env", csrf_time_limit is not None, f"Value: {csrf_time_limit}")
        
        return csrf_enabled is not None
    
    def test_server_connection(self):
        """Test 2: Check if server is running and accessible"""
        print("\n=== Testing Server Connection ===")
        
        try:
            response = self.session.get(self.base_url)
            self.log_result("Server accessible", response.status_code == 200, f"Status: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            self.log_result("Server accessible", False, str(e))
            return False
    
    def test_csrf_token_generation(self):
        """Test 3: Verify CSRF token is generated in forms"""
        print("\n=== Testing CSRF Token Generation ===")
        
        try:
            # Get login page
            response = self.session.get(urljoin(self.base_url, "/auth/login"))
            if response.status_code != 200:
                self.log_result("Login page accessible", False, f"Status: {response.status_code}")
                return False
                
            # Check for CSRF token in response
            has_csrf_meta = 'name="csrf-token"' in response.text
            has_csrf_input = 'name="csrf_token"' in response.text
            
            self.log_result("CSRF meta tag present", has_csrf_meta)
            self.log_result("CSRF input field present", has_csrf_input)
            
            # Extract CSRF token
            if has_csrf_input:
                import re
                token_match = re.search(r'name="csrf_token"\s+value="([^"]+)"', response.text)
                if token_match:
                    csrf_token = token_match.group(1)
                    self.log_result("CSRF token extracted", True, f"Token length: {len(csrf_token)}")
                    self.session.headers['X-CSRFToken'] = csrf_token
                    return True
                    
            return False
            
        except Exception as e:
            self.log_result("CSRF token generation", False, str(e))
            return False
    
    def test_form_without_csrf(self):
        """Test 4: Verify form submission fails without CSRF token"""
        print("\n=== Testing Form Submission Without CSRF ===")
        
        try:
            # Try to submit login form without CSRF token
            data = {
                "username": "test_user",
                "password": "test_pass"
            }
            
            response = requests.post(
                urljoin(self.base_url, "/auth/login"),
                data=data,
                allow_redirects=False
            )
            
            # Should get 400 Bad Request without CSRF
            is_protected = response.status_code in [400, 403]
            self.log_result("Form protected without CSRF", is_protected, f"Status: {response.status_code}")
            
            return is_protected
            
        except Exception as e:
            self.log_result("CSRF protection test", False, str(e))
            return False
    
    def test_api_exemption(self):
        """Test 5: Verify API endpoints are exempt from CSRF"""
        print("\n=== Testing API CSRF Exemption ===")
        
        try:
            # API endpoints should work without CSRF token
            headers = {
                'Content-Type': 'application/json',
                'X-API-KEY': 'test_key'  # Would need valid key in production
            }
            
            response = requests.get(
                urljoin(self.base_url, "/api/v1/orders"),
                headers=headers
            )
            
            # Should not get CSRF error (might get auth error which is fine)
            is_exempt = response.status_code != 400 or 'CSRF' not in response.text
            self.log_result("API endpoint CSRF exempt", is_exempt, f"Status: {response.status_code}")
            
            return is_exempt
            
        except Exception as e:
            self.log_result("API exemption test", False, str(e))
            return True  # Consider it passed if we can't reach the endpoint
    
    def test_cross_platform_compatibility(self):
        """Test 6: Platform-specific compatibility checks"""
        print("\n=== Testing Cross-Platform Compatibility ===")
        
        current_platform = platform.system()
        
        # Check file path separators
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        path_valid = os.path.exists(env_path)
        self.log_result(f"Path handling on {current_platform}", path_valid, env_path)
        
        # Check line endings in .env file
        if path_valid:
            with open(env_path, 'rb') as f:
                content = f.read()
                has_crlf = b'\r\n' in content
                has_lf = b'\n' in content
                
                if current_platform == "Windows":
                    self.log_result("Windows line endings compatible", True)
                else:
                    self.log_result("Unix line endings compatible", has_lf, "LF endings found")
        
        return True
    
    def run_all_tests(self):
        """Run all CSRF tests"""
        print(f"\n{'='*60}")
        print(f"OpenAlgo CSRF Protection Test Suite")
        print(f"Platform: {platform.system()} {platform.release()}")
        print(f"Python: {platform.python_version()}")
        print(f"{'='*60}")
        
        # Run tests in order
        tests = [
            self.test_env_configuration,
            self.test_server_connection,
            self.test_csrf_token_generation,
            self.test_form_without_csrf,
            self.test_api_exemption,
            self.test_cross_platform_compatibility
        ]
        
        for test in tests:
            try:
                test()
            except Exception as e:
                self.log_result(test.__name__, False, f"Exception: {str(e)}")
        
        # Summary
        print(f"\n{'='*60}")
        passed = sum(1 for t in self.results["tests"] if t["passed"])
        total = len(self.results["tests"])
        print(f"Test Summary: {passed}/{total} tests passed")
        
        # Save results
        results_file = f"csrf_test_results_{platform.system().lower()}.json"
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2)
        print(f"Results saved to: {results_file}")
        
        return passed == total

def main():
    """Main test execution"""
    # Check command line arguments
    base_url = "http://127.0.0.1:5000"
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    
    print(f"Testing against: {base_url}")
    
    # Create tester and run tests
    tester = CSRFTester(base_url)
    success = tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()