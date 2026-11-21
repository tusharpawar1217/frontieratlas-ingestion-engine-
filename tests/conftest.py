"""
Pytest configuration and shared fixtures.
"""
import pytest
import asyncio
from pathlib import Path


# Configure pytest-asyncio
def pytest_configure(config):
    """Configure pytest."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


@pytest.fixture(scope="session")
def event_loop():
    """Create an event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_data_dir():
    """Provide path to test data directory."""
    return Path(__file__).parent / "test_data"


@pytest.fixture
def sample_html():
    """Provide sample HTML for testing."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="article:published_time" content="2024-01-15T10:30:00Z">
        <script type="application/ld+json">
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": "Test Article",
            "datePublished": "2024-01-15T10:30:00Z"
        }
        </script>
    </head>
    <body>
        <article>
            <h1>Test Article</h1>
            <time datetime="2024-01-15T10:30:00Z">January 15, 2024</time>
            <p>This is test content about OpenAI and Anthropic.</p>
        </article>
    </body>
    </html>
    """


@pytest.fixture
def sample_rss_entry():
    """Provide sample RSS entry for testing."""
    import time
    from datetime import datetime, timezone
    
    return {
        'title': 'Test Article',
        'link': 'https://example.com/test',
        'summary': 'Test summary',
        'published_parsed': time.struct_time((2024, 1, 15, 10, 30, 0, 0, 0, 0)),
        'published': 'Mon, 15 Jan 2024 10:30:00 GMT',
    }
