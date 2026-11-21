"""
Pydantic models for GraphOne pipeline data structures.
All records follow the schema specification with validation.

v2 additions:
- EvidenceField: LLM-extracted values with verbatim evidence quotes
- ProvenanceMetadata: HTTP status, content hash, extractor tracking
- EvidenceSpan: Character-level evidence location tracking
"""
from datetime import datetime
from typing import Any, Literal, Optional
from enum import Enum
import hashlib

from pydantic import BaseModel, Field, HttpUrl, field_validator, ConfigDict


# Schema version constant
SCHEMA_VERSION = "1.0"


class EvidenceField(BaseModel):
    """
    A field value with evidence quote from source text.
    
    The LLM must return both the extracted value and a verbatim quote
    from the source text that supports it. The grounding validator
    verifies the evidence is a substring of the source.
    """
    value: Any = Field(..., description="Extracted value")
    evidence: str = Field(..., description="Verbatim quote from source text supporting this value")
    
    model_config = ConfigDict(extra="forbid")


class EvidenceSpan(BaseModel):
    """
    Character-level span for evidence location in source text.
    """
    field: str = Field(..., description="Field name this evidence supports")
    start: int = Field(..., description="Start character index in source text")
    end: int = Field(..., description="End character index in source text")
    text: str = Field(..., description="The evidence text (for verification)")
    
    model_config = ConfigDict(extra="forbid")


class ExtractorType(str, Enum):
    """Type of extractor used."""
    API = "api"  # Direct API response
    PARSER = "parser"  # Deterministic parsing (CSS selectors, JSON-LD, etc.)
    LLM = "llm"  # LLM extraction (format: "llm:provider:model")


class ProvenanceMetadata(BaseModel):
    """
    Provenance tracking for record verification.
    
    Every record must have this metadata to prove:
    1. The source URL returned HTTP 200
    2. When it was fetched
    3. Content integrity (sha256 hash)
    4. What extraction method was used
    5. Evidence locations for LLM-extracted fields
    """
    http_status: int = Field(..., description="HTTP status code (must be 200 for valid records)")
    fetched_at: datetime = Field(..., description="UTC timestamp when content was fetched")
    content_sha256: str = Field(..., description="SHA-256 hash of source content (for verification)")
    extractor: str = Field(..., description="Extraction method: api, parser, or llm:provider:model")
    evidence_spans: list[EvidenceSpan] = Field(
        default_factory=list,
        description="Character spans for evidence (LLM-extracted fields only)"
    )
    retry_count: int = Field(default=0, description="Number of retries needed")
    processing_time_ms: Optional[float] = Field(None, description="Processing time in milliseconds")
    
    model_config = ConfigDict(extra="forbid")
    
    @classmethod
    def from_fetch(
        cls,
        http_status: int,
        fetched_at: datetime,
        content: str,
        extractor: str,
        evidence_spans: Optional[list[EvidenceSpan]] = None,
        retry_count: int = 0,
        processing_time_ms: Optional[float] = None,
    ) -> "ProvenanceMetadata":
        """
        Create provenance metadata from a fetch operation.
        
        Args:
            http_status: HTTP status code
            fetched_at: Fetch timestamp
            content: Source content
            extractor: Extractor identifier
            evidence_spans: Evidence locations (optional)
            retry_count: Retry count
            processing_time_ms: Processing time
            
        Returns:
            ProvenanceMetadata instance
        """
        content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
        
        return cls(
            http_status=http_status,
            fetched_at=fetched_at,
            content_sha256=content_hash,
            extractor=extractor,
            evidence_spans=evidence_spans or [],
            retry_count=retry_count,
            processing_time_ms=processing_time_ms,
        )


class PricingModel(str, Enum):
    """Pricing models for products."""
    FREE = "FREE"
    FREEMIUM = "FREEMIUM"
    PAID = "PAID"
    ENTERPRISE = "ENTERPRISE"


class DateConfidence(str, Enum):
    """Confidence levels for parsed dates."""
    HIGH = "high"  # From structured metadata
    MEDIUM = "medium"  # From visible text parsing
    HEURISTIC = "heuristic"  # From first-seen tracking


class DateSource(str, Enum):
    """Source of date information."""
    JSON_LD = "json_ld"
    OPENGRAPH = "opengraph"
    TIME_ELEMENT = "time_element"
    RSS_PUBDATE = "rss_pubdate"
    VISIBLE_TEXT = "visible_text"
    HTTP_HEADER = "http_header"
    FIRST_SEEN = "first_seen"


class SourceInfo(BaseModel):
    """Source metadata for a record."""
    name: str = Field(..., description="Name of the data source")
    url: str = Field(..., description="URL that was fetched (must return HTTP 200)")
    
    model_config = ConfigDict(extra="forbid")


# Helper function to create metadata dict with provenance
def create_metadata_with_provenance(
    provenance: ProvenanceMetadata,
    additional_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Create a metadata dictionary with provenance tracking.
    
    Args:
        provenance: Provenance metadata
        additional_meta: Additional metadata fields
        
    Returns:
        Combined metadata dictionary
    """
    meta = {
        "provenance": provenance.model_dump(mode="json"),
    }
    
    if additional_meta:
        meta.update(additional_meta)
    
    return meta


class StartupData(BaseModel):
    """Startup-specific data fields."""
    entityName: str = Field(..., description="Name of the startup entity")
    employeeCount: Optional[int] = Field(None, description="Number of employees")
    
    model_config = ConfigDict(extra="forbid")


class StartupContent(BaseModel):
    """Content wrapper for startup data."""
    data: StartupData
    
    model_config = ConfigDict(extra="forbid")


class StartupRecord(BaseModel):
    """Complete startup record schema."""
    schemaVersion: str = Field(default=SCHEMA_VERSION, description="Schema version")
    recordType: Literal["STARTUP"] = Field(default="STARTUP", description="Record type identifier")
    source: SourceInfo
    content: StartupContent
    collectedAt: datetime = Field(..., description="Collection timestamp in ISO-8601 UTC")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(extra="forbid")
    
    @field_validator("collectedAt", mode="before")
    @classmethod
    def parse_collected_at(cls, v):
        """Ensure collectedAt is a datetime object."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class ProductData(BaseModel):
    """Product-specific data fields."""
    startupName: str = Field(..., description="Name of the startup that created the product")
    productName: Optional[str] = Field(None, description="Name of the product")
    pricingModel: Optional[PricingModel] = Field(None, description="Pricing model")
    
    model_config = ConfigDict(extra="forbid")


class ProductContent(BaseModel):
    """Content wrapper for product data."""
    data: ProductData
    
    model_config = ConfigDict(extra="forbid")


class ProductRecord(BaseModel):
    """Complete product record schema."""
    schemaVersion: str = Field(default=SCHEMA_VERSION, description="Schema version")
    recordType: Literal["PRODUCT"] = Field(default="PRODUCT", description="Record type identifier")
    source: SourceInfo
    content: ProductContent
    collectedAt: datetime = Field(..., description="Collection timestamp in ISO-8601 UTC")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(extra="forbid")
    
    @field_validator("collectedAt", mode="before")
    @classmethod
    def parse_collected_at(cls, v):
        """Ensure collectedAt is a datetime object."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class ResearchPaperData(BaseModel):
    """Research paper-specific data fields."""
    title: str = Field(..., description="Paper title")
    authors: list[str] = Field(default_factory=list, description="List of authors")
    paper_url: str = Field(..., description="URL to the paper")
    github_url: Optional[str] = Field(None, description="Associated GitHub repository URL")
    github_stars: Optional[int] = Field(None, description="GitHub stars count (from API only)")
    published_date: Optional[str] = Field(None, description="Publication date in ISO-8601 format")
    abstract: Optional[str] = Field(None, description="Paper abstract")
    
    model_config = ConfigDict(extra="forbid")


class ResearchPaperContent(BaseModel):
    """Content wrapper for research paper data."""
    data: ResearchPaperData
    
    model_config = ConfigDict(extra="forbid")


class ResearchPaperRecord(BaseModel):
    """Complete research paper record schema."""
    schemaVersion: str = Field(default=SCHEMA_VERSION, description="Schema version")
    recordType: Literal["RESEARCH_PAPER"] = Field(default="RESEARCH_PAPER", description="Record type identifier")
    source: SourceInfo
    content: ResearchPaperContent
    collectedAt: datetime = Field(..., description="Collection timestamp in ISO-8601 UTC")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(extra="forbid")
    
    @field_validator("collectedAt", mode="before")
    @classmethod
    def parse_collected_at(cls, v):
        """Ensure collectedAt is a datetime object."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class JobData(BaseModel):
    """Job posting-specific data fields."""
    company: str = Field(..., description="Company name (canonical)")
    title: str = Field(..., description="Job title")
    date: str = Field(..., description="Posting date in ISO-8601 format")
    is_remote: bool = Field(..., description="Whether the job is remote")
    role_family: Optional[str] = Field(None, description="Role family/category")
    location: Optional[str] = Field(None, description="Job location")
    
    model_config = ConfigDict(extra="forbid")


class JobContent(BaseModel):
    """Content wrapper for job data."""
    data: JobData
    
    model_config = ConfigDict(extra="forbid")


class JobRecord(BaseModel):
    """Complete job record schema."""
    schemaVersion: str = Field(default=SCHEMA_VERSION, description="Schema version")
    recordType: Literal["JOB"] = Field(default="JOB", description="Record type identifier")
    source: SourceInfo
    content: JobContent
    collectedAt: datetime = Field(..., description="Collection timestamp in ISO-8601 UTC")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(extra="forbid")
    
    @field_validator("collectedAt", mode="before")
    @classmethod
    def parse_collected_at(cls, v):
        """Ensure collectedAt is a datetime object."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class NewsData(BaseModel):
    """News article-specific data fields."""
    title: str = Field(..., description="Article title")
    url: str = Field(..., description="Article URL")
    source_name: str = Field(..., description="News source name")
    published_at: str = Field(..., description="Publication date in ISO-8601 UTC")
    full_text: Optional[str] = Field(None, description="Extracted full text content")
    summary: Optional[str] = Field(None, description="Article summary")
    date_source: DateSource = Field(..., description="Source of the date information")
    date_confidence: DateConfidence = Field(..., description="Confidence level of the date")
    
    model_config = ConfigDict(extra="forbid")


class NewsContent(BaseModel):
    """Content wrapper for news data."""
    data: NewsData
    
    model_config = ConfigDict(extra="forbid")


class NewsRecord(BaseModel):
    """Complete news record schema."""
    schemaVersion: str = Field(default=SCHEMA_VERSION, description="Schema version")
    recordType: Literal["NEWS"] = Field(default="NEWS", description="Record type identifier")
    source: SourceInfo
    content: NewsContent
    collectedAt: datetime = Field(..., description="Collection timestamp in ISO-8601 UTC")
    meta: Optional[dict[str, Any]] = Field(default=None, description="Additional metadata")
    
    model_config = ConfigDict(extra="forbid")
    
    @field_validator("collectedAt", mode="before")
    @classmethod
    def parse_collected_at(cls, v):
        """Ensure collectedAt is a datetime object."""
        if isinstance(v, str):
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        return v


class EntityMappingEntry(BaseModel):
    """Entity mapping log entry for resolution tracking."""
    raw_name: str = Field(..., description="Original entity name from source")
    canonical_name: str = Field(..., description="Resolved canonical entity name")
    match_method: str = Field(..., description="Method used for matching (exact, alias, fuzzy, new)")
    score: Optional[float] = Field(None, description="Match score (for fuzzy matching)")
    source_url: str = Field(..., description="URL where the entity was found")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Resolution timestamp")
    
    model_config = ConfigDict(extra="forbid")


# Type unions for easier handling
Record = StartupRecord | ProductRecord | ResearchPaperRecord | JobRecord | NewsRecord


def validate_record(record_dict: dict[str, Any]) -> Record:
    """
    Validate a record dictionary against the appropriate schema.
    
    Args:
        record_dict: Dictionary containing record data
        
    Returns:
        Validated record object
        
    Raises:
        ValueError: If record type is unknown or validation fails
    """
    record_type = record_dict.get("recordType")
    
    if record_type == "STARTUP":
        return StartupRecord(**record_dict)
    elif record_type == "PRODUCT":
        return ProductRecord(**record_dict)
    elif record_type == "RESEARCH_PAPER":
        return ResearchPaperRecord(**record_dict)
    elif record_type == "JOB":
        return JobRecord(**record_dict)
    elif record_type == "NEWS":
        return NewsRecord(**record_dict)
    else:
        raise ValueError(f"Unknown record type: {record_type}")
