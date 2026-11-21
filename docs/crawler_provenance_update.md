# Crawler Provenance Tracking Update (v2)

**Status**: 🟢 Papers Crawler COMPLETE  
**Date**: 2026-11-21

## Overview

Updated crawlers to track full provenance metadata for every record, enabling verification of zero-hallucination claims through audit sampling.

---

## What Was Changed

### Papers Crawler (`src/crawlers/papers.py`) ✅

**Changes**:
1. ✅ Import provenance models
2. ✅ Track HTTP status for every API call
3. ✅ Track fetched_at timestamp (UTC)
4. ✅ Calculate content_sha256 hash
5. ✅ Record extractor type ("api" for arXiv)
6. ✅ Create `ProvenanceMetadata` for each paper
7. ✅ Store provenance in `record.meta` using `create_metadata_with_provenance()`
8. ✅ Track GitHub stars fetch timestamp

**Updated Methods**:
- `_fetch_arxiv_category()` - Now returns `List[(paper_data, provenance)]`
- `crawl_arxiv()` - Uses provenance in record creation

**Example Record with Provenance**:
```json
{
  "schemaVersion": "1.0",
  "recordType": "RESEARCH_PAPER",
  "source": {
    "name": "arxiv",
    "url": "http://arxiv.org/abs/2311.12345"
  },
  "content": {
    "data": {
      "title": "Attention Is All You Need",
      "authors": ["Vaswani", "Shazeer", ...],
      "paper_url": "http://arxiv.org/abs/2311.12345",
      "github_url": "https://github.com/tensorflow/tensor2tensor",
      "github_stars": 15234,
      "published_date": "2023-11-15T10:30:00Z",
      "abstract": "..."
    }
  },
  "collectedAt": "2026-11-21T15:30:00Z",
  "meta": {
    "provenance": {
      "http_status": 200,
      "fetched_at": "2026-11-21T15:30:00Z",
      "content_sha256": "abc123def456...",
      "extractor": "api",
      "evidence_spans": [],
      "retry_count": 0
    },
    "category": "cs.AI",
    "github_stars_fetched": true,
    "stars_fetched_at": "2026-11-21T15:30:15Z"
  }
}
```

---

## Provenance Fields Explained

| Field | Type | Purpose | Example |
|-------|------|---------|---------|
| `http_status` | int | HTTP response code (must be 200) | 200 |
| `fetched_at` | datetime | UTC timestamp of fetch | "2026-11-21T15:30:00Z" |
| `content_sha256` | string | SHA-256 hash of source content | "abc123..." (64 chars) |
| `extractor` | string | How data was extracted | "api", "parser", "llm:gemini:gemini-1.5-flash" |
| `evidence_spans` | array | Character spans for LLM evidence | `[{"field": "title", "start": 0, "end": 20, ...}]` |
| `retry_count` | int | Number of retries needed | 0 |

---

## Why This Matters

### Before (v1)
```python
# Record with NO provenance
{
  "source": {"name": "arxiv", "url": "..."},
  "content": {...},
  "meta": {"category": "cs.AI"}
}

# Can't verify:
# - Was HTTP 200?
# - When was it fetched?
# - Content integrity?
# - How was it extracted?
```

### After (v2) ✅
```python
# Record WITH provenance
{
  "source": {...},
  "content": {...},
  "meta": {
    "provenance": {
      "http_status": 200,
      "fetched_at": "2026-11-21T15:30:00Z",
      "content_sha256": "abc123...",
      "extractor": "api"
    }
  }
}

# Can verify:
# ✅ HTTP 200 (not 404/500)
# ✅ When fetched (freshness)
# ✅ Content hasn't changed (hash)
# ✅ How extracted (api/parser/llm)
```

---

## Self-Audit Use Case

With provenance tracking, we can now implement **self-audit sampling**:

```python
# Select 30 random papers
sample = random.sample(all_papers, 30)

for paper in sample:
    # Re-fetch the source URL
    status, content, _ = await http_client.fetch(paper.source.url)
    
    # Verify HTTP 200
    assert status == 200, "Source no longer accessible"
    
    # Verify content integrity (optional - content may have changed)
    current_hash = hashlib.sha256(content.encode()).hexdigest()
    if current_hash != paper.meta.provenance.content_sha256:
        logger.warning("Content changed since fetch")
    
    # Verify title appears in content
    assert paper.content.data.title in content, "Title not found in source"
    
    # Verify authors appear
    for author in paper.content.data.authors:
        assert author in content, f"Author {author} not found"
```

**Result**: Proves that extracted data ACTUALLY came from the source.

---

## Remaining Crawlers to Update

### Priority Order

1. ✅ **Papers Crawler** - DONE (pilot implementation)

2. ⏭️ **News Crawler** (~1 hour)
   - RSS feeds (deterministic)
   - Add provenance for RSS XML fetch
   - Add provenance for full-text fetch (trafilatura)
   - Track extractor: "parser" for RSS, "parser" for trafilatura

3. ⏭️ **Jobs Crawler** (~1 hour)
   - RemoteOK API (deterministic)
   - Add provenance for API responses
   - Track extractor: "api"

4. ⏭️ **Startups Crawler** (~1 hour)
   - HuggingFace Spaces API
   - YC scraping (if implemented)
   - Track extractor: "api" or "parser"

5. ⏭️ **Products Crawler** (~1 hour)
   - GitHub repos API
   - Product Hunt (if implemented)
   - Track extractor: "api"

**Total remaining**: ~4 hours

---

## Pattern to Follow (Copy-Paste Template)

### For API Sources

```python
# 1. Track fetch details
fetched_at = datetime.now(timezone.utc)
status, content, headers = await self.http_client.fetch(url)

# 2. Verify status
if status != 200:
    logger.warning(f"Non-200 status: {status}")
    continue

# 3. Calculate content hash
content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()

# 4. Parse content (your existing logic)
data = parse_api_response(content)

# 5. Create provenance
provenance = ProvenanceMetadata(
    http_status=status,
    fetched_at=fetched_at,
    content_sha256=content_hash,
    extractor="api",  # or "parser" for HTML/RSS
    evidence_spans=[],  # Empty for deterministic extraction
    retry_count=0,
)

# 6. Create record with provenance
meta = create_metadata_with_provenance(
    provenance,
    additional_meta={"any": "extra", "fields": "here"}
)

record = SomeRecord(
    source=SourceInfo(name="source_name", url=url),
    content=SomeContent(data=SomeData(**data)),
    collectedAt=provenance.fetched_at,  # Use provenance timestamp
    meta=meta,  # Include provenance
)
```

### For LLM Extraction (Future)

```python
# Use the orchestrator's extract_with_evidence method
success, cleaned_data, provenance = await orchestrator.extract_with_evidence(
    source_text=content,
    source_url=url,
    record_type="STARTUP",
    prompt=extraction_prompt,
)

# Update provenance with HTTP details
provenance.http_status = status
provenance.fetched_at = fetched_at
provenance.content_sha256 = content_hash

# Create record
meta = create_metadata_with_provenance(provenance)
record = StartupRecord(..., meta=meta)
```

---

## Testing Provenance

### Unit Test Template

```python
def test_crawler_tracks_provenance():
    """Test that crawler creates proper provenance metadata."""
    # Run crawler
    records = await crawler.crawl_source(source_config)
    
    for record in records:
        # Check provenance exists
        assert "provenance" in record.meta
        prov = record.meta["provenance"]
        
        # Check required fields
        assert prov["http_status"] == 200
        assert prov["fetched_at"]  # Not empty
        assert len(prov["content_sha256"]) == 64  # SHA-256 hex
        assert prov["extractor"] in ["api", "parser", "llm:*"]
        assert isinstance(prov["evidence_spans"], list)
        assert isinstance(prov["retry_count"], int)
```

---

## Benefits of Provenance Tracking

1. **Verifiability**: Can re-fetch sources and verify data integrity
2. **Debugging**: Know exactly when/how each record was created
3. **Audit Trail**: Proves data origin for compliance
4. **Quality Control**: Identify stale or broken sources
5. **LLM Accountability**: Track which model extracted which data
6. **Evidence Proof**: Character-level evidence spans for LLM extractions

---

## Next Steps

1. ⏭️ Update news crawler with provenance
2. ⏭️ Update jobs crawler with provenance
3. ⏭️ Update startups crawler with provenance
4. ⏭️ Update products crawler with provenance
5. ⏭️ Write tests for provenance tracking
6. ⏭️ Build self-audit sampling script

**Estimated completion**: Task 6 done in ~4 hours

---

## Files Modified

- ✅ `src/crawlers/papers.py` - Added provenance tracking
- ✅ `docs/crawler_provenance_update.md` - This document

---

**Last Updated**: 2026-11-21 15:45 UTC
