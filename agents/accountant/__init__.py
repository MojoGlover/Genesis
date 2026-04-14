"""
Accountant — System Economic Intelligence and Financial Record Module
GENESIS Agent | Computer Black | v2.0

Usage:
    from GENESIS.agents.accountant import accountant

    # Record a cost
    accountant.track_inference("anthropic", "claude-haiku-4-5", 1200, 450, agent="engineer0")

    # Check budget status
    accountant.budget_status()

    # Get optimization recommendations
    accountant.optimize()

    # Generate reports
    print(accountant.report("daily"))
    print(accountant.report("monthly"))
    print(accountant.report("tax", year=2025))

    # Export tax CSV
    path = accountant.export_tax_csv(2025)

    # Forecast
    print(accountant.forecast())

    # Pre-flight: estimate before running something expensive
    est = accountant.estimate_workflow([
        {"name": "summarize", "provider": "anthropic", "model": "claude-haiku-4-5",
         "input_tokens": 2000, "output_tokens": 400, "count": 10},
    ])
"""
from .modules.ledger       import Ledger, Transaction
from .modules.cost_tracker import CostTracker
from .modules.budget_guard import BudgetGuard
from .modules.reporter     import Reporter
from .modules.optimizer    import Optimizer
from .modules.forecaster   import Forecaster
from .tools.gcp_costs      import GCPCostTracker


class AccountantAgent:
    """
    Public interface for the Accountant agent.
    All other agents and modules interact through this class.
    """

    def __init__(self):
        self.name        = "Accountant"
        self._ledger     = Ledger()
        self._tracker    = CostTracker(self._ledger)
        self._guard      = BudgetGuard(self._ledger)
        self._reporter   = Reporter(self._ledger)
        self._optimizer  = Optimizer(self._ledger)
        self._forecaster = Forecaster(self._ledger)
        self.gcp         = GCPCostTracker()     # GCP free-tier watcher

    # ── Cost tracking ─────────────────────────────────────────────────────────

    def track_inference(
        self, provider: str, model: str,
        input_tokens: int, output_tokens: int,
        agent: str = "system", workflow: str = "", project: str = "",
    ) -> float:
        """Record an LLM inference call. Returns cost in USD."""
        return self._tracker.track_inference(
            provider, model, input_tokens, output_tokens,
            agent=agent, workflow=workflow, project=project,
        )

    def track_compute(self, provider: str, service: str, **kwargs) -> float:
        """Record cloud compute usage."""
        return self._tracker.track_compute(provider, service, **kwargs)

    def track_subscription(self, vendor: str, service: str, amount_usd: float, **kwargs) -> float:
        """Record a subscription or recurring charge."""
        return self._tracker.track_subscription(vendor, service, amount_usd, **kwargs)

    def track(self, vendor: str, service: str, amount_usd: float, category: str, **kwargs) -> float:
        """Manually record any cost."""
        return self._tracker.track_manual(vendor, service, amount_usd, category, **kwargs)

    # ── Budget & alerts ───────────────────────────────────────────────────────

    def check_alerts(self) -> list:
        """Run all budget and anomaly checks. Returns list of alerts."""
        alerts = self._guard.check()
        alerts += self._guard.check_free_tier()
        spike = self._guard.detect_cost_spike()
        if spike:
            alerts.append(spike)
        # GCP free-tier alerts
        for msg in self.gcp.alert_if_approaching_limit():
            alerts.append(msg)
        return alerts

    def gcp_status(self) -> str:
        """Print GCP Cloud Run free-tier usage and cost."""
        return self.gcp.status()

    def budget_status(self) -> None:
        """Print current budget status to stdout."""
        self._guard.print_status()

    # ── Reports ───────────────────────────────────────────────────────────────

    def report(self, period: str = "monthly", year: int = None) -> str:
        """
        Generate a text report.
        period: "daily" | "weekly" | "monthly" | "tax" | "agents" | "forecast"
        """
        if period == "daily":
            return self._reporter.daily_summary()
        elif period == "weekly":
            return self._reporter.weekly_summary()
        elif period == "monthly":
            return self._reporter.monthly_summary()
        elif period == "tax":
            return self._reporter.tax_summary(year)
        elif period == "agents":
            return self._reporter.agent_cost_breakdown()
        elif period == "forecast":
            return self._forecaster.summary_text()
        else:
            return f"Unknown report type: {period}. Use: daily, weekly, monthly, tax, agents, forecast"

    def export_tax_csv(self, year: int = None) -> str:
        """Export tax-ready CSV. Returns path to file."""
        path = self._reporter.export_tax_csv(year)
        return str(path)

    # ── Optimization ─────────────────────────────────────────────────────────

    def optimize(self) -> None:
        """Print cost optimization recommendations."""
        self._optimizer.print_recommendations()

    def recommendations(self) -> list:
        """Return list of Recommendation objects."""
        return self._optimizer.analyze()

    # ── Forecasting ──────────────────────────────────────────────────────────

    def forecast(self) -> str:
        """Return text forecast summary."""
        return self._forecaster.summary_text()

    def estimate_workflow(self, steps: list) -> dict:
        """Estimate cost of a workflow before running it."""
        return self._forecaster.estimate_workflow_cost(steps)

    def break_even(self, monthly_revenue: float, fixed_costs: float = 0) -> dict:
        """Calculate break-even given expected revenue."""
        return self._forecaster.break_even(monthly_revenue, fixed_costs)

    # ── Full status ───────────────────────────────────────────────────────────

    def status(self) -> None:
        """Print full financial status: budget + forecast + top recommendations."""
        print(f"\n{'═'*54}")
        print(f"  Accountant — System Financial Status")
        print(f"{'═'*54}")
        self._guard.print_status()
        print(self._forecaster.summary_text())
        alerts = self.check_alerts()
        if alerts:
            print(f"\n⚠  {len(alerts)} active alert(s):")
            for a in alerts:
                print(f"  {a}")
        recs = self._optimizer.analyze()
        if recs:
            top = recs[:2]
            print(f"\n💡 Top recommendations:")
            for r in top:
                print(f"  {r}")
        print(f"{'═'*54}\n")


# Singleton — import and use directly
accountant = AccountantAgent()
