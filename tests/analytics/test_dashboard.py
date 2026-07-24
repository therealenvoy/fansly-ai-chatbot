"""Tests for KPI Dashboard."""

import pytest
from src.analytics.dashboard import KPIDashboard


class TestChattingRatio:
    def test_chatting_ratio_subscription_1000_dm_8000(self):
        """subscription=1000, dm=8000 -> 8.0"""
        result = KPIDashboard.calculate_chatting_ratio(1000.0, 8000.0)
        assert result == 8.0

    def test_chatting_ratio_zero_subscription(self):
        """Zero subscription revenue should handle gracefully."""
        result = KPIDashboard.calculate_chatting_ratio(0.0, 1000.0)
        assert result == 0.0

    def test_chatting_ratio_zero_dm(self):
        """Zero DM revenue should return 0.0."""
        result = KPIDashboard.calculate_chatting_ratio(500.0, 0.0)
        assert result == 0.0


class TestPPVUnlockRate:
    def test_ppv_unlock_rate_30_of_1000(self):
        """30/1000 -> 3.0%"""
        result = KPIDashboard.calculate_ppv_unlock_rate(30, 1000)
        assert result == 3.0

    def test_ppv_unlock_rate_zero_sends(self):
        """Zero sends should return 0.0."""
        result = KPIDashboard.calculate_ppv_unlock_rate(10, 0)
        assert result == 0.0

    def test_ppv_unlock_rate_full(self):
        """All sends unlocked."""
        result = KPIDashboard.calculate_ppv_unlock_rate(100, 100)
        assert result == 100.0


class TestAOV:
    def test_aov(self):
        """$500 total / 10 purchases = $50 AOV"""
        result = KPIDashboard.calculate_aov(500.0, 10)
        assert result == 50.0

    def test_aov_zero_purchases(self):
        """Zero purchases should return 0.0."""
        result = KPIDashboard.calculate_aov(500.0, 0)
        assert result == 0.0


class TestResponseTimeAvg:
    def test_response_time_avg(self):
        """Average of [1.0, 2.0, 3.0] = 2.0"""
        result = KPIDashboard.calculate_response_time_avg([1.0, 2.0, 3.0])
        assert result == 2.0

    def test_response_time_empty(self):
        """Empty list returns 0.0."""
        result = KPIDashboard.calculate_response_time_avg([])
        assert result == 0.0


class TestScriptCompletionRate:
    def test_script_completion_rate(self):
        """50 completed / 200 started = 25%"""
        result = KPIDashboard.calculate_script_completion_rate(50, 200)
        assert result == 25.0

    def test_script_completion_rate_zero_started(self):
        """Zero started returns 0.0."""
        result = KPIDashboard.calculate_script_completion_rate(10, 0)
        assert result == 0.0


class TestAftercareReturnRate:
    def test_aftercare_return_rate(self):
        """15 returns / 100 aftercare = 15%"""
        result = KPIDashboard.calculate_aftercare_return_rate(100, 15)
        assert result == 15.0

    def test_aftercare_return_rate_zero_aftercare(self):
        """Zero aftercare count returns 0.0."""
        result = KPIDashboard.calculate_aftercare_return_rate(0, 10)
        assert result == 0.0


class TestHealthLabel:
    def test_health_label_elite(self):
        """Ratio >9 -> 'elite'"""
        assert KPIDashboard.get_health_label(10.0) == "elite"
        assert KPIDashboard.get_health_label(9.1) == "elite"

    def test_health_label_healthy(self):
        """Ratio 6-9 -> 'healthy'"""
        assert KPIDashboard.get_health_label(7.5) == "healthy"
        assert KPIDashboard.get_health_label(6.0) == "healthy"
        assert KPIDashboard.get_health_label(9.0) == "healthy"

    def test_health_label_underperforming(self):
        """Ratio 4-6 -> 'underperforming'"""
        assert KPIDashboard.get_health_label(5.0) == "underperforming"
        assert KPIDashboard.get_health_label(4.0) == "underperforming"
        assert KPIDashboard.get_health_label(5.99) == "underperforming"

    def test_health_label_critical(self):
        """Ratio <4 -> 'critical'"""
        assert KPIDashboard.get_health_label(3.9) == "critical"
        assert KPIDashboard.get_health_label(0.0) == "critical"
        assert KPIDashboard.get_health_label(2.5) == "critical"


class TestSummary:
    def test_summary_returns_all_kpis(self):
        """Summary should compute KPIs and health label."""
        stats = {
            "subscription_revenue": 1000.0,
            "dm_revenue": 8000.0,
            "unlocks": 30,
            "sends": 1000,
            "total_dm_revenue": 500.0,
            "purchase_count": 10,
            "response_times": [1.0, 2.0, 3.0],
            "completed_scripts": 50,
            "started_scripts": 200,
            "aftercare_count": 100,
            "return_purchase_count": 15,
        }
        result = KPIDashboard.summary(stats)
        assert result["chatting_ratio"] == 8.0
        assert result["ppv_unlock_rate"] == 3.0
        assert result["aov"] == 50.0
        assert result["response_time_avg"] == 2.0
        assert result["script_completion_rate"] == 25.0
        assert result["aftercare_return_rate"] == 15.0
        assert result["health_label"] == "healthy"
