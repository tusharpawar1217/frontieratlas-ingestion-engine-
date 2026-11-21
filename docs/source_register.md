# Source Viability Register

**Generated**: 2026-11-21 08:35:28 UTC
**Total Sources Tested**: 18

## Legend

- 🟢 VIABLE - Accessible, parseable, fresh
- 🟡 UNSTABLE - HTTP errors, parse failures, or stale
- 🔴 DEAD - Unreachable or blocked by robots.txt
- ⚫ DISABLED - Disabled in config

---

## PAPERS

| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |
|--------|------|--------|------------|--------------|----------------|-----------|------|-------|
| arxiv | API | HTTP 400 | Disallowed by robots.txt | ❌  | Unknown | N/A (bulk) | 🔴 BLOCKED | None |
| huggingface_papers | web | N/A | N/A | ❌  | N/A | N/A | 🔴 ERROR |  |
| semantic_scholar | API | OK | No robots.txt (allowed) | ✅ HTTP 200 | To be determined | N/A (bulk) | 🟢 VIABLE | None |

## STARTUPS

| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |
|--------|------|--------|------------|--------------|----------------|-----------|------|-------|
| yc_companies | API | OK | Disallowed by robots.txt | ✅ HTTP 200 | To be determined | N/A (bulk) | 🔴 BLOCKED | None |
| huggingface_spaces | API | OK | Allowed | ✅ API accessible | 200+ spaces | N/A (bulk) | 🟢 VIABLE | None |
| crunchbase_public | web | DISABLED | - | - | - | - | ⚫ DISABLED | Disabled in config |

## PRODUCTS

| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |
|--------|------|--------|------------|--------------|----------------|-----------|------|-------|
| producthunt | API | HTTP 404 | Allowed | ❌  | Unknown | N/A (bulk) | 🟡 UNSTABLE | Check API access requirements |
| github_repos | API | OK | No robots.txt (allowed) | ✅ API accessible | 1000+ repos | N/A (bulk) | 🟢 VIABLE | None |

## NEWS

| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |
|--------|------|--------|------------|--------------|----------------|-----------|------|-------|
| techcrunch | RSS | OK | Allowed | ✅ 20 entries, 12 < 24h | ~12-20 items/day | 12/20 < 24h | 🟢 VIABLE | None |
| venturebeat | RSS | HTTP 429 | Allowed | ❌  | Unknown | N/A | 🟡 UNSTABLE | None |
| artificialintelligence_news | RSS | OK | Allowed | ❌ 0 entries, 0 < 24h | ~0-0 items/day | N/A | 🟡 PARSE_FAIL | None |
| theverge_ai | RSS | HTTP 404 | Allowed | ❌  | Unknown | N/A | 🟡 UNSTABLE | None |
| mit_tech_review | RSS | OK | Allowed | ✅ 10 entries, 2 < 24h | ~2-10 items/day | 2/10 < 24h | 🟢 VIABLE | None |

## JOBS

| Source | Type | Status | Robots.txt | Sample Parse | Expected Yield | Freshness | Risk | Notes |
|--------|------|--------|------------|--------------|----------------|-----------|------|-------|
| greenhouse | web | N/A | N/A | ❌  | N/A | N/A | 🔴 ERROR |  |
| lever | web | N/A | N/A | ❌  | N/A | N/A | 🔴 ERROR |  |
| remoteok | API | OK | Allowed | ✅ 100 jobs found | 100+ jobs | N/A (bulk) | 🟢 VIABLE | None |
| remotive | RSS | OK | Allowed | ❌ 0 entries, 0 < 24h | ~0-0 items/day | N/A | 🟡 PARSE_FAIL | None |
| wellfound | web | N/A | N/A | ❌  | N/A | N/A | 🔴 ERROR |  |

---

## Summary

- **Viable**: 6
- **Unstable**: 5
- **Dead/Blocked**: 6
- **Disabled**: 1

## Recommendations

### ❌ Dead/Blocked Sources (Remove or Replace)
- **arxiv** (papers): HTTP 400
- **huggingface_papers** (papers): N/A
- **yc_companies** (startups): OK
- **greenhouse** (jobs): N/A
- **lever** (jobs): N/A
- **wellfound** (jobs): N/A

### ⚠️ Unstable Sources (Monitor Closely)
- **producthunt** (products): 
- **venturebeat** (news): 
- **artificialintelligence_news** (news): 0 entries, 0 < 24h
- **theverge_ai** (news): 
- **remotive** (jobs): 0 entries, 0 < 24h

### ✅ Production Readiness

**6/18 sources are production-ready.**

⚠️ **Action Required**: Replace dead sources and stabilize unstable sources before production deployment.