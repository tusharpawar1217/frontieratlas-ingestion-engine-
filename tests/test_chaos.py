"""
Tests for Chaos Engineering Framework
"""

import pytest
import asyncio

from src.chaos import (
    ChaosInjector,
    FailureRule,
    FailureType,
    HTTPError,
    create_rate_limit_chaos,
    create_network_chaos,
    create_latency_chaos,
)


@pytest.fixture
def chaos_injector():
    """Create chaos injector for testing."""
    injector = ChaosInjector(enabled=True)
    yield injector
    injector.clear_rules()


class TestFailureRule:
    """Test failure rules."""
    
    def test_rule_matches_all_domains(self):
        """Rule with no domain filter should match all."""
        rule = FailureRule(
            name="test",
            failure_type=FailureType.HTTP_429,
            probability=1.0,  # Always match
        )
        
        assert rule.matches("https://example.com/page")
        assert rule.matches("https://other.com/page")
    
    def test_rule_matches_specific_domain(self):
        """Rule with domain filter should match only that domain."""
        rule = FailureRule(
            name="test",
            failure_type=FailureType.HTTP_429,
            probability=1.0,
            target_domains={"example.com"},
        )
        
        assert rule.matches("https://example.com/page")
        assert not rule.matches("https://other.com/page")
    
    def test_rule_matches_pattern(self):
        """Rule with pattern should match URLs containing pattern."""
        rule = FailureRule(
            name="test",
            failure_type=FailureType.HTTP_429,
            probability=1.0,
            target_patterns=["/api/"],
        )
        
        assert rule.matches("https://example.com/api/data")
        assert not rule.matches("https://example.com/page")
    
    def test_rule_respects_probability(self):
        """Rule with low probability should not always match."""
        rule = FailureRule(
            name="test",
            failure_type=FailureType.HTTP_429,
            probability=0.0,  # Never match
        )
        
        # Even with repeated checks, should never match
        for _ in range(100):
            assert not rule.matches("https://example.com/page")
    
    def test_disabled_rule_never_matches(self):
        """Disabled rule should never match."""
        rule = FailureRule(
            name="test",
            failure_type=FailureType.HTTP_429,
            probability=1.0,
            enabled=False,
        )
        
        assert not rule.matches("https://example.com/page")


class TestChaosInjector:
    """Test chaos injector."""
    
    @pytest.mark.asyncio
    async def test_no_injection_when_disabled(self, chaos_injector):
        """Injector should not inject when disabled."""
        chaos_injector.disable()
        
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=429,
            probability=1.0,
        )
        
        failure = await chaos_injector.inject("https://example.com/page")
        
        assert failure is None
    
    @pytest.mark.asyncio
    async def test_http_429_injection(self, chaos_injector):
        """Test injecting HTTP 429 error."""
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=429,
            probability=1.0,
        )
        
        failure = await chaos_injector.inject("https://example.com/page")
        
        assert failure is not None
        assert isinstance(failure, HTTPError)
        assert failure.status_code == 429
    
    @pytest.mark.asyncio
    async def test_http_503_injection(self, chaos_injector):
        """Test injecting HTTP 503 error."""
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=503,
            probability=1.0,
        )
        
        failure = await chaos_injector.inject("https://example.com/page")
        
        assert failure is not None
        assert isinstance(failure, HTTPError)
        assert failure.status_code == 503
    
    @pytest.mark.asyncio
    async def test_timeout_injection(self, chaos_injector):
        """Test injecting timeout error."""
        rule = FailureRule(
            name="timeout",
            failure_type=FailureType.TIMEOUT,
            probability=1.0,
        )
        chaos_injector.add_rule(rule)
        
        failure = await chaos_injector.inject("https://example.com/page")
        
        assert failure is not None
        assert isinstance(failure, TimeoutError)
    
    @pytest.mark.asyncio
    async def test_connection_error_injection(self, chaos_injector):
        """Test injecting connection error."""
        rule = FailureRule(
            name="connection",
            failure_type=FailureType.CONNECTION_ERROR,
            probability=1.0,
        )
        chaos_injector.add_rule(rule)
        
        failure = await chaos_injector.inject("https://example.com/page")
        
        assert failure is not None
        assert isinstance(failure, ConnectionError)
    
    @pytest.mark.asyncio
    async def test_latency_injection(self, chaos_injector):
        """Test injecting latency."""
        import time
        
        chaos_injector.add_latency_rule(
            name="latency",
            latency_ms=100,
            probability=1.0,
        )
        
        start = time.time()
        failure = await chaos_injector.inject("https://example.com/page")
        elapsed = time.time() - start
        
        # Latency is not a failure
        assert failure is None
        # But should have delayed
        assert elapsed >= 0.1


class TestRuleManagement:
    """Test managing chaos rules."""
    
    @pytest.mark.asyncio
    async def test_add_and_remove_rule(self, chaos_injector):
        """Test adding and removing rules."""
        chaos_injector.add_http_error_rule(
            name="test_rule",
            status_code=429,
            probability=1.0,
        )
        
        assert len(chaos_injector.rules) == 1
        
        removed = chaos_injector.remove_rule("test_rule")
        
        assert removed is True
        assert len(chaos_injector.rules) == 0
    
    @pytest.mark.asyncio
    async def test_enable_disable_rule(self, chaos_injector):
        """Test enabling and disabling rules."""
        chaos_injector.add_http_error_rule(
            name="test_rule",
            status_code=429,
            probability=1.0,
        )
        
        # Disable rule
        chaos_injector.disable_rule("test_rule")
        
        failure = await chaos_injector.inject("https://example.com/page")
        assert failure is None
        
        # Enable rule
        chaos_injector.enable_rule("test_rule")
        
        failure = await chaos_injector.inject("https://example.com/page")
        assert failure is not None


class TestStatistics:
    """Test statistics tracking."""
    
    @pytest.mark.asyncio
    async def test_stats_tracking(self, chaos_injector):
        """Test statistics are tracked."""
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=429,
            probability=1.0,
        )
        
        # Inject failures
        await chaos_injector.inject("https://example.com/1")
        await chaos_injector.inject("https://example.com/2")
        await chaos_injector.inject("https://other.com/1")
        
        stats = chaos_injector.get_stats()
        
        assert stats['total_requests'] == 3
        assert stats['failures_injected'] == 3
        assert stats['injection_rate_percent'] == 100.0
        assert stats['by_type']['http_429'] == 3
    
    @pytest.mark.asyncio
    async def test_stats_by_domain(self, chaos_injector):
        """Test statistics by domain."""
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=429,
            probability=1.0,
        )
        
        await chaos_injector.inject("https://example.com/1")
        await chaos_injector.inject("https://example.com/2")
        await chaos_injector.inject("https://other.com/1")
        
        stats = chaos_injector.get_stats()
        
        assert stats['by_domain']['example.com'] == 2
        assert stats['by_domain']['other.com'] == 1


class TestPredefinedScenarios:
    """Test predefined chaos scenarios."""
    
    def test_rate_limit_scenario(self):
        """Test rate limit chaos scenario."""
        rules = create_rate_limit_chaos(domains={"example.com"})
        
        assert len(rules) == 2
        assert any(r.failure_type == FailureType.HTTP_429 for r in rules)
        assert any(r.failure_type == FailureType.HTTP_503 for r in rules)
    
    def test_network_scenario(self):
        """Test network chaos scenario."""
        rules = create_network_chaos()
        
        assert len(rules) == 2
        assert any(r.failure_type == FailureType.TIMEOUT for r in rules)
        assert any(r.failure_type == FailureType.CONNECTION_ERROR for r in rules)
    
    def test_latency_scenario(self):
        """Test latency chaos scenario."""
        rules = create_latency_chaos(latency_ms=500)
        
        assert len(rules) == 1
        assert rules[0].failure_type == FailureType.LATENCY
        assert rules[0].latency_ms == 500


class TestDomainTargeting:
    """Test targeting specific domains."""
    
    @pytest.mark.asyncio
    async def test_target_specific_domain(self, chaos_injector):
        """Test failures only on specific domain."""
        chaos_injector.add_http_error_rule(
            name="test",
            status_code=429,
            probability=1.0,
            domains={"example.com"},
        )
        
        # Should inject on example.com
        failure1 = await chaos_injector.inject("https://example.com/page")
        assert failure1 is not None
        
        # Should NOT inject on other.com
        failure2 = await chaos_injector.inject("https://other.com/page")
        assert failure2 is None
