"""
Test Script for Final Submission Verification

Run this script to verify all components are working before submission.
Usage: python test_before_submission.py
"""

import sys
import subprocess
import time
from pathlib import Path


def print_header(text):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f"  {text}")
    print("=" * 80 + "\n")


def run_demo(script_name, description):
    """Run a demo script and return result."""
    print(f"📋 Running: {description}")
    print(f"   Command: python scripts/{script_name}")
    print()
    
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, f"scripts/{script_name}"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        elapsed = time.time() - start_time
        
        if result.returncode == 0:
            print(f"   ✅ PASSED (Exit {result.returncode}) - {elapsed:.2f}s")
            return True
        else:
            print(f"   ❌ FAILED (Exit {result.returncode}) - {elapsed:.2f}s")
            if result.stderr:
                print(f"   Error: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"   ❌ TIMEOUT (>60s)")
        return False
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return False


def check_files():
    """Check if required files exist."""
    print_header("FILE VERIFICATION")
    
    required_files = [
        "README.md",
        "requirements.txt",
        "TESTING_RESULTS.md",
        "SUBMISSION_CHECKLIST.md",
        "SPRINT1_SUMMARY.md",
        "SPRINT2_SUMMARY.md",
        "scripts/demo_pipeline.py",
        "scripts/demo_core_components.py",
        "scripts/demo_integration.py",
    ]
    
    all_exist = True
    for file_path in required_files:
        if Path(file_path).exists():
            print(f"   ✅ {file_path}")
        else:
            print(f"   ❌ MISSING: {file_path}")
            all_exist = False
    
    return all_exist


def main():
    """Main test function."""
    print("\n")
    print("╔══════════════════════════════════════════════════════════════════════╗")
    print("║                                                                      ║")
    print("║            PRE-SUBMISSION VERIFICATION TEST                          ║")
    print("║                                                                      ║")
    print("╚══════════════════════════════════════════════════════════════════════╝")
    
    # Check files
    files_ok = check_files()
    
    if not files_ok:
        print("\n❌ Some required files are missing!")
        return 1
    
    # Run demos
    print_header("RUNNING APPLICATION TESTS")
    
    tests = [
        ("demo_pipeline.py", "Sprint 1 - Zero-Hallucination Pipeline"),
        ("demo_core_components.py", "Sprint 2 - Core Components"),
        ("demo_integration.py", "Sprint 3 - Integration"),
    ]
    
    results = []
    for script, desc in tests:
        passed = run_demo(script, desc)
        results.append((desc, passed))
        print()
    
    # Summary
    print_header("TEST RESULTS SUMMARY")
    
    passed_count = sum(1 for _, passed in results if passed)
    total_count = len(results)
    
    for desc, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"   {status}: {desc}")
    
    print()
    print(f"   Total: {passed_count}/{total_count} tests passed")
    print()
    
    if passed_count == total_count:
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║                                                                      ║")
        print("║                  ✅ ALL TESTS PASSED! ✅                             ║")
        print("║                                                                      ║")
        print("║              YOUR APPLICATION IS READY TO SUBMIT!                    ║")
        print("║                                                                      ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
        print()
        print("📦 Submit this GitHub repository:")
        print("   https://github.com/tusharpawar1217/frontieratlas-ingestion-engine-")
        print()
        return 0
    else:
        print("╔══════════════════════════════════════════════════════════════════════╗")
        print("║                                                                      ║")
        print("║                  ❌ SOME TESTS FAILED! ❌                            ║")
        print("║                                                                      ║")
        print("║                Please review the errors above.                       ║")
        print("║                                                                      ║")
        print("╚══════════════════════════════════════════════════════════════════════╝")
        print()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
