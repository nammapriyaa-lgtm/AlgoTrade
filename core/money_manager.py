"""
Advanced Money Management Module
==================================
Capital allocation, compounding, drawdown recovery,
profit management, and portfolio optimization.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CapitalState:
    """Current state of capital allocation."""
    total_capital: float = 0.0
    trading_capital: float = 0.0
    reserve_capital: float = 0.0
    strategy_allocations: Dict[str, float] = field(default_factory=dict)
    deployed_amount: float = 0.0
    free_capital: float = 0.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    compounded_amount: float = 0.0
    withdrawn_amount: float = 0.0


class MoneyManager:
    """
    Advanced money management with institutional-grade capital controls.
    
    Features:
    - Dynamic capital allocation across strategies
    - Smart compounding with threshold controls
    - Progressive drawdown recovery
    - Profit target management and scaling
    - Withdrawal scheduling
    - Risk-adjusted position sizing integration
    - Capital preservation rules
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Capital tracking
        self.initial_capital = config.get("total_capital", 500000)
        self.current_capital = self.initial_capital
        self.peak_capital = self.initial_capital
        self.reserve_percent = config.get("allocation", {}).get("reserve_percent", 30.0) / 100
        
        # P&L tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.monthly_pnl = 0.0
        self.total_pnl = 0.0
        self.pnl_history: List[Dict[str, Any]] = []
        
        # Compounding
        self.compounded_total = 0.0
        self.compound_config = config.get("compounding", {})
        
        # Drawdown recovery
        self.in_drawdown = False
        self.drawdown_depth = 0.0
        self.size_reduction_active = False
        self.current_size_multiplier = 1.0
        
        # Profit management
        self.daily_target_reached = False
        self.weekly_target_reached = False
        self.scaling_active = False
        
        # Withdrawal tracking
        self.total_withdrawn = 0.0
        self.withdrawal_history: List[Dict] = []
        
        logger.info("MoneyManager initialized | Capital: %s | Reserve: %.0f%%",
                   self.initial_capital, self.reserve_percent * 100)

    # =========================================================================
    # CAPITAL ALLOCATION
    # =========================================================================

    def get_capital_state(self) -> CapitalState:
        """Get current capital allocation state."""
        trading_capital = self.current_capital * (1 - self.reserve_percent)
        reserve_capital = self.current_capital * self.reserve_percent
        
        allocations = self._calculate_strategy_allocations(trading_capital)
        
        return CapitalState(
            total_capital=self.current_capital,
            trading_capital=trading_capital,
            reserve_capital=reserve_capital,
            strategy_allocations=allocations,
            deployed_amount=0,  # Updated externally
            free_capital=trading_capital,
            daily_pnl=self.daily_pnl,
            weekly_pnl=self.weekly_pnl,
            monthly_pnl=self.monthly_pnl,
            compounded_amount=self.compounded_total,
            withdrawn_amount=self.total_withdrawn,
        )

    def _calculate_strategy_allocations(self, trading_capital: float) -> Dict[str, float]:
        """Calculate capital allocation per strategy."""
        alloc_config = self.config.get("allocation", {})
        allocations = {}
        
        s1_pct = alloc_config.get("strategy_1_percent", 40.0) / 100
        s2_pct = alloc_config.get("strategy_2_percent", 30.0) / 100
        
        allocations["strategy_1"] = trading_capital * s1_pct
        allocations["strategy_2"] = trading_capital * s2_pct
        allocations["discretionary"] = trading_capital * (1 - s1_pct - s2_pct)
        
        # Apply size reduction if in drawdown
        if self.size_reduction_active:
            for key in allocations:
                allocations[key] *= self.current_size_multiplier
        
        return allocations

    def get_available_capital(self, strategy_id: str = "strategy_1") -> float:
        """Get available capital for a specific strategy."""
        state = self.get_capital_state()
        return state.strategy_allocations.get(strategy_id, 0)

    def get_max_position_value(self, strategy_id: str = "strategy_1") -> float:
        """Get maximum single position value for a strategy."""
        available = self.get_available_capital(strategy_id)
        max_per_trade_pct = self.config.get("max_capital_per_trade", 0.10)
        return available * max_per_trade_pct

    # =========================================================================
    # COMPOUNDING
    # =========================================================================

    def apply_compounding(self) -> Dict[str, Any]:
        """
        Apply compounding rules to grow position sizes.
        
        Rules:
        - Only compound after reaching threshold
        - Compound specified percentage of profits
        - Cap maximum growth
        """
        if not self.compound_config.get("enabled", True):
            return {"applied": False, "reason": "Compounding disabled"}
        
        threshold = self.compound_config.get("compound_threshold", 10000)
        compound_pct = self.compound_config.get("compound_percent", 50.0) / 100
        max_growth = self.compound_config.get("max_position_growth", 2.0)
        
        # Check if profit exceeds threshold
        if self.total_pnl < threshold:
            return {"applied": False, "reason": f"Profit below threshold ({self.total_pnl} < {threshold})"}
        
        # Check if max growth exceeded
        growth_ratio = self.current_capital / self.initial_capital
        if growth_ratio >= max_growth:
            return {"applied": False, "reason": f"Max growth reached ({growth_ratio:.2f}x)"}
        
        # Apply compounding
        compound_amount = self.total_pnl * compound_pct
        
        # Only compound new profits since last compounding
        new_compound = compound_amount - self.compounded_total
        if new_compound <= 0:
            return {"applied": False, "reason": "No new profits to compound"}
        
        self.current_capital += new_compound
        self.compounded_total += new_compound
        
        logger.info("Compounding applied: +%.2f | New capital: %.2f", new_compound, self.current_capital)
        
        return {
            "applied": True,
            "compound_amount": new_compound,
            "new_capital": self.current_capital,
            "growth_ratio": self.current_capital / self.initial_capital,
        }

    # =========================================================================
    # DRAWDOWN RECOVERY
    # =========================================================================

    def check_drawdown_recovery(self) -> Dict[str, Any]:
        """
        Check and manage drawdown state.
        Implements progressive size reduction during drawdowns.
        """
        dd_config = self.config.get("drawdown_recovery", {})
        
        # Calculate current drawdown
        if self.peak_capital > 0:
            self.drawdown_depth = ((self.peak_capital - self.current_capital) / self.peak_capital) * 100
        
        reduce_at = dd_config.get("reduce_size_at_drawdown", 5.0)
        reduction_factor = dd_config.get("size_reduction_factor", 0.5)
        recovery_threshold = dd_config.get("recovery_threshold", 2.0)
        progressive = dd_config.get("progressive_reduction", True)
        
        result = {
            "in_drawdown": False,
            "drawdown_percent": self.drawdown_depth,
            "size_multiplier": 1.0,
            "action": "none",
        }
        
        if self.drawdown_depth >= reduce_at:
            self.in_drawdown = True
            self.size_reduction_active = True
            
            if progressive:
                # Progressive reduction: reduce more as drawdown deepens
                excess_dd = self.drawdown_depth - reduce_at
                additional_reduction = excess_dd * 0.1  # 10% more reduction per 1% extra DD
                self.current_size_multiplier = max(
                    0.25,  # Never go below 25% size
                    reduction_factor - additional_reduction
                )
            else:
                self.current_size_multiplier = reduction_factor
            
            result["in_drawdown"] = True
            result["size_multiplier"] = self.current_size_multiplier
            result["action"] = "reduce_size"
            
            logger.warning(
                "Drawdown recovery active: DD=%.2f%% | Size multiplier: %.2f",
                self.drawdown_depth, self.current_size_multiplier
            )
            
        elif self.in_drawdown and self.drawdown_depth <= recovery_threshold:
            # Recovery - resume normal sizing
            self.in_drawdown = False
            self.size_reduction_active = False
            self.current_size_multiplier = 1.0
            result["action"] = "resume_normal"
            logger.info("Drawdown recovery: Resuming normal position sizing")
        
        return result

    def update_peak(self) -> None:
        """Update peak capital after new highs."""
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital

    # =========================================================================
    # PROFIT MANAGEMENT
    # =========================================================================

    def check_profit_targets(self) -> Dict[str, Any]:
        """
        Check if profit targets are reached and manage scaling.
        """
        profit_config = self.config.get("profit_management", {})
        
        result = {
            "daily_target_reached": False,
            "weekly_target_reached": False,
            "scale_down_active": False,
            "scale_factor": 1.0,
        }
        
        daily_target = profit_config.get("daily_target", 25000)
        weekly_target = profit_config.get("weekly_target", 100000)
        
        # Daily target check
        if self.daily_pnl >= daily_target:
            self.daily_target_reached = True
            result["daily_target_reached"] = True
            
            if profit_config.get("scale_down_after_target", True):
                scale_factor = profit_config.get("scale_down_factor", 0.5)
                self.scaling_active = True
                result["scale_down_active"] = True
                result["scale_factor"] = scale_factor
                logger.info("Daily target reached (%.2f). Scaling down by %.0f%%",
                           self.daily_pnl, (1 - scale_factor) * 100)
        
        # Weekly target check
        if self.weekly_pnl >= weekly_target:
            self.weekly_target_reached = True
            result["weekly_target_reached"] = True
        
        return result

    def get_position_multiplier(self) -> float:
        """
        Get the effective position size multiplier considering all factors:
        - Drawdown recovery
        - Profit target scaling
        - Compounding growth
        """
        multiplier = 1.0
        
        # Drawdown reduction
        if self.size_reduction_active:
            multiplier *= self.current_size_multiplier
        
        # Profit scaling (reduce after target)
        if self.scaling_active:
            scale_factor = self.config.get("profit_management", {}).get("scale_down_factor", 0.5)
            multiplier *= scale_factor
        
        # Compounding growth (increase based on capital growth)
        if self.compound_config.get("enabled", True) and self.current_capital > self.initial_capital:
            growth = self.current_capital / self.initial_capital
            multiplier *= min(growth, self.compound_config.get("max_position_growth", 2.0))
        
        return round(multiplier, 3)

    # =========================================================================
    # P&L RECORDING
    # =========================================================================

    def record_pnl(self, pnl: float, trade_type: str = "intraday") -> None:
        """Record P&L from a completed trade."""
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.monthly_pnl += pnl
        self.total_pnl += pnl
        self.current_capital += pnl
        
        self.update_peak()
        self.check_drawdown_recovery()
        self.check_profit_targets()
        
        self.pnl_history.append({
            "timestamp": datetime.now().isoformat(),
            "pnl": pnl,
            "cumulative_pnl": self.total_pnl,
            "capital": self.current_capital,
            "type": trade_type,
        })

    def end_of_day(self) -> Dict[str, Any]:
        """End of day processing - apply compounding, record stats."""
        compound_result = self.apply_compounding()
        
        eod_stats = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "daily_pnl": self.daily_pnl,
            "weekly_pnl": self.weekly_pnl,
            "monthly_pnl": self.monthly_pnl,
            "total_pnl": self.total_pnl,
            "current_capital": self.current_capital,
            "peak_capital": self.peak_capital,
            "drawdown": self.drawdown_depth,
            "compounded": compound_result,
            "daily_target_reached": self.daily_target_reached,
        }
        
        # Reset daily
        self.daily_pnl = 0.0
        self.daily_target_reached = False
        self.scaling_active = False
        
        return eod_stats

    def end_of_week(self) -> Dict[str, Any]:
        """End of week processing."""
        stats = {"weekly_pnl": self.weekly_pnl, "capital": self.current_capital}
        self.weekly_pnl = 0.0
        self.weekly_target_reached = False
        return stats

    def end_of_month(self) -> Dict[str, Any]:
        """End of month processing with withdrawal calculation."""
        profit_config = self.config.get("profit_management", {})
        withdraw_pct = profit_config.get("withdraw_percent_monthly", 20.0) / 100
        
        withdrawal = 0.0
        if self.monthly_pnl > 0:
            withdrawal = self.monthly_pnl * withdraw_pct
            self.total_withdrawn += withdrawal
            self.current_capital -= withdrawal
            self.withdrawal_history.append({
                "date": datetime.now().strftime("%Y-%m-%d"),
                "amount": withdrawal,
                "monthly_pnl": self.monthly_pnl,
            })
        
        stats = {
            "monthly_pnl": self.monthly_pnl,
            "withdrawal": withdrawal,
            "remaining_capital": self.current_capital,
            "total_withdrawn": self.total_withdrawn,
        }
        
        self.monthly_pnl = 0.0
        return stats

    # =========================================================================
    # REPORTING
    # =========================================================================

    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive money management summary."""
        return {
            "initial_capital": self.initial_capital,
            "current_capital": self.current_capital,
            "total_pnl": self.total_pnl,
            "total_return_pct": (self.total_pnl / self.initial_capital * 100) if self.initial_capital > 0 else 0,
            "peak_capital": self.peak_capital,
            "max_drawdown_pct": self.drawdown_depth,
            "compounded_total": self.compounded_total,
            "total_withdrawn": self.total_withdrawn,
            "position_multiplier": self.get_position_multiplier(),
            "in_drawdown": self.in_drawdown,
            "size_reduction_active": self.size_reduction_active,
            "daily_target_reached": self.daily_target_reached,
            "reserve_amount": self.current_capital * self.reserve_percent,
        }
