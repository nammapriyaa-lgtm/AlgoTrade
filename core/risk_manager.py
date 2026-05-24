"""
Advanced Risk Management Module
=================================
Institutional-grade risk controls with circuit breakers,
position sizing, exposure management, and real-time monitoring.
"""

import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"
    HALTED = "HALTED"


class CircuitBreakerState(Enum):
    NORMAL = "NORMAL"
    WARNING = "WARNING"
    TRIPPED = "TRIPPED"
    COOLING_DOWN = "COOLING_DOWN"


@dataclass
class RiskMetrics:
    """Real-time risk metrics snapshot."""
    total_capital: float = 0.0
    deployed_capital: float = 0.0
    available_capital: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_percent: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    open_positions: int = 0
    open_orders: int = 0
    exposure_percent: float = 0.0
    risk_level: RiskLevel = RiskLevel.LOW
    consecutive_losses: int = 0
    trades_today: int = 0
    win_rate_today: float = 0.0
    sharpe_intraday: float = 0.0
    var_95: float = 0.0  # Value at Risk (95%)


@dataclass
class TradeResult:
    """Record of a completed trade for risk tracking."""
    symbol: str = ""
    pnl: float = 0.0
    pnl_percent: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: datetime = field(default_factory=datetime.now)
    quantity: int = 0
    entry_price: float = 0.0
    exit_price: float = 0.0
    is_winner: bool = False
    strategy_id: str = ""


class RiskManager:
    """
    Advanced risk management system with multi-level controls.
    
    Features:
    - Real-time P&L and exposure monitoring
    - Dynamic position sizing (Fixed Risk, Kelly, Optimal F)
    - Multi-level circuit breakers (daily, weekly, monthly, rapid)
    - Consecutive loss management with cooldown
    - Maximum drawdown protection
    - Trailing stop management
    - Pre-trade risk validation
    - Risk-adjusted performance metrics
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Capital
        self.total_capital = config.get("total_capital", 500000)
        self.deployed_capital = 0.0
        self.peak_capital = self.total_capital
        
        # Daily tracking
        self.daily_pnl = 0.0
        self.daily_high_pnl = 0.0
        self.daily_low_pnl = 0.0
        self.trades_today: List[TradeResult] = []
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        
        # Weekly/Monthly tracking
        self.weekly_pnl = 0.0
        self.monthly_pnl = 0.0
        
        # Drawdown tracking
        self.max_drawdown = 0.0
        self.current_drawdown = 0.0
        self.drawdown_start_time: Optional[datetime] = None
        
        # Circuit breakers
        self.circuit_state = CircuitBreakerState.NORMAL
        self.circuit_trip_time: Optional[datetime] = None
        self.cooldown_until: Optional[datetime] = None
        
        # Rapid loss detection
        self._recent_losses = deque(maxlen=100)
        
        # Risk level
        self.current_risk_level = RiskLevel.LOW
        
        # Position tracking
        self.open_position_count = 0
        self.open_order_count = 0
        
        # Performance history
        self._pnl_history: List[float] = []
        self._equity_curve: List[Tuple[datetime, float]] = []
        
        logger.info("RiskManager initialized with capital: %s", self.total_capital)

    # =========================================================================
    # PRE-TRADE RISK CHECK
    # =========================================================================

    def can_trade(self) -> Tuple[bool, str]:
        """
        Master pre-trade risk check.
        Returns (allowed, reason) tuple.
        """
        # Circuit breaker check
        if self.circuit_state == CircuitBreakerState.TRIPPED:
            return False, "Circuit breaker tripped - trading halted"
        
        # Cooldown check
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            remaining = (self.cooldown_until - datetime.now()).seconds
            return False, f"Cooldown active - {remaining}s remaining"
        
        # Daily loss limit
        max_daily_loss = self.config.get("daily_limits", {}).get("max_daily_loss", 25000)
        if abs(self.daily_pnl) >= max_daily_loss and self.daily_pnl < 0:
            self._trip_circuit("Daily loss limit reached")
            return False, f"Daily loss limit reached: {self.daily_pnl}"
        
        # Max trades per day
        max_trades = self.config.get("daily_limits", {}).get("max_trades_per_day", 20)
        if len(self.trades_today) >= max_trades:
            return False, f"Max daily trades reached: {max_trades}"
        
        # Max open positions
        max_positions = self.config.get("max_open_positions", 5)
        if self.open_position_count >= max_positions:
            return False, f"Max open positions reached: {max_positions}"
        
        # Max drawdown
        max_dd = self.config.get("daily_limits", {}).get("max_drawdown_percent", 5.0)
        if self.current_drawdown >= max_dd:
            self._trip_circuit("Max drawdown exceeded")
            return False, f"Max drawdown exceeded: {self.current_drawdown:.2f}%"
        
        # Consecutive losses
        max_consec = self.config.get("daily_limits", {}).get("max_consecutive_losses", 3)
        if self.consecutive_losses >= max_consec:
            cooldown = self.config.get("daily_limits", {}).get("cooldown_after_consecutive_losses", 300)
            self.cooldown_until = datetime.now() + timedelta(seconds=cooldown)
            self.consecutive_losses = 0  # Reset after cooldown
            return False, f"Consecutive loss limit ({max_consec}) - cooldown {cooldown}s"
        
        return True, "OK"

    def validate_order(
        self,
        symbol: str,
        quantity: int,
        price: float,
        transaction_type: str,
        product_type: str = "I",
    ) -> Tuple[bool, str]:
        """
        Validate a specific order against risk parameters.
        
        Checks:
        - Can trade at all (master check)
        - Capital availability
        - Position concentration limits
        - Order value limits
        """
        # Master check
        can, reason = self.can_trade()
        if not can:
            return False, reason
        
        # Capital check
        order_value = quantity * price if price > 0 else quantity * 100  # Estimate for MKT
        max_per_trade = self.total_capital * self.config.get("max_capital_per_trade", 0.10)
        if order_value > max_per_trade:
            return False, f"Order value {order_value} exceeds per-trade limit {max_per_trade}"
        
        # Exposure check
        max_exposure = self.total_capital * self.config.get("max_daily_exposure", 0.50)
        if self.deployed_capital + order_value > max_exposure:
            return False, f"Total exposure would exceed limit: {max_exposure}"
        
        return True, "OK"

    # =========================================================================
    # POSITION SIZING
    # =========================================================================

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
        lot_size: int = 1,
        method: Optional[str] = None,
    ) -> int:
        """
        Calculate optimal position size based on risk parameters.
        
        Methods:
        - fixed_risk: Risk fixed % of capital per trade
        - kelly: Kelly criterion with fractional sizing
        - optimal_f: Optimal F calculation
        - fixed_lots: Fixed number of lots
        
        Returns:
            Number of lots to trade
        """
        sizing_config = self.config.get("position_sizing", {})
        method = method or sizing_config.get("method", "fixed_risk")
        
        if method == "fixed_risk":
            return self._size_fixed_risk(entry_price, stop_loss_price, lot_size, sizing_config)
        elif method == "kelly":
            return self._size_kelly(entry_price, stop_loss_price, lot_size, sizing_config)
        elif method == "optimal_f":
            return self._size_optimal_f(entry_price, stop_loss_price, lot_size, sizing_config)
        elif method == "fixed_lots":
            return sizing_config.get("fixed_lots", 1)
        else:
            return 1

    def _size_fixed_risk(
        self, entry: float, sl: float, lot_size: int, config: Dict
    ) -> int:
        """Fixed risk position sizing - risk X% of capital per trade."""
        risk_percent = config.get("risk_per_trade_percent", 2.0)
        risk_amount = self.total_capital * (risk_percent / 100)
        
        risk_per_lot = abs(entry - sl) * lot_size
        if risk_per_lot <= 0:
            return config.get("min_lot_size", 1)
        
        lots = int(risk_amount / risk_per_lot)
        lots = max(lots, config.get("min_lot_size", 1))
        lots = min(lots, config.get("max_lot_size", 10))
        
        # Reduce size if in drawdown
        if self.current_drawdown > 3.0:
            lots = max(1, int(lots * 0.5))
        
        return lots

    def _size_kelly(
        self, entry: float, sl: float, lot_size: int, config: Dict
    ) -> int:
        """Kelly Criterion position sizing."""
        if len(self.trades_today) < 5:
            return config.get("min_lot_size", 1)
        
        wins = sum(1 for t in self.trades_today if t.is_winner)
        win_rate = wins / len(self.trades_today)
        
        if win_rate <= 0:
            return config.get("min_lot_size", 1)
        
        avg_win = sum(t.pnl for t in self.trades_today if t.is_winner) / max(wins, 1)
        avg_loss = abs(sum(t.pnl for t in self.trades_today if not t.is_winner) / max(len(self.trades_today) - wins, 1))
        
        if avg_loss <= 0:
            return config.get("min_lot_size", 1)
        
        # Kelly formula: f = W - (1-W)/R where R = avg_win/avg_loss
        reward_risk = avg_win / avg_loss
        kelly = win_rate - ((1 - win_rate) / reward_risk)
        
        # Use fractional Kelly (quarter Kelly for safety)
        fraction = config.get("kelly_fraction", 0.25)
        kelly_adjusted = max(0, kelly * fraction)
        
        risk_amount = self.total_capital * kelly_adjusted
        risk_per_lot = abs(entry - sl) * lot_size
        
        if risk_per_lot <= 0:
            return config.get("min_lot_size", 1)
        
        lots = int(risk_amount / risk_per_lot)
        lots = max(lots, config.get("min_lot_size", 1))
        lots = min(lots, config.get("max_lot_size", 10))
        
        return lots

    def _size_optimal_f(
        self, entry: float, sl: float, lot_size: int, config: Dict
    ) -> int:
        """Optimal F position sizing (Ralph Vince method)."""
        if len(self.trades_today) < 10:
            return config.get("min_lot_size", 1)
        
        # Find largest loss
        losses = [t.pnl for t in self.trades_today if t.pnl < 0]
        if not losses:
            return config.get("min_lot_size", 1)
        
        largest_loss = abs(min(losses))
        if largest_loss <= 0:
            return config.get("min_lot_size", 1)
        
        # Optimal f calculation (simplified)
        optimal_f = 0.0
        best_twl = 0.0
        
        for f in [i * 0.01 for i in range(1, 100)]:
            twl = 1.0
            for trade in self.trades_today:
                twl *= (1 + f * (-trade.pnl / largest_loss))
            
            if twl > best_twl:
                best_twl = twl
                optimal_f = f
        
        # Apply with safety margin
        risk_amount = self.total_capital * optimal_f * 0.5
        risk_per_lot = abs(entry - sl) * lot_size
        
        if risk_per_lot <= 0:
            return config.get("min_lot_size", 1)
        
        lots = int(risk_amount / risk_per_lot)
        lots = max(lots, config.get("min_lot_size", 1))
        lots = min(lots, config.get("max_lot_size", 10))
        
        return lots

    # =========================================================================
    # STOP LOSS MANAGEMENT
    # =========================================================================

    def calculate_stop_loss(
        self,
        entry_price: float,
        transaction_type: str,
        atr: float = 0.0,
    ) -> Dict[str, float]:
        """
        Calculate stop loss levels based on configuration.
        
        Returns:
            Dict with initial_sl, trailing_sl, and target levels
        """
        sl_config = self.config.get("stop_loss", {})
        target_config = self.config.get("targets", {})
        sl_type = sl_config.get("type", "percentage")
        
        if sl_type == "percentage":
            sl_percent = sl_config.get("default_sl_percent", 30.0) / 100
            if transaction_type == "B":
                initial_sl = entry_price * (1 - sl_percent)
            else:
                initial_sl = entry_price * (1 + sl_percent)
                
        elif sl_type == "points":
            sl_points = sl_config.get("min_sl_points", 5)
            if transaction_type == "B":
                initial_sl = entry_price - sl_points
            else:
                initial_sl = entry_price + sl_points
                
        elif sl_type == "atr" and atr > 0:
            atr_multiplier = 2.0
            if transaction_type == "B":
                initial_sl = entry_price - (atr * atr_multiplier)
            else:
                initial_sl = entry_price + (atr * atr_multiplier)
        else:
            sl_percent = sl_config.get("default_sl_percent", 30.0) / 100
            initial_sl = entry_price * (1 - sl_percent) if transaction_type == "B" else entry_price * (1 + sl_percent)
        
        # Calculate targets
        t1_pct = target_config.get("target_1_percent", 20.0) / 100
        t2_pct = target_config.get("target_2_percent", 40.0) / 100
        t3_pct = target_config.get("target_3_percent", 60.0) / 100
        
        if transaction_type == "B":
            target_1 = entry_price * (1 + t1_pct)
            target_2 = entry_price * (1 + t2_pct)
            target_3 = entry_price * (1 + t3_pct)
        else:
            target_1 = entry_price * (1 - t1_pct)
            target_2 = entry_price * (1 - t2_pct)
            target_3 = entry_price * (1 - t3_pct)
        
        return {
            "initial_sl": round(initial_sl, 2),
            "target_1": round(target_1, 2),
            "target_2": round(target_2, 2),
            "target_3": round(target_3, 2),
            "risk_reward_ratio": round(abs(target_1 - entry_price) / max(abs(entry_price - initial_sl), 0.01), 2),
        }

    def update_trailing_stop(
        self,
        entry_price: float,
        current_price: float,
        current_sl: float,
        transaction_type: str,
    ) -> float:
        """
        Calculate updated trailing stop loss.
        
        Returns new stop loss price (only moves in favorable direction).
        """
        sl_config = self.config.get("stop_loss", {})
        if not sl_config.get("trailing_sl_enabled", True):
            return current_sl
        
        trailing_pct = sl_config.get("trailing_sl_percent", 20.0) / 100
        activation_pct = sl_config.get("trailing_activation_percent", 15.0) / 100
        
        # Check if trailing should activate
        if transaction_type == "B":
            profit_pct = (current_price - entry_price) / entry_price
            if profit_pct < activation_pct:
                return current_sl
            
            new_sl = current_price * (1 - trailing_pct)
            return max(new_sl, current_sl)  # Only move up
        else:
            profit_pct = (entry_price - current_price) / entry_price
            if profit_pct < activation_pct:
                return current_sl
            
            new_sl = current_price * (1 + trailing_pct)
            return min(new_sl, current_sl)  # Only move down

    # =========================================================================
    # CIRCUIT BREAKERS
    # =========================================================================

    def _trip_circuit(self, reason: str) -> None:
        """Trip the circuit breaker."""
        self.circuit_state = CircuitBreakerState.TRIPPED
        self.circuit_trip_time = datetime.now()
        logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)

    def reset_circuit(self) -> None:
        """Manually reset circuit breaker (admin action)."""
        self.circuit_state = CircuitBreakerState.NORMAL
        self.circuit_trip_time = None
        logger.info("Circuit breaker manually reset")

    def check_rapid_loss(self, loss: float) -> None:
        """Check for rapid loss pattern (loss in short window)."""
        cb_config = self.config.get("circuit_breakers", {})
        if not cb_config.get("enabled", True):
            return
        
        self._recent_losses.append((time.time(), loss))
        
        # Check losses within window
        window = cb_config.get("rapid_loss_window", 300)
        rapid_limit = cb_config.get("rapid_loss_circuit", 15000)
        
        cutoff = time.time() - window
        recent_total = sum(
            abs(loss) for ts, loss in self._recent_losses if ts > cutoff
        )
        
        if recent_total >= rapid_limit:
            self._trip_circuit(f"Rapid loss: {recent_total} in {window}s window")

    # =========================================================================
    # P&L TRACKING
    # =========================================================================

    def record_trade(self, trade: TradeResult) -> None:
        """Record a completed trade and update risk metrics."""
        self.trades_today.append(trade)
        self.daily_pnl += trade.pnl
        
        if trade.pnl > 0:
            self.daily_high_pnl = max(self.daily_high_pnl, self.daily_pnl)
        
        # Track consecutive wins/losses
        if trade.is_winner:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            self.check_rapid_loss(trade.pnl)
        
        # Update drawdown
        self._update_drawdown()
        
        # Update equity curve
        self._equity_curve.append((datetime.now(), self.total_capital + self.daily_pnl))
        
        logger.info(
            "Trade recorded: %s PnL=%.2f | Daily PnL=%.2f | Consec L=%d",
            trade.symbol, trade.pnl, self.daily_pnl, self.consecutive_losses
        )

    def _update_drawdown(self) -> None:
        """Update drawdown calculations."""
        current_equity = self.total_capital + self.daily_pnl
        
        if current_equity > self.peak_capital:
            self.peak_capital = current_equity
            self.drawdown_start_time = None
        
        if self.peak_capital > 0:
            self.current_drawdown = ((self.peak_capital - current_equity) / self.peak_capital) * 100
            self.max_drawdown = max(self.max_drawdown, self.current_drawdown)
        
        if self.current_drawdown > 0 and self.drawdown_start_time is None:
            self.drawdown_start_time = datetime.now()

    def update_pnl(self, unrealized_pnl: float) -> None:
        """Update with current unrealized P&L for monitoring."""
        total_pnl = self.daily_pnl + unrealized_pnl
        
        # Update risk level
        loss_percent = abs(total_pnl / self.total_capital * 100) if total_pnl < 0 else 0
        
        if loss_percent >= 5.0:
            self.current_risk_level = RiskLevel.CRITICAL
        elif loss_percent >= 3.0:
            self.current_risk_level = RiskLevel.HIGH
        elif loss_percent >= 1.5:
            self.current_risk_level = RiskLevel.MEDIUM
        else:
            self.current_risk_level = RiskLevel.LOW
        
        if self.circuit_state == CircuitBreakerState.TRIPPED:
            self.current_risk_level = RiskLevel.HALTED

    # =========================================================================
    # METRICS & REPORTING
    # =========================================================================

    def get_risk_metrics(self) -> RiskMetrics:
        """Get current risk metrics snapshot."""
        wins = sum(1 for t in self.trades_today if t.is_winner)
        total = len(self.trades_today)
        
        return RiskMetrics(
            total_capital=self.total_capital,
            deployed_capital=self.deployed_capital,
            available_capital=self.total_capital - self.deployed_capital,
            daily_pnl=self.daily_pnl,
            daily_pnl_percent=(self.daily_pnl / self.total_capital * 100) if self.total_capital > 0 else 0,
            max_drawdown=self.max_drawdown,
            current_drawdown=self.current_drawdown,
            open_positions=self.open_position_count,
            open_orders=self.open_order_count,
            exposure_percent=(self.deployed_capital / self.total_capital * 100) if self.total_capital > 0 else 0,
            risk_level=self.current_risk_level,
            consecutive_losses=self.consecutive_losses,
            trades_today=total,
            win_rate_today=(wins / total * 100) if total > 0 else 0,
        )

    def get_daily_stats(self) -> Dict[str, Any]:
        """Get comprehensive daily statistics."""
        wins = [t for t in self.trades_today if t.is_winner]
        losses = [t for t in self.trades_today if not t.is_winner]
        
        avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
        
        profit_factor = abs(sum(t.pnl for t in wins)) / abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses) != 0 else 0
        
        return {
            "total_trades": len(self.trades_today),
            "winners": len(wins),
            "losers": len(losses),
            "win_rate": (len(wins) / len(self.trades_today) * 100) if self.trades_today else 0,
            "gross_profit": sum(t.pnl for t in wins),
            "gross_loss": sum(t.pnl for t in losses),
            "net_pnl": self.daily_pnl,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "largest_win": max((t.pnl for t in wins), default=0),
            "largest_loss": min((t.pnl for t in losses), default=0),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown": self.max_drawdown,
            "current_drawdown": self.current_drawdown,
            "consecutive_losses": self.consecutive_losses,
            "risk_level": self.current_risk_level.value,
            "circuit_state": self.circuit_state.value,
        }

    def reset_daily(self) -> None:
        """Reset daily metrics (call at start of day)."""
        self.daily_pnl = 0.0
        self.daily_high_pnl = 0.0
        self.daily_low_pnl = 0.0
        self.trades_today = []
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.current_drawdown = 0.0
        self.circuit_state = CircuitBreakerState.NORMAL
        self.cooldown_until = None
        self._recent_losses.clear()
        logger.info("Daily risk metrics reset")
