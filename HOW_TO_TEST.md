# How to Test Before Submission

This guide shows you how to test the application on your local machine before submitting.

---

## Quick Test (Recommended)

### Option 1: Double-Click (Windows)
1. Double-click `RUN_TESTS.bat` file
2. Wait for all tests to complete
3. Check results (all should show ✅)

### Option 2: Run Test Script
```bash
python test_before_submission.py
```

This will:
- ✅ Check all required files exist
- ✅ Run Sprint 1 demo
- ✅ Run Sprint 2 demo
- ✅ Run Sprint 3 demo
- ✅ Show summary of results

---

## Individual Demo Tests

If you want to test each sprint separately:

### Sprint 1: Zero-Hallucination Pipeline
```bash
python scripts/demo_pipeline.py
```

**Expected Output:**
- Evidence grounding: Valid extractions accepted, hallucinations rejected
- Provenance tracking: HTTP 200, SHA-256, timestamps
- Quality gates: 6/6 passed
- Exit code: 0

### Sprint 2: Core Components
```bash
python scripts/demo_core_components.py
```

**Expected Output:**
- URL Frontier: Priority scheduling + deduplication
- Rate Limiter: Token bucket + adaptive backoff
- Cache: LRU + TTL per vertical
- Chaos Engineering: Failure injection
- Composite Client: All components integrated
- Exit code: 0

### Sprint 3: Integration
```bash
python scripts/demo_integration.py
```

**Expected Output:**
- papers.py crawler integrated
- news.py crawler integrated
- Rate limiting working
- Cache working (100% hit rate on 2nd fetch)
- Exit code: 0

---

## Manual Testing

If you want to test specific components:

### 1. Test Evidence Grounding
```python
from src.llm.grounding import EvidenceGroundingValidator

validator = EvidenceGroundingValidator()
source = "Attention Is All You Need - Transformers paper"
data = {
    "title": {
        "value": "Attention Is All You Need",
        "evidence": "Attention Is All You Need"
    }
}
result = validator.validate(data, source, ["title"])
print(f"Valid: {result.is_valid}")  # Should be True
```

### 2. Test URL Frontier
```python
import asyncio
from src.frontier import URLFrontier, Priority

async def test_frontier():
    frontier = URLFrontier()
    await frontier.add("https://example.com/1", Priority.HIGH, "papers")
    await frontier.add("https://example.com/2", Priority.LOW, "news")
    
    url1 = await frontier.pop()
    print(f"First URL: {url1.url} (priority: {url1.priority})")
    # Should get HIGH priority first

asyncio.run(test_frontier())
```

### 3. Test Rate Limiter
```python
import asyncio
from src.ratelimit import AdaptiveRateLimiter

async def test_rate_limiter():
    limiter = AdaptiveRateLimiter(default_rate=5.0, default_burst=3)
    
    # These should be immediate (burst)
    await limiter.acquire("example.com")
    await limiter.acquire("example.com")
    await limiter.acquire("example.com")
    
    print("Burst complete!")
    
    # This should wait
    await limiter.acquire("example.com")
    print("Throttled request complete!")

asyncio.run(test_rate_limiter())
```

### 4. Test Cache
```python
import asyncio
from src.cache import ContentCache

async def test_cache():
    cache = ContentCache(max_size=100)
    cache.set_ttl("papers", 24 * 3600)  # 24 hours
    
    # Set and get
    await cache.set("https://example.com", "papers", "content")
    result = await cache.get("https://example.com", "papers")
    
    print(f"Cache hit: {result is not None}")
    print(f"Stats: {cache.get_stats()}")

asyncio.run(test_cache())
```

---

## Verify Repository

Check that all files are present:

```bash
# Check file count
ls -R | wc -l  # Linux/Mac
(Get-ChildItem -Recurse -File).Count  # Windows PowerShell

# Should show ~120 files
```

Check key files:
- ✅ README.md
- ✅ requirements.txt
- ✅ TESTING_RESULTS.md
- ✅ SUBMISSION_CHECKLIST.md
- ✅ SPRINT1_SUMMARY.md
- ✅ SPRINT2_SUMMARY.md

---

## Expected Results

When all tests pass, you should see:

```
╔══════════════════════════════════════════════════════════════════════╗
║                                                                      ║
║                  ✅ ALL TESTS PASSED! ✅                             ║
║                                                                      ║
║              YOUR APPLICATION IS READY TO SUBMIT!                    ║
║                                                                      ║
╚══════════════════════════════════════════════════════════════════════╝

📦 Submit this GitHub repository:
   https://github.com/tusharpawar1217/frontieratlas-ingestion-engine-
```

---

## Troubleshooting

### "Module not found" error
```bash
pip install -r requirements.txt
```

### "Python not found"
Make sure Python 3.10+ is installed:
```bash
python --version
```

### Demo doesn't exit
- Press Ctrl+C to stop
- Check if there's an infinite loop
- Review error messages

### All tests fail
1. Check you're in the correct directory
2. Verify requirements are installed
3. Check Python version (need 3.10+)

---

## Quick Verification Checklist

Before submitting, verify:

- [ ] All 3 demos run successfully (exit 0)
- [ ] No error messages in output
- [ ] All features working as expected
- [ ] README.md is comprehensive
- [ ] All files are committed to Git
- [ ] Repository is pushed to GitHub

---

## Contact

If you encounter issues:
1. Check error messages carefully
2. Review logs in console output
3. Verify all dependencies installed
4. Check Python version compatibility

---

## Final Step

Once all tests pass:

1. ✅ Verify GitHub repository is up-to-date
2. ✅ Double-check all tests passed
3. ✅ Submit the GitHub URL:

   **https://github.com/tusharpawar1217/frontieratlas-ingestion-engine-**

---

**Good luck with your submission!** 🚀
