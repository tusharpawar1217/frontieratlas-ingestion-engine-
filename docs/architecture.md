# GraphOne Pipeline Architecture & Scale Strategy

## Executive Summary

This document outlines the architecture for scaling GraphOne from thousands to 500,000+ records, handling tens of thousands of concurrent LLM extractions, and maintaining freshness/dedupe across distributed nodes.

## Current Architecture (1K-10K records)

### Single-Node Design
- **SQLite storage**: Local database with WAL mode
- **Async Python**: asyncio with semaphores (50 concurrent)
- **In-memory rate limiting**: Per-domain token buckets
- **Local dedupe**: URL canonicalization + content hashing

### Strengths
- Simple deployment (no infrastructure)
- Fast development iteration
- Sufficient for initial data collection
- Easy debugging and testing

### Bottlenecks at Scale
- SQLite write contention beyond ~10K writes/sec
- Single-node memory limits for dedupe tracking
- Rate limiter state not shared across workers
- No horizontal scaling capability

---

## Scale Strategy for 500K Records

### 1. Distributed Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Load Balancer / API Gateway           │
└────────────────────────────────┬────────────────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
         ┌────▼────┐       ┌────▼────┐       ┌────▼────┐
         │ Worker 1│       │ Worker 2│  ...  │ Worker N│
         └────┬────┘       └────┬────┘       └────┬────┘
              │                  │                  │
              └──────────────────┼──────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼───┐ ┌─────▼──────┐
              │  Redis    │ │Kafka/ │ │PostgreSQL  │
              │(Rate Lmt) │ │RabbitMQ│ │+ pgvector  │
              │(Dedupe)   │ │(Queue)│ │+ TimescaleDB
              └───────────┘ └───────┘ └────────────┘
```

### Components

**Workers (Stateless)**
- Python async workers in containers (Docker/K8s)
- Auto-scale based on queue depth
- Each worker: 50-100 concurrent tasks
- Graceful shutdown (finish in-flight requests)

**Message Queue (Kafka/RabbitMQ/SQS)**
- URL frontier: pending URLs by domain
- Priority queues: fresh news/jobs prioritized
- Dead letter queue: failed items after retries
- Consumer groups for parallel processing

**Shared State (Redis)**
- Rate limit counters (RPM/TPM per domain)
- Bloom filters for fast dedupe checks
- Circuit breaker states
- Distributed locks for critical sections

**Storage (PostgreSQL)**
- Primary data store with JSONB columns
- Unique constraints on canonical URLs
- Indexes on domain, timestamp, content hash
- TimescaleDB extension for time-series (date filters)

---

## 2. Sitemap & API-Driven URL Discovery

### Problem
Crawling 500K pages by following links is slow and polite crawling (1 req/sec) takes days.

### Solution: Intelligent URL Frontier

**Sitemap Ingestion**
```python
# Parse sitemaps for bulk URL discovery
async def ingest_sitemap(sitemap_url: str):
    urls = await fetch_and_parse_sitemap(sitemap_url)
    # Yields 1,000-100,000 URLs instantly
    await queue.enqueue_batch(urls, priority="normal")
```

**API-First Approach**
- arXiv API: 2,000 papers/minute (paginated)
- GitHub GraphQL: Batch queries for 100 repos/request
- RemoteOK API: All jobs in single JSON response
- RSS feeds: 50-500 articles per feed

**Estimated Time to 500K**
- APIs: 10,000-50,000 records/hour
- Sitemaps: 5,000-10,000 URLs/hour (with processing)
- Total: **10-50 hours** vs weeks of link-following

---

## 3. Per-Domain Politeness & Sharding

### Domain-Based Sharding

**Worker Assignment**
```python
# Hash domain to worker shard
worker_id = hash(domain) % num_workers
queue_name = f"crawl-worker-{worker_id}"
```

**Benefits**
- Each worker handles disjoint set of domains
- No coordination needed for per-domain rate limits
- Scale by adding workers (rebalance shards)

### Rate Limit Architecture

**Centralized Rate Limiter (Redis)**
```python
# Atomic rate limit check with Lua script
RATE_LIMIT_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local current = redis.call('INCR', key)
if current == 1 then
    redis.call('EXPIRE', key, window)
end
if current > limit then
    return 0  -- Rate limited
end
return 1  -- Allowed
"""

# Check before each request
allowed = await redis.eval(
    RATE_LIMIT_SCRIPT,
    keys=[f"rate:{domain}:minute"],
    args=[rpm_limit, 60]
)
```

**Token Bucket in Redis**
```python
# Token bucket with sorted sets
await redis.zadd(
    f"tokens:{domain}",
    {timestamp: token_count}
)
# Remove old tokens
await redis.zremrangebyscore(
    f"tokens:{domain}",
    0, time.time() - 60
)
```

### Adaptive Concurrency

**Per-Domain Tuning**
- Start: 1 req/sec (polite default)
- Monitor: 429 errors, response times
- Increase: Double concurrency if no errors for 5 min
- Decrease: Halve on 429, backoff on 503
- Cap: Never exceed config limit (e.g., 10/sec for arXiv)

---

## 4. 413/429 Strategy at Scale

### Problem
With 10,000 concurrent LLM requests across 3 providers:
- 429 rate limits hit frequently
- 413 context overflows on long articles
- Provider failures cascade

### Solution: Central Rate Limit Service

**Architecture**
```
Workers ──request──> Rate Limit Service ──approve──> LLM Provider
                          │
                      Redis (state)
```

**Service Features**
- **Token bucket pools** per provider (RPM/TPM)
- **Queue with backpressure**: Workers wait for tokens
- **Adaptive batching**: Combine small requests
- **Circuit breakers**: Auto-disable failing providers
- **Fallback routing**: Gemini full → Groq retry → DeepSeek

### Token-Aware Chunking Pipeline

**Stage 1: Size Check**
```python
estimated_tokens = count_tokens(content)
if estimated_tokens > provider.max_tokens:
    # Chunk before submitting
    content = chunk_intelligently(content, provider.max_tokens)
```

**Stage 2: 413 Handler**
```python
if response.status == 413:
    # Halve content and retry
    content = chunk_more_aggressively(content, limit // 2)
    await retry_with_backoff()
```

**Stage 3: Fallback to Next Provider**
```python
if all_retries_exhausted:
    # Move to next provider (may have larger context)
    provider = next_in_chain(current_provider)
    await retry_with_new_provider(content, provider)
```

### Response Caching

**Content-Addressed Cache (Redis)**
```python
cache_key = f"llm:{sha256(content)}:{prompt_type}"
cached = await redis.get(cache_key)
if cached:
    return json.loads(cached)

# Call LLM
response = await llm.generate(content, prompt)

# Cache for 7 days
await redis.setex(cache_key, 604800, json.dumps(response))
```

**Benefits**
- Duplicate content (e.g., syndicated news) processed once
- Retries after 429 hit cache instead of provider
- Estimated 30-50% cache hit rate

---

## 5. Freshness & Dedupe in Distributed Systems

### Atomic URL Dedupe

**Problem**: Two workers fetch same URL simultaneously

**Solution: Redis SETNX (Set if Not eXists)**
```python
canonical_url = canonicalize(url)
content_hash = sha256(content)

# Atomic check-and-set
is_new = await redis.set(
    f"seen:{canonical_url}",
    content_hash,
    nx=True,  # Only set if not exists
    ex=86400 * 30  # TTL: 30 days
)

if not is_new:
    # Already processed, skip
    return
```

**PostgreSQL Alternative**
```sql
-- Unique constraint prevents duplicates
CREATE UNIQUE INDEX idx_unique_url ON seen_urls(canonical_url);

-- Insert with conflict handling
INSERT INTO seen_urls (canonical_url, content_hash, first_seen)
VALUES ($1, $2, NOW())
ON CONFLICT (canonical_url) DO NOTHING;
```

### Content Dedupe (Near-Duplicates)

**Bloom Filter (Fast Negative Check)**
```python
# Check if content hash might exist
if not await bloom.contains(content_hash):
    # Definitely new
    await process_content(content)
    await bloom.add(content_hash)
else:
    # Maybe duplicate, check database
    exists = await db.query(
        "SELECT 1 FROM seen_content WHERE content_hash = $1",
        content_hash
    )
    if not exists:
        await process_content(content)
```

### First-Seen Tracking (24h Filter)

**Time-Series Table (TimescaleDB)**
```sql
-- Hypertable for time-based queries
CREATE TABLE first_seen (
    url TEXT,
    canonical_url TEXT,
    content_hash TEXT,
    first_seen TIMESTAMPTZ NOT NULL,
    last_seen TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('first_seen', 'first_seen');

-- Query: URLs first seen in last 24h
SELECT * FROM first_seen
WHERE first_seen > NOW() - INTERVAL '24 hours';
```

---

## 6. Storage Architecture

### PostgreSQL (System of Record)

**Schema Design**
```sql
CREATE TABLE records (
    id BIGSERIAL PRIMARY KEY,
    record_type TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    content JSONB NOT NULL,
    content_hash TEXT,
    collected_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_type_date (record_type, collected_at DESC),
    INDEX idx_content_hash (content_hash),
    INDEX idx_source (source_name, collected_at DESC)
);

-- GIN index for JSONB queries
CREATE INDEX idx_content_gin ON records USING GIN (content);

-- Partial index for recent records
CREATE INDEX idx_recent ON records (collected_at)
WHERE collected_at > NOW() - INTERVAL '7 days';
```

**Why PostgreSQL?**
- JSONB: Flexible schema for evolving data
- ACID: Ensure no duplicate URLs
- Performance: 10,000+ writes/sec with proper indexing
- pgvector: Semantic search on embeddings (future)

### pgvector (Semantic Search)

**Entity Embeddings**
```sql
-- Add vector column
ALTER TABLE entities ADD COLUMN embedding vector(1536);

-- Create HNSW index for fast similarity search
CREATE INDEX ON entities USING hnsw (embedding vector_cosine_ops);

-- Find similar entities
SELECT canonical_name, embedding <=> $1 AS distance
FROM entities
ORDER BY distance LIMIT 10;
```

**Use Cases**
- Fuzzy entity matching beyond string similarity
- Semantic deduplication (similar but not identical content)
- Related entity discovery

### Neo4j (Graph Layer)

**Relationship Modeling**
```cypher
// Startup -> Product relationship
CREATE (s:Startup {name: "OpenAI"})-[:CREATED]->(p:Product {name: "ChatGPT"})

// Research Paper -> Startup (author affiliation)
CREATE (paper:Paper {title: "GPT-4"})<-[:AUTHORED]-(s:Startup {name: "OpenAI"})

// Startup -> Funding event
CREATE (s:Startup {name: "Anthropic"})-[:RAISED {amount: "450M", date: "2023-05"}]->(r:FundingRound)

// Query: All products by startups funded in 2024
MATCH (s:Startup)-[:RAISED {date: "2024-*"}]->(r)
MATCH (s)-[:CREATED]->(p:Product)
RETURN s.name, COLLECT(p.name) AS products
```

**Why Graph DB?**
- Natural fit for relationship-heavy data
- Traverse networks (startups → founders → other startups)
- Pattern matching (companies with AI products and papers)

### Justification Summary

| Component | Purpose | Scale Limit | Fallback |
|-----------|---------|-------------|----------|
| PostgreSQL | Primary storage, dedupe | 100K writes/sec | Sharding by domain |
| Redis | Rate limits, bloom filters | 1M ops/sec | Redis Cluster |
| pgvector | Semantic entity matching | 10M vectors | Dedicated instance |
| Neo4j | Relationship queries | 1B nodes | Graph sharding |

---

## 7. Monitoring & Observability

### Key Metrics

**Throughput**
- URLs processed/min
- Records ingested/min
- LLM requests/min per provider

**Quality**
- Grounding validation pass rate
- Entity resolution method distribution
- Date extraction confidence levels

**Reliability**
- 429 rate limit hit rate
- Circuit breaker triggers
- Failed records by error type

### Alerting

**Critical Alerts**
- All LLM providers in circuit-open state
- Database write errors > 1%
- Dedupe check failures (Redis down)

**Warning Alerts**
- Grounding validation pass rate < 90%
- 429 rate limit hits > 10% of requests
- Queue depth > 10,000 URLs

---

## 8. Cost Estimation (500K records)

### LLM Costs (Worst Case: All Records Need Extraction)

**Assumptions**
- 500K records × 2,000 tokens/record = 1B tokens
- Gemini Flash: $0.075 / 1M tokens
- Groq: Free (rate-limited)
- DeepSeek: $0.14 / 1M tokens

**Cost Breakdown**
- Gemini: 1B tokens × $0.075 = **$75**
- Groq fallback (10%): Free
- DeepSeek fallback (5%): 50M × $0.14 = **$7**
- **Total: ~$82**

**With Caching (50% hit rate)**
- Actual cost: **$41**

### Infrastructure Costs (AWS, monthly)

- **Workers**: 10× t3.medium = $300
- **PostgreSQL**: RDS db.r5.xlarge = $540
- **Redis**: ElastiCache r5.large = $160
- **Kafka**: MSK 3-broker = $450
- **Storage**: 100GB EBS + S3 = $30
- **Total: ~$1,480/month**

### One-Time Cost for 500K Ingestion

- LLM: $41
- Infrastructure (1 week): $1,480 / 4 = **$370**
- **Total: ~$411**

---

## 9. Deployment Architecture

### Kubernetes (Recommended)

```yaml
# Worker deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: graphone-worker
spec:
  replicas: 10  # Autoscale 5-50
  template:
    spec:
      containers:
      - name: worker
        image: graphone-pipeline:latest
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        resources:
          requests:
            memory: "2Gi"
            cpu: "1000m"
          limits:
            memory: "4Gi"
            cpu: "2000m"
```

### Terraform (Infrastructure as Code)

```hcl
# PostgreSQL RDS
resource "aws_db_instance" "postgres" {
  identifier = "graphone-db"
  engine = "postgres"
  engine_version = "15.3"
  instance_class = "db.r5.xlarge"
  allocated_storage = 100
  
  # Extensions
  parameters = {
    "shared_preload_libraries" = "pg_stat_statements,pgvector"
  }
}

# Redis ElastiCache
resource "aws_elasticache_cluster" "redis" {
  cluster_id = "graphone-redis"
  engine = "redis"
  node_type = "cache.r5.large"
  num_cache_nodes = 1
}
```

---

## Conclusion

This architecture scales GraphOne from 1K to 500K+ records by:

1. **Distributing work** across stateless workers with message queues
2. **Centralizing state** in Redis (rate limits, dedupe) and PostgreSQL (storage)
3. **Prioritizing APIs** over scraping for bulk acquisition
4. **Handling 429/413** with adaptive rate limiting and intelligent chunking
5. **Ensuring freshness** with atomic dedupe and time-series queries
6. **Choosing fit-for-purpose storage**: PostgreSQL + pgvector + Neo4j

**Estimated Performance**: 10,000-50,000 records/hour with $400 one-time cost.
