"""
LLM prompts for structured extraction with EVIDENCE-BASED GROUNDING.

v2 CRITICAL CHANGE: All LLM responses must include VERBATIM EVIDENCE QUOTES.
The LLM must return {"value": X, "evidence": "exact quote from text"} for each field.
Code verifies evidence is a substring of source text. No evidence = reject field.
"""
from typing import Dict, Any


# Anti-hallucination system prompt with EVIDENCE requirement
SYSTEM_PROMPT = """You are a precise data extraction assistant. Your role is to extract ONLY information that is explicitly present in the provided text, WITH EVIDENCE.

CRITICAL RULES (v2 - EVIDENCE-BASED GROUNDING):
1. For EVERY extracted value, you MUST provide a verbatim evidence quote from the text
2. Evidence must be an EXACT substring copied from the source text (preserve punctuation, capitalization)
3. Use null for any field where information is not present
4. NEVER infer, guess, or invent information
5. NEVER use your training data or general knowledge
6. NEVER paraphrase or summarize the evidence - copy it EXACTLY
7. If you cannot find verbatim evidence, set the field to null
8. Return valid JSON matching the specified schema

FORMAT: For each extractable field, return:
{
  "fieldName": {
    "value": "the extracted value",
    "evidence": "exact verbatim quote from the text that supports this value"
  }
}

For fields that cannot be extracted, return:
{
  "fieldName": {
    "value": null,
    "evidence": null
  }
}

Remember: Every extraction MUST be backed by verbatim evidence. It is better to return null than to guess or paraphrase."""


def get_startup_extraction_prompt(text: str) -> str:
    """
    Generate prompt for startup data extraction WITH EVIDENCE.
    
    Args:
        text: Source text
        
    Returns:
        Extraction prompt
    """
    return f"""Extract startup information from the following text. For EVERY field, provide the extracted value AND a verbatim evidence quote.

TEXT:
{text}

Extract the following fields as JSON with evidence:
{{
  "entityName": {{
    "value": "string (company name as written in text, or null)",
    "evidence": "exact quote from text mentioning the company name, or null"
  }},
  "employeeCount": {{
    "value": "integer (exact number if stated, or null)",
    "evidence": "exact quote stating the employee count, or null"
  }},
  "description": {{
    "value": "string (company description if present, or null)",
    "evidence": "exact quote with the description, or null"
  }},
  "founded": {{
    "value": "string (founding year/date if mentioned, or null)",
    "evidence": "exact quote mentioning founding date, or null"
  }},
  "location": {{
    "value": "string (headquarters location if mentioned, or null)",
    "evidence": "exact quote mentioning location, or null"
  }}
}}

CRITICAL: 
- Evidence must be VERBATIM (exact copy from the text above)
- Do NOT paraphrase or summarize
- If you cannot find an exact quote, use null for both value and evidence
- The evidence text will be verified as a substring of the source

Return valid JSON."""


def get_product_extraction_prompt(text: str) -> str:
    """
    Generate prompt for product data extraction WITH EVIDENCE.
    
    Args:
        text: Source text
        
    Returns:
        Extraction prompt
    """
    return f"""Extract product information from the following text. For EVERY field, provide the extracted value AND a verbatim evidence quote.

TEXT:
{text}

Extract the following fields as JSON with evidence:
{{
  "productName": {{
    "value": "string (product name as written, or null)",
    "evidence": "exact quote mentioning the product name, or null"
  }},
  "startupName": {{
    "value": "string (company/creator name, or null)",
    "evidence": "exact quote mentioning the company name, or null"
  }},
  "pricingModel": {{
    "value": "FREE|FREEMIUM|PAID|ENTERPRISE|null",
    "evidence": "exact quote about pricing, or null"
  }},
  "description": {{
    "value": "string (product description if present, or null)",
    "evidence": "exact quote with description, or null"
  }},
  "category": {{
    "value": "string (product category if mentioned, or null)",
    "evidence": "exact quote mentioning category, or null"
  }}
}}

For pricingModel, extract value based on evidence:
- FREE: explicit mention of "free", "open source", "no cost"
- FREEMIUM: mentions both free and paid tiers
- PAID: mentions subscription, pricing, payment
- ENTERPRISE: mentions enterprise or custom pricing
- null: no pricing information in text

CRITICAL:
- Evidence must be VERBATIM (exact copy from the text above)
- The evidence will be verified as a substring of the source
- If ambiguous or unclear, use null for both value and evidence

Return valid JSON."""


def get_news_extraction_prompt(text: str) -> str:
    """
    Generate prompt for news article entity extraction WITH EVIDENCE.
    
    Args:
        text: Source text
        
    Returns:
        Extraction prompt
    """
    return f"""Extract entities from the following news article. For EVERY field, provide the extracted value AND verbatim evidence.

TEXT:
{text}

Extract the following fields as JSON with evidence:
{{
  "companies": [
    {{"value": "CompanyName", "evidence": "exact quote mentioning this company"}},
    ...
  ],
  "people": [
    {{"value": "Person Name", "evidence": "exact quote mentioning this person"}},
    ...
  ],
  "products": [
    {{"value": "Product Name", "evidence": "exact quote mentioning this product"}},
    ...
  ],
  "summary": {{
    "value": "2-3 sentence summary (or null if text too short)",
    "evidence": "key sentences from text used for summary, or null"
  }},
  "key_facts": [
    {{"value": "key fact statement", "evidence": "exact quote supporting this fact"}},
    ...
  ]
}}

CRITICAL:
- For arrays, EACH item must have its own evidence quote
- Evidence must be VERBATIM from the text above
- Use empty array [] if no items found
- Do NOT invent or infer entities not mentioned

Return valid JSON."""


def get_job_extraction_prompt(text: str) -> str:
    """
    Generate prompt for job posting extraction WITH EVIDENCE.
    
    Args:
        text: Source text
        
    Returns:
        Extraction prompt
    """
    return f"""Extract job posting information from the following text. For EVERY field, provide the extracted value AND verbatim evidence.

TEXT:
{text}

Extract the following fields as JSON with evidence:
{{
  "title": {{
    "value": "string (job title as written, or null)",
    "evidence": "exact quote with the job title, or null"
  }},
  "company": {{
    "value": "string (company name as written, or null)",
    "evidence": "exact quote mentioning the company, or null"
  }},
  "location": {{
    "value": "string (job location if mentioned, or null)",
    "evidence": "exact quote mentioning location, or null"
  }},
  "is_remote": {{
    "value": "boolean (true if remote mentioned, false if on-site, null if unclear)",
    "evidence": "exact quote about work location/remote status, or null"
  }},
  "role_family": {{
    "value": "string (Engineering, AI/ML, Product, Design, or null)",
    "evidence": "exact quote indicating role type, or null"
  }},
  "requirements": [
    {{"value": "requirement text", "evidence": "exact quote with this requirement"}},
    ...
  ],
  "salary_range": {{
    "value": "string (salary range if mentioned, or null)",
    "evidence": "exact quote mentioning salary, or null"
  }}
}}

CRITICAL:
- Evidence must be VERBATIM from the text above
- For boolean is_remote: extract value from evidence (true if "remote"/"work from home" mentioned)
- Use empty array [] if no requirements found
- If field is not mentioned, use null for both value and evidence

Return valid JSON."""


def get_paper_extraction_prompt(text: str) -> str:
    """
    Generate prompt for research paper metadata extraction WITH EVIDENCE.
    
    Args:
        text: Source text (abstract or page content)
        
    Returns:
        Extraction prompt
    """
    return f"""Extract research paper information from the following text. For EVERY field, provide the extracted value AND verbatim evidence.

TEXT:
{text}

Extract the following fields as JSON with evidence:
{{
  "title": {{
    "value": "string (paper title as written, or null)",
    "evidence": "exact quote with the paper title, or null"
  }},
  "authors": [
    {{"value": "Author Name", "evidence": "exact quote mentioning this author"}},
    ...
  ],
  "abstract": {{
    "value": "string (paper abstract if present, or null)",
    "evidence": "the abstract text itself (if clearly marked), or null"
  }},
  "published_date": {{
    "value": "string (publication date if mentioned, or null)",
    "evidence": "exact quote mentioning date, or null"
  }},
  "github_urls": [
    {{"value": "https://github.com/...", "evidence": "exact quote with this URL"}},
    ...
  ],
  "key_contributions": [
    {{"value": "contribution statement", "evidence": "exact quote describing this contribution"}},
    ...
  ]
}}

CRITICAL:
- Evidence must be VERBATIM from the text above
- For arrays, EACH item needs its own evidence
- Use empty array [] if no items found
- For URLs, evidence must contain the actual URL

Return valid JSON."""


# JSON schemas for structured output WITH EVIDENCE
# v2: All fields now require {"value": X, "evidence": "quote"}

EVIDENCE_FIELD_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": ["string", "integer", "boolean", "null"]},
        "evidence": {"type": ["string", "null"]},
    },
    "required": ["value", "evidence"],
}

EVIDENCE_ARRAY_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": "string"},
        "evidence": {"type": "string"},
    },
    "required": ["value", "evidence"],
}

STARTUP_SCHEMA = {
    "type": "object",
    "properties": {
        "entityName": EVIDENCE_FIELD_SCHEMA,
        "employeeCount": {
            "type": "object",
            "properties": {
                "value": {"type": ["integer", "null"]},
                "evidence": {"type": ["string", "null"]},
            },
            "required": ["value", "evidence"],
        },
        "description": EVIDENCE_FIELD_SCHEMA,
        "founded": EVIDENCE_FIELD_SCHEMA,
        "location": EVIDENCE_FIELD_SCHEMA,
    },
    "required": ["entityName", "employeeCount"],
}

PRODUCT_SCHEMA = {
    "type": "object",
    "properties": {
        "productName": EVIDENCE_FIELD_SCHEMA,
        "startupName": EVIDENCE_FIELD_SCHEMA,
        "pricingModel": {
            "type": "object",
            "properties": {
                "value": {"type": ["string", "null"], "enum": ["FREE", "FREEMIUM", "PAID", "ENTERPRISE", None]},
                "evidence": {"type": ["string", "null"]},
            },
            "required": ["value", "evidence"],
        },
        "description": EVIDENCE_FIELD_SCHEMA,
        "category": EVIDENCE_FIELD_SCHEMA,
    },
    "required": ["productName", "startupName", "pricingModel"],
}

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "people": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "products": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "summary": EVIDENCE_FIELD_SCHEMA,
        "key_facts": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
    },
    "required": ["companies", "people", "products", "summary", "key_facts"],
}

JOB_SCHEMA = {
    "type": "object",
    "properties": {
        "title": EVIDENCE_FIELD_SCHEMA,
        "company": EVIDENCE_FIELD_SCHEMA,
        "location": EVIDENCE_FIELD_SCHEMA,
        "is_remote": {
            "type": "object",
            "properties": {
                "value": {"type": ["boolean", "null"]},
                "evidence": {"type": ["string", "null"]},
            },
            "required": ["value", "evidence"],
        },
        "role_family": EVIDENCE_FIELD_SCHEMA,
        "requirements": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "salary_range": EVIDENCE_FIELD_SCHEMA,
    },
    "required": ["title", "company", "location", "is_remote", "role_family"],
}

PAPER_SCHEMA = {
    "type": "object",
    "properties": {
        "title": EVIDENCE_FIELD_SCHEMA,
        "authors": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "abstract": EVIDENCE_FIELD_SCHEMA,
        "published_date": EVIDENCE_FIELD_SCHEMA,
        "github_urls": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
        "key_contributions": {
            "type": "array",
            "items": EVIDENCE_ARRAY_ITEM_SCHEMA,
        },
    },
    "required": ["title", "authors"],
}


def get_prompt_and_schema(record_type: str, text: str) -> tuple[str, Dict[str, Any]]:
    """
    Get appropriate prompt and schema for a record type.
    
    Args:
        record_type: Record type (STARTUP, PRODUCT, NEWS, JOB, RESEARCH_PAPER)
        text: Source text
        
    Returns:
        Tuple of (prompt, schema)
    """
    if record_type == "STARTUP":
        return (get_startup_extraction_prompt(text), STARTUP_SCHEMA)
    elif record_type == "PRODUCT":
        return (get_product_extraction_prompt(text), PRODUCT_SCHEMA)
    elif record_type == "NEWS":
        return (get_news_extraction_prompt(text), NEWS_SCHEMA)
    elif record_type == "JOB":
        return (get_job_extraction_prompt(text), JOB_SCHEMA)
    elif record_type == "RESEARCH_PAPER":
        return (get_paper_extraction_prompt(text), PAPER_SCHEMA)
    else:
        raise ValueError(f"Unknown record type: {record_type}")
