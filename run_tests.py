#!/usr/bin/env python3
"""
Test Runner Script for OpenAlgo Event Publisher

Usage:
    python run_tests.py                    # Run all tests
    python run_tests.py --unit             # Run only unit tests
    python run_tests.py --integration      # Run only integration tests
    python run_tests.py --coverage         # Run with coverage report
    python run_tests.py --verbose          # Run with verbose output
    python run_tests.py --fast             # Run in parallel (requires pytest-xdist)
"""

import sys
import subprocess
import argparse
import os


def run_command(cmd):
    """Run a command and return exit code"""
    print(f"\n{'='*70}")
    print(f"Running: {' '.join(cmd)}")
    print(f"{'='*70}\n")
    
    result = subprocess.run(cmd)
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description='Run OpenAlgo Event Publisher Tests')
    parser.add_argument('--unit', action='store_true', help='Run only unit tests')
    parser.add_argument('--integration', action='store_true', help='Run only integration tests')
    parser.add_argument('--coverage', action='store_true', help='Run with coverage report')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--fast', '-f', action='store_true', help='Run tests in parallel')
    parser.add_argument('--html', action='store_true', help='Generate HTML coverage report')
    parser.add_argument('--pdb', action='store_true', help='Drop to debugger on failure')
    
    args = parser.parse_args()
    
    # Base command
    cmd = ['python', '-m', 'pytest', 'test/']
    
    # Add test selection
    if args.unit:
        cmd.append('test/test_event_publisher.py')
    elif args.integration:
        cmd.append('test/test_event_publisher_integration.py')
    
    # Add options
    if args.verbose:
        cmd.append('-v')
    
    if args.fast:
        cmd.extend(['-n', 'auto'])  # Use all CPU cores
    
    if args.pdb:
        cmd.append('--pdb')
    
    if args.coverage:
        cmd.extend([
            '--cov=utils.event_publisher',
            '--cov-report=term-missing'
        ])
        
        if args.html:
            cmd.append('--cov-report=html')
    
    # Run tests
    exit_code = run_command(cmd)
    
    if exit_code == 0:
        print(f"\n{'='*70}")
        print("✅ All tests passed!")
        print(f"{'='*70}\n")
        
        if args.coverage and args.html:
            print("📊 Coverage report generated: htmlcov/index.html")
            print("   Open in browser to view detailed coverage\n")
    else:
        print(f"\n{'='*70}")
        print("❌ Some tests failed!")
        print(f"{'='*70}\n")
    
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
