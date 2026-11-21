# GraphOne Pipeline v1 → v2 Audit

**Audit Date**: 2024-11-21  
**Auditor**: Principal Data Engineer  
**Goal**: Upgrade to production-grade v2 with zero-hallucination guarantees

## Executive Summary

The v1 implementation provides a solid foundation with async crawling, multi-tier LLM orchestration, entity resolution, and Google Sheets export. However, it **lacks critical production requirements**:

❌ **NO EVIDENCE-BASED GROUNDING** - LLM extractions not verified against source text  
❌ **NO PROVENANCE TRACKING** - Missing http_status, fetched_at, content_sha256, extractor type  
❌ **NO QUALITY GATES** - No validation, audit sampling, or quality reports  
❌ **MISSING COMPONENTS** - No frontier, ratelimit, cache, chaos testing, or source viability probe  
❌ **INCOMPLETE TESTING** - Tests exist but don't cover critical v2 requirements  

**Verdict**: Code is structurally sound but needs significant upgrades for production zero-hallucination guarantees.

---

## What Exists (v1 Implementation)

### ✅ Core Infrastructure
| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Config Management | `src/config.py` | ✅ Working | YAML + env settings, needs sources.yaml split |
| Logging | `src/logging_setup.py` | ✅ Working | Loguru-based |
| Data Models | `src/models.py` | ⚠️ Partial | Has schemas but missing provenance fields |
| HTTP Client | `src/core/http_client.py` | ✅ Working | Token bucket rate limiting, robots.txt, retries |
| Browser | `src/core/browser.py` | ✅ Working | Playwright async with resource blocking |
| Dedupe | `src/core/dedupe.py` | ✅ Working | URL canonicalization, content hashing |
| Storage | `src/core/storage.py` | ✅ Working | SQLite with WAL, needs provenance tables |

### ✅ Data Acquisition
| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Papers Crawler | `src/crawlers/papers.py` | ⚠️ Partial | arXiv works, needs GitHub verification |
| Startups Crawler | `src/crawlers/startups.py` | ⚠️ Partial | YC + HF Spaces, needs evidence tracking |
| Products Crawler | `src/crawlers/products.py` | ⚠️ Partial | PH + GitHub, needs evidence |
| News Crawler | `src/crawlers/news.py` | ⚠️ Partial | RSS + trafilatura, needs 24h strict |
| Jobs Crawler | `src/crawlers/jobs.py` | ⚠️ Partial | RemoteOK works, needs evidence |
| Date Parsing | `src/dates.py` | ✅ Working | Priority cascade implemented |

### ✅ LLM Pipeline
| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Orchestrator | `src/llm/orchestrator.py` | ✅ Working | 3-tier fallback with circuit breakers |
| Providers | `src/llm/providers.py` | ✅ Working | Gemini, Groq, DeepSeek |
| Chunking | `src/llm/chunking.py` | ✅ Working | Token-aware with tiktoken |
| Prompts | `src/llm/prompts.py` | ⚠️ Needs Upgrade | Anti-hallucination prompts but NO evidence quotes |
| Grounding | `src/llm/grounding.py` | ⚠️ Weak | Fuzzy matching only, no evidence verification |

### ✅ Entity Resolution & Export
| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Entity Resolver | `src/resolver/entity_resolver.py` | ✅ Working | Deterministic pipeline with seed data |
| Sheets Exporter | `src/export/sheets.py` | ✅ Working | 6 tabs with batch writes |

### ✅ Testing
| Component | Files | Status | Notes |
|-----------|-------|--------|-------|
| Date Tests | `tests/test_dates.py` | ✅ Working | Comprehensive |
| Dedupe Tests | `tests/test_dedupe.py` | ✅ Working | Good coverage |
| Entity Tests | `tests/test_entity_resolver.py` | ✅ Working | Including false positives |
| Grounding Tests | `tests/test_grounding.py` | ⚠️ Partial | Needs evidence verification |
| Chunking Tests | `tests/test_chunking.py` | ✅ Working | Token budget property test |

---

## What's Missing (v2 Requirements)

### ❌ CRITICAL: Evidence-Based Grounding System
**Priority: P0 (BLOCKER)**

**Current**: LLM returns `{"entityName": "OpenAI"}` and grounding validator checks if "OpenAI" appears in source text using fuzzy matching.

**Required**: LLM must return:
```json
{
  "entityName": {
    "value": "OpenAI",
    "evidence": "OpenAI announced today"
  }
}
```

Code must:
1. Verify `evidence` is a verbatim substring of normalized source text
2. Verify `value` is consistent with `evidence`
3. Set field to null if verification fails
4. Reject record if REQUIRED field fails

**Files to Create/Modify**:
- `src/llm/prompts.py` - Add evidence-quote prompt format
- `src/llm/grounding.py` - Rewrite to verify evidence quotes
- `src/models.py` - Add `EvidenceField` model
- `tests/test_grounding.py` - Add evidence verification tests

---

### ❌ CRITICAL: Provenance Tracking
**Priority: P0 (BLOCKER)**

**Required**: Every record must have in `meta`:
```json
{
  "meta": {
    "http_status": 200,
    "fetched_at": "2024-11-21T10:30:00Z",
    "content_sha256": "abc123...",
    "extractor": "llm:gemini:gemini-1.5-flash",
    "evidence_spans": [
      {"field": "entityName", "start": 45, "end": 52, "text": "OpenAI"}
    ]
  }
}
```

**Files to Create/Modify**:
- `src/models.py` - Add `ProvenanceMetadata` model
- `src/crawlers/*.py` - Track HTTP status, fetched_at, content hash
- `src/llm/orchestrator.py` - Record extractor type
- `src/core/storage.py` - Add provenance columns

---

### ❌ CRITICAL: Quality Gates & Self-Audit
**Priority: P0 (BLOCKER)**

**Missing**:
- `src/quality/validate.py` - Schema, grounding, freshness validation
- `src/quality/report.py` - Generate `docs/quality_report.md`
- `src/quality/audit_sample.py` - Re-fetch and verify 30 records/vertical
- Quality gates that FAIL the run on violations

**Impact**: No way to verify zero hallucination claim

---

### ❌ HIGH: Missing Core Components
**Priority: P1**

| Component | Status | Impact |
|-----------|--------|--------|
| `src/core/frontier.py` | ❌ Missing | No URL queue abstraction for scale |
| `src/core/ratelimit.py` | ❌ Missing | Rate limiting mixed in http_client |
| `src/llm/cache.py` | ❌ Missing | No content-hash LLM result caching |
| `src/llm/chaos.py` | ❌ Missing | Can't demonstrate fault tolerance |
| `scripts/probe_sources.py` | ❌ Missing | No source viability checking |
| `sources.yaml` | ❌ Missing | Sources hardcoded in config.yaml |

---

### ❌ HIGH: Incomplete Crawlers
**Priority: P1**

**Papers Crawler** (`src/crawlers/papers.py`):
- ✅ arXiv API works
- ❌ No GitHub URL verification (just extracted, not verified 200)
- ❌ No stars_fetched_at timestamp
- ❌ HuggingFace Papers not implemented
- ❌ Semantic Scholar not implemented

**All Crawlers**:
- ❌ No evidence tracking for LLM-extracted fields
- ❌ No provenance metadata
- ❌ No per-record extractor type

---

### ❌ MEDIUM: Testing Gaps
**Priority: P2**

Missing test coverage:
- Evidence-quote verification
- Provenance tracking
- Quality gates
- 24h filter edge cases (23:59 vs 24:01)
- Resume from checkpoint
- Chaos injection
- Sheets cell/row limits

---

### ❌ MEDIUM: Documentation Gaps
**Priority: P2**

**Missing**:
- `docs/source_register.md` - Source viability table
- `docs/quality_report.md` - Run results and gates
- `data/eval/entity_pairs.csv` - Resolver evaluation data
- Demo script
- Submission checklist
- Source risk matrix in architecture.md

---

## Phase 0 Results: Source Viability Probe

**Status**: ✅ COMPLETE  
**Date**: 2026-11-21

### Probe Results Summary
- **Tested**: 18 sources across 5 verticals
- **Viable**: 6 sources (33%)
- **Unstable**: 5 sources (28%)
- **Dead/Blocked**: 6 sources (33%)
- **Disabled**: 1 source (6%)

### Critical Findings

#### 🔴 BLOCKED/DEAD Sources (Must Replace)
1. **arXiv API** - HTTP 400 + robots.txt disallowed
   - **Impact**: PRIMARY papers source blocked
   - **Action**: Use Semantic Scholar API (already tested ✅) + HuggingFace Papers
   
2. **YC Companies API** - Blocked by robots.txt despite 200 status
   - **Impact**: PRIMARY startups source blocked
   - **Action**: Switch to web scraping YC public directory with proper politeness
   
3. **Greenhouse/Lever** - URL pattern requires company names (not standalone APIs)
   - **Impact**: Job boards not viable without company list
   - **Action**: Remove or implement with known AI company list
   
4. **Wellfound** - Parse error (None type)
   - **Impact**: Jobs source unusable
   - **Action**: Fix URL parsing or remove

#### 🟡 UNSTABLE Sources (Monitor/Fix)
1. **Product Hunt API** - HTTP 404
   - **Action**: Verify API endpoint or switch to web scraping
   
2. **VentureBeat RSS** - HTTP 429 (rate limited during probe)
   - **Action**: Add retry logic, reduce probe frequency
   
3. **AI News RSS** - 0 entries parsed
   - **Action**: Inspect feed format, may be empty or malformed
   
4. **The Verge AI RSS** - HTTP 404
   - **Action**: Verify RSS URL, may have changed
   
5. **Remotive RSS** - 0 entries parsed
   - **Action**: Inspect feed format

#### ✅ VIABLE Sources (Production Ready)
1. **Semantic Scholar API** - Papers ✅
2. **HuggingFace Spaces API** - Startups ✅
3. **GitHub Repos API** - Products ✅
4. **TechCrunch RSS** - News ✅ (12/20 items < 24h)
5. **MIT Tech Review RSS** - News ✅ (2/10 items < 24h)
6. **RemoteOK API** - Jobs ✅ (100 jobs found)

### Papers with Code Test
**URL**: https://paperswithcode.com/paper/98456  
**Status**: 🟢 200 OK (site is alive)  
**Verdict**: Site works but lacks public API. Can scrape with Playwright if needed, but Semantic Scholar provides better structured data.

### Impact on 1,000-Record Target

**Current Viable Yield Estimate**:
- Papers: Semantic Scholar API (~500+) ✅
- Startups: HuggingFace Spaces (~200) ⚠️ (need more sources)
- Products: GitHub Repos (~1000) ✅
- News: TechCrunch + MIT Tech Review (~14 items/day) ⚠️ (need more sources)
- Jobs: RemoteOK (~100) ⚠️ (need more sources)

**Verdict**: ❌ **INSUFFICIENT for production targets without source replacement.**

---

## Prioritized Fix List (Updated with Phase 0 Results)

### Sprint 1: Zero-Hallucination Core + Critical Source Fixes (Week 1)
**BLOCKERS - Cannot proceed to production without these**

1. ✅ **Phase 0 Complete**: Source viability probe and register
2. **Replace dead sources** (P0):
   - Fix arXiv API implementation (check API format, respect robots.txt)
   - Add alternative papers sources (Semantic Scholar ✅, HuggingFace Papers)
   - Fix YC scraping with proper robots.txt compliance
   - Add more news sources to replace dead RSS feeds
   - Add more jobs sources (We Work Remotely, Hacker News Who's Hiring)
3. **Evidence-based grounding** (P0) - Rewrite prompts + grounding validator
4. **Provenance tracking** (P0) - Add to models + storage
5. **Quality gates** (P0) - validate.py, report.py, audit_sample.py
1. **Evidence-based grounding** - Rewrite prompts + grounding validator
2. **Provenance tracking** - Add to models + storage
3. **Quality gates** - validate.py, report.py, audit_sample.py
4. **Source probe** - scripts/probe_sources.py + source_register.md

### Sprint 2: Production Components (Week 2)
5. **Core abstractions** - frontier.py, ratelimit.py, cache.py
6. **Crawler upgrades** - Evidence tracking, GitHub verification
7. **Chaos testing** - chaos.py + --chaos flag
8. **Evaluation data** - entity_pairs.csv + precision/recall

### Sprint 3: Scale & Documentation (Week 3)
9. **sources.yaml** - Externalize source configs
10. **Testing gaps** - Evidence tests, edge cases, limits
11. **Documentation** - Complete all docs, demo script
12. **Quality validation** - End-to-end run with all gates

---

## Risk Assessment

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Dead sources (Papers with Code) | High | Confirmed | Already documented, using arXiv |
| ToS violations | Critical | Medium | Source probe + legal review |
| LLM hallucinations | Critical | High | Evidence-quote grounding (this audit) |
| Rate limit exhaustion | Medium | Medium | Adaptive rate limiting + caching |
| 24h filter failures | High | Low | Property tests + audit sampling |

---

## Code Quality Assessment

### Strengths
- ✅ Well-structured async code
- ✅ Proper use of pydantic v2
- ✅ Comprehensive rate limiting
- ✅ Good test coverage for v1 features
- ✅ Clean separation of concerns

### Weaknesses
- ❌ No evidence verification (critical flaw)
- ❌ Missing provenance tracking
- ❌ No quality gates or validation
- ❌ Hardcoded configurations
- ❌ No fault injection testing

---

## Recommendation

**Proceed with v2 upgrade following the prioritized fix list.**

The v1 codebase is solid enough to build on, but the **evidence-based grounding and provenance tracking are non-negotiable blockers** that must be addressed before any production use.

Estimated effort: **3 weeks** with the prioritized sprint plan above.

---

## Next Steps

1. ✅ **Phase 0**: Create `scripts/probe_sources.py` and `docs/source_register.md`
2. **Phase 1**: Evidence-based grounding system
3. **Phase 2**: Provenance tracking
4. **Phase 3**: Quality gates and self-audit
5. **Phase 4**: Complete remaining components
6. **Phase 5**: Full integration test and demo
