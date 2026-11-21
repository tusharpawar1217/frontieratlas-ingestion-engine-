# Phase 0 Summary: Audit + Source Viability

**Completed**: 2026-11-21  
**Status**: ✅ COMPLETE

## Deliverables

1. ✅ **docs/audit.md** - Complete v1→v2 audit with prioritized fix list
2. ✅ **scripts/probe_sources.py** - Automated source viability testing
3. ✅ **docs/source_register.md** - Detailed viability report for all 18 sources
4. ✅ **sources.yaml** - External source configuration with risk assessment

---

## Key Findings

### 1. Existing Codebase (v1) Assessment

**Strengths**:
- ✅ Well-structured async architecture with proper separation of concerns
- ✅ Comprehensive pydantic v2 models and validation
- ✅ Multi-tier LLM orchestration with fallback chain (Gemini→Groq→DeepSeek)
- ✅ Token-bucket rate limiting and circuit breakers
- ✅ Entity resolution with deterministic pipeline
- ✅ Good test coverage for implemented features

**Critical Gaps (Blockers for v2)**:
- ❌ **NO EVIDENCE-BASED GROUNDING** - LLM returns values without verbatim quotes
- ❌ **NO PROVENANCE TRACKING** - Missing http_status, fetched_at, content_sha256, extractor type
- ❌ **NO QUALITY GATES** - No validation, audit sampling, or quality reports
- ❌ **NO SELF-AUDIT** - Cannot verify zero-hallucination claim

**Verdict**: Foundation is solid, but **zero-hallucination guarantees are NOT implemented**.

---

### 2. Source Viability Results

**Tested**: 18 sources across 5 verticals

| Status | Count | % | Impact |
|--------|-------|---|--------|
| 🟢 Viable | 6 | 33% | Production ready |
| 🟡 Unstable | 5 | 28% | Needs fixing |
| 🔴 Dead/Blocked | 6 | 33% | Must replace |
| ⚫ Disabled | 1 | 6% | By design |

#### Viable Sources (Production Ready)
1. **Semantic Scholar API** - Papers (500+ expected)
2. **HuggingFace Spaces API** - Startups (200+ expected)
3. **GitHub Repos API** - Products (1000+ expected)
4. **TechCrunch RSS** - News (12/20 items < 24h)
5. **MIT Tech Review RSS** - News (2/10 items < 24h)
6. **RemoteOK API** - Jobs (100+ jobs)

#### Dead/Blocked Sources (Must Replace)
1. **arXiv API** - HTTP 400 + robots.txt disallowed ❌
2. **YC Companies** - robots.txt blocked despite 200 status ❌
3. **Greenhouse/Lever** - Not standalone APIs (need company list) ❌
4. **Wellfound** - Parse error ❌

#### Unstable Sources (Monitor/Fix)
1. **Product Hunt** - HTTP 404
2. **VentureBeat** - HTTP 429 (rate limited)
3. **The Verge AI** - HTTP 404
4. **AI News RSS** - 0 entries parsed
5. **Remotive** - 0 entries parsed

---

### 3. Papers with Code Test

**Task Example**: https://paperswithcode.com/paper/98456

**Result**: 🟢 Site is ALIVE (HTTP 200)
- URL returned 200 OK
- robots.txt allows access
- Site is functional

**Verdict**: Papers with Code is viable but lacks a public API. Can be scraped with Playwright if needed, but **Semantic Scholar provides better structured data** and should be PRIMARY source.

---

### 4. Impact on 1,000-Record Target

**Current Viable Yield**:
```
Papers:   Semantic Scholar (~500)          ✅ Sufficient
Startups: HuggingFace Spaces (~200)        ⚠️  Need 800 more
Products: GitHub Repos (~1000)             ✅ Sufficient
News:     TC + MIT TR (~14/day)            ⚠️  Need 3+ more sources
Jobs:     RemoteOK (~100/day)              ⚠️  Need 2+ more sources
```

**Verdict**: ❌ **INSUFFICIENT for 1,000 unique startups without additional sources**

**Action Plan**:
1. Add 3+ more news RSS sources (Ars Technica, Wired, Reuters) ✅ Added to sources.yaml
2. Add 2+ more job sources (We Work Remotely, Stack Overflow) ✅ Added to sources.yaml
3. Add startup sources (Wikidata SPARQL, Golden, or manual curated list)
4. Fix arXiv or accept Semantic Scholar as PRIMARY papers source

---

## Recommendations

### Immediate Actions (Sprint 1)

1. **Replace Dead Sources** (P0)
   - ✅ Created `sources.yaml` with 3 new news sources (Ars Technica, Wired, Reuters)
   - ✅ Created `sources.yaml` with 2 new job sources (We Work Remotely, Stack Overflow)
   - ⏭️ Need to implement alternative startup sources
   - ⏭️ Document arXiv as blocked, use Semantic Scholar as PRIMARY

2. **Implement Evidence-Based Grounding** (P0 - BLOCKER)
   - Modify `src/llm/prompts.py` to request evidence quotes
   - Rewrite `src/llm/grounding.py` to verify evidence as substring
   - Add `EvidenceField` model to `src/models.py`
   - Write comprehensive evidence verification tests

3. **Add Provenance Tracking** (P0 - BLOCKER)
   - Add `ProvenanceMetadata` to `src/models.py`
   - Track HTTP status, fetched_at, content_sha256 in all crawlers
   - Record extractor type (api/parser/llm:provider:model)
   - Store evidence spans for LLM-extracted fields

4. **Build Quality Gates** (P0 - BLOCKER)
   - Create `src/quality/validate.py` - Schema, grounding, freshness validation
   - Create `src/quality/report.py` - Generate quality_report.md
   - Create `src/quality/audit_sample.py` - Re-fetch and verify 30 records/vertical
   - FAIL the run on gate violations (non-zero exit code)

### Deferred Actions (Sprint 2+)

5. **Missing Core Components** (P1)
   - `src/core/frontier.py` - URL queue abstraction
   - `src/core/ratelimit.py` - Extract from http_client
   - `src/llm/cache.py` - Content-hash LLM caching
   - `src/llm/chaos.py` - Fault injection for testing

6. **Crawler Upgrades** (P1)
   - GitHub URL verification (GET repo, check 200)
   - Evidence tracking for all LLM fields
   - Implement HuggingFace Papers parser
   - Add new sources from sources.yaml

7. **Testing Gaps** (P2)
   - Evidence verification tests
   - 24h filter edge cases (23:59 vs 24:01)
   - Resume from checkpoint
   - Chaos injection tests
   - Sheets cell/row limits

8. **Documentation** (P2)
   - Update README with Phase 0 results
   - Create demo script
   - Create submission checklist
   - Export architecture.pdf

---

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Insufficient sources for 1,000 records | High | Medium | Add sources from sources.yaml |
| arXiv blocked permanently | High | High | Use Semantic Scholar as PRIMARY |
| Evidence grounding not implemented | **CRITICAL** | Certain | Sprint 1 P0 task |
| Provenance tracking missing | **CRITICAL** | Certain | Sprint 1 P0 task |
| No quality gates = unverifiable claims | **CRITICAL** | Certain | Sprint 1 P0 task |
| Rate limit exhaustion | Medium | Medium | Adaptive rate limiting + caching |
| LLM hallucinations | **CRITICAL** | High | Evidence-quote grounding (Sprint 1) |

---

## Next Steps

### Sprint 1 (This Week): Zero-Hallucination Core
**BLOCKERS - Cannot claim zero hallucination without these**

1. ✅ Phase 0 Complete
2. **Evidence-based grounding system** (2 days)
   - Modify prompts to request evidence quotes
   - Rewrite grounding validator to verify substring
   - Add EvidenceField model
   - Write comprehensive tests
3. **Provenance tracking** (1 day)
   - Add ProvenanceMetadata model
   - Track in all crawlers and LLM calls
   - Store in database
4. **Quality gates + self-audit** (2 days)
   - Build validate.py, report.py, audit_sample.py
   - FAIL run on violations
   - Re-fetch sample and verify

### Sprint 2: Production Components
5. Core abstractions (frontier, ratelimit, cache, chaos)
6. Crawler upgrades (GitHub verification, evidence tracking)
7. Implement new sources from sources.yaml
8. Evaluation data + precision/recall metrics

### Sprint 3: Scale & Documentation
9. Complete testing gaps
10. Full documentation
11. Demo script
12. End-to-end validation run

---

## Files Created/Modified in Phase 0

### Created
- ✅ `docs/audit.md` - Complete v1→v2 audit
- ✅ `scripts/probe_sources.py` - Automated viability testing
- ✅ `docs/source_register.md` - Source viability report
- ✅ `sources.yaml` - External source configuration
- ✅ `docs/phase0_summary.md` - This document

### Modified
- None (Phase 0 is read-only assessment)

---

## Conclusion

**Phase 0 is COMPLETE.**

The v1 codebase is well-architected but **lacks the three critical components** required for zero-hallucination guarantees:

1. ❌ Evidence-based grounding
2. ❌ Provenance tracking
3. ❌ Quality gates + self-audit

Source viability testing revealed that **only 33% of sources are production-ready**, requiring either source replacement or fixes.

**Ready to proceed to Sprint 1**: Implement evidence-based grounding, provenance tracking, and quality gates.

**Estimated time to production-ready v2**: 3 weeks (3 sprints as outlined above)
