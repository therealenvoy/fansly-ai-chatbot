"""KPI Dashboard — computes key performance indicators for creator revenue."""


class KPIDashboard:
    """Computes and labels key performance indicators for fansly creators."""

    @staticmethod
    def calculate_chatting_ratio(subscription_revenue: float, dm_revenue: float) -> float:
        """Calculate DM-to-subscription revenue ratio.

        Args:
            subscription_revenue: Total subscription revenue.
            dm_revenue: Total DM/tip revenue.

        Returns:
            Ratio of dm_revenue / subscription_revenue, or 0.0 if subscription is zero.
        """
        if subscription_revenue == 0.0:
            return 0.0
        return dm_revenue / subscription_revenue

    @staticmethod
    def calculate_ppv_unlock_rate(unlocks: int, sends: int) -> float:
        """Calculate PPV unlock rate as a percentage.

        Args:
            unlocks: Number of PPV unlocks.
            sends: Number of PPV sends.

        Returns:
            Percentage of sends that resulted in unlocks, or 0.0 if sends is zero.
        """
        if sends == 0:
            return 0.0
        return (unlocks / sends) * 100.0

    @staticmethod
    def calculate_aov(total_dm_revenue: float, purchase_count: int) -> float:
        """Calculate Average Order Value.

        Args:
            total_dm_revenue: Total revenue from DM purchases.
            purchase_count: Number of purchases.

        Returns:
            Average order value, or 0.0 if purchase_count is zero.
        """
        if purchase_count == 0:
            return 0.0
        return total_dm_revenue / purchase_count

    @staticmethod
    def calculate_response_time_avg(response_times: list[float]) -> float:
        """Calculate average response time.

        Args:
            response_times: List of response times in seconds.

        Returns:
            Average response time, or 0.0 if the list is empty.
        """
        if not response_times:
            return 0.0
        return sum(response_times) / len(response_times)

    @staticmethod
    def calculate_script_completion_rate(completed: int, started: int) -> float:
        """Calculate script completion rate as a percentage.

        Args:
            completed: Number of completed scripts.
            started: Number of started scripts.

        Returns:
            Completion rate percentage, or 0.0 if started is zero.
        """
        if started == 0:
            return 0.0
        return (completed / started) * 100.0

    @staticmethod
    def calculate_aftercare_return_rate(aftercare_count: int, return_purchase_count: int) -> float:
        """Calculate aftercare return purchase rate as a percentage.

        Args:
            aftercare_count: Number of aftercare interactions.
            return_purchase_count: Number of return purchases after aftercare.

        Returns:
            Return rate percentage, or 0.0 if aftercare_count is zero.
        """
        if aftercare_count == 0:
            return 0.0
        return (return_purchase_count / aftercare_count) * 100.0

    @staticmethod
    def get_health_label(chatting_ratio: float) -> str:
        """Return a health label based on chatting ratio.

        Args:
            chatting_ratio: DM-to-subscription revenue ratio.

        Returns:
            'elite' (>9), 'healthy' (6-9), 'underperforming' (4-6), or 'critical' (<4).
        """
        if chatting_ratio > 9.0:
            return "elite"
        elif chatting_ratio >= 6.0:
            return "healthy"
        elif chatting_ratio >= 4.0:
            return "underperforming"
        else:
            return "critical"

    @staticmethod
    def summary(stats: dict) -> dict:
        """Compute all KPIs and health label from a stats dict.

        Args:
            stats: Dictionary with keys:
                - subscription_revenue
                - dm_revenue
                - unlocks
                - sends
                - total_dm_revenue
                - purchase_count
                - response_times
                - completed_scripts
                - started_scripts
                - aftercare_count
                - return_purchase_count

        Returns:
            Dictionary with all computed KPIs and health_label.
        """
        chatting_ratio = KPIDashboard.calculate_chatting_ratio(
            stats["subscription_revenue"], stats["dm_revenue"]
        )
        return {
            "chatting_ratio": chatting_ratio,
            "ppv_unlock_rate": KPIDashboard.calculate_ppv_unlock_rate(
                stats["unlocks"], stats["sends"]
            ),
            "aov": KPIDashboard.calculate_aov(
                stats["total_dm_revenue"], stats["purchase_count"]
            ),
            "response_time_avg": KPIDashboard.calculate_response_time_avg(
                stats["response_times"]
            ),
            "script_completion_rate": KPIDashboard.calculate_script_completion_rate(
                stats["completed_scripts"], stats["started_scripts"]
            ),
            "aftercare_return_rate": KPIDashboard.calculate_aftercare_return_rate(
                stats["aftercare_count"], stats["return_purchase_count"]
            ),
            "health_label": KPIDashboard.get_health_label(chatting_ratio),
        }
