"""
AlgoTrade Pro - Main Application Entry Point
==============================================
Institutional-Grade Algorithmic Trading Platform
for Flattrade API with Python/PyQt5.

Supports:
- Fully automated strategy execution
- Semi-automated button-based trading
- Real-time market analytics dashboard
- Advanced risk & money management

Usage:
    python main.py                  # Launch full dashboard
    python main.py --headless       # Run strategies without GUI
    python main.py --config custom.yaml  # Use custom config
"""

import sys
import os
import signal
import logging
import argparse
from datetime import datetime
from pathlib import Path

import yaml

# Add project root to path
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.flattrade_api import FlattradeAPI
from core.auth_helper import AuthHelper
from core.order_manager import OrderManager
from core.risk_manager import RiskManager
from core.money_manager import MoneyManager
from core.market_data import MarketDataEngine
from core.strategy_engine import StrategyEngine
from core.connection_validator import ConnectionValidator

logger = logging.getLogger("AlgoTrade")



def setup_logging(config: dict) -> None:
    """Configure application logging."""
    log_config = config.get("logging", {})
    log_level = getattr(logging, log_config.get("level", "INFO"))
    log_dir = log_config.get("log_directory", "logs")
    
    os.makedirs(log_dir, exist_ok=True)
    
    log_file = os.path.join(
        log_dir, f"algotrade_{datetime.now().strftime('%Y%m%d')}.log"
    )
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, mode='a'),
        ]
    )
    
    logger.info("=" * 70)
    logger.info("AlgoTrade Pro - Starting")
    logger.info("=" * 70)


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        config_path = os.path.join(PROJECT_ROOT, "config", "settings.yaml")
    
    if not os.path.exists(config_path):
        logger.error("Config file not found: %s", config_path)
        sys.exit(1)
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    logger.info("Configuration loaded from: %s", config_path)
    return config



class TradingSystem:
    """
    Master trading system orchestrator.
    Coordinates all modules: API, Orders, Risk, Money, Market Data, Strategy.
    """

    def __init__(self, config: dict):
        self.config = config
        self.is_running = False
        self.is_paused = False
        
        # Initialize core modules
        logger.info("Initializing trading system modules...")
        
        # API Client
        api_config = {**config.get("api", {}), **config.get("account", {})}
        self.api = FlattradeAPI(api_config)
        
        # Order Manager
        self.order_manager = OrderManager(self.api, config.get("orders", {}))
        
        # Risk Manager
        self.risk_manager = RiskManager(config.get("risk_management", {}))
        
        # Money Manager
        money_config = {**config.get("money_management", {}), 
                       "total_capital": config.get("risk_management", {}).get("total_capital", 500000)}
        self.money_manager = MoneyManager(money_config)
        
        # Market Data Engine
        self.market_data = MarketDataEngine(self.api, config)
        
        # Strategy Engine
        self.strategy = StrategyEngine(
            self.market_data,
            self.risk_manager,
            self.money_manager,
            config.get("strategy", {}).get("primary", {}),
        )
        
        # Wire up callbacks
        self._setup_callbacks()
        
        logger.info("Trading system initialized successfully")

    def _setup_callbacks(self):
        """Connect module callbacks."""
        # Order updates -> Risk Manager
        self.order_manager.on_order_update(self._on_order_update)
        self.order_manager.on_position_update(self._on_position_update)
        
        # Strategy signals
        self.strategy.on_signal(self._on_signal)
        
        # WebSocket callbacks
        self.api.on("quote_update", self._on_quote)
        self.api.on("depth_update", self._on_depth)
        self.api.on("order_update", self.order_manager.handle_order_update)

    # =========================================================================
    # AUTHENTICATION & CONNECTION
    # =========================================================================

    def connect(self, request_token: str) -> bool:
        """Authenticate and establish connections."""
        # Authenticate REST API
        result = self.api.authenticate(request_token)
        if result["status"] != "success":
            logger.error("Authentication failed: %s", result.get("message"))
            return False
        
        # Connect WebSocket
        ws_connected = self.api.connect_websocket()
        if not ws_connected:
            logger.warning("WebSocket connection failed, will retry...")
        
        # Subscribe to order updates
        self.api.subscribe_orders()
        
        # Run system health check
        validator = ConnectionValidator(self)
        all_ok, report = validator.run_full_check()
        
        if not all_ok:
            logger.warning("Some health checks failed - review before trading")
            print("\n" + validator.get_summary_string() + "\n")
        else:
            print("\n" + validator.get_summary_string() + "\n")
        
        self.is_running = True
        logger.info("Trading system connected and ready")
        return True

    def verify_system(self):
        """
        Run system verification without connecting.
        Use this to check if credentials and config are valid.
        
        Returns:
            (all_passed: bool, summary_string: str)
        """
        validator = ConnectionValidator(self)
        all_ok, report = validator.run_full_check()
        return all_ok, validator.get_summary_string()

    # =========================================================================
    # TRADING OPERATIONS
    # =========================================================================

    def execute_manual_trade(
        self, index: str, option_type: str, action: str,
        lots: int = 1, order_type: str = "MARKET"
    ) -> dict:
        """Execute a manual trade from dashboard buttons."""
        if self.is_paused:
            return {"status": "error", "message": "Trading is paused"}
        
        # Risk check
        can_trade, reason = self.risk_manager.can_trade()
        if not can_trade:
            logger.warning("Trade blocked by risk manager: %s", reason)
            return {"status": "blocked", "message": reason}
        
        # Get ATM strike
        atm_strike = self.market_data.get_atm_strike(index)
        if atm_strike == 0:
            return {"status": "error", "message": "Cannot determine ATM strike"}
        
        # Build trading symbol
        lot_sizes = self.config.get("orders", {}).get("lot_sizes", {})
        lot_size = lot_sizes.get(index, 25)
        quantity = lots * lot_size
        
        # Map order type
        order_type_map = {
            "MARKET": "MKT", "LIMIT": "LMT",
            "SL-MARKET": "SL-MKT", "SL-LIMIT": "SL-LMT"
        }
        ot = order_type_map.get(order_type, "MKT")
        
        # Transaction type
        trans_type = "B" if action == "BUY" else "S"
        
        # Construct symbol (simplified - needs actual symbol lookup)
        tradingsymbol = f"{index}{atm_strike}{option_type}"
        
        # Place order
        result = self.order_manager.place_order(
            exchange="NFO",
            tradingsymbol=tradingsymbol,
            transaction_type=trans_type,
            quantity=quantity,
            order_type=ot,
            product_type="I",
            remarks=f"MANUAL_{index}_{option_type}",
            strategy_id="manual",
        )
        
        logger.info("Manual trade: %s %s %s x%d -> %s",
                   action, index, option_type, lots, result["status"])
        return result

    def square_off_all(self):
        """Square off all positions."""
        self.order_manager.cancel_all_orders()
        return self.order_manager.square_off_all()

    def cancel_all_orders(self):
        """Cancel all pending orders."""
        return self.order_manager.cancel_all_orders()

    def start_strategy(self, mode: str = "semi_auto"):
        """Start automated strategy."""
        self.strategy.state.mode = mode
        self.strategy.start()

    def stop_strategy(self):
        """Stop automated strategy."""
        self.strategy.stop()

    def pause_trading(self):
        """Pause all trading."""
        self.is_paused = not self.is_paused
        state = "PAUSED" if self.is_paused else "RESUMED"
        logger.info("Trading %s", state)

    def reset_circuit_breaker(self):
        """Reset circuit breaker."""
        self.risk_manager.reset_circuit()



    # =========================================================================
    # CALLBACKS
    # =========================================================================

    def _on_quote(self, data: dict):
        """Handle real-time quote updates."""
        self.market_data.process_tick(data)

    def _on_depth(self, data: dict):
        """Handle market depth updates."""
        pass  # Processed by market data engine

    def _on_order_update(self, order):
        """Handle order status changes."""
        logger.info("Order update: %s -> %s", order.order_id, order.status.value)

    def _on_position_update(self, positions):
        """Handle position changes."""
        # Update risk manager
        self.risk_manager.open_position_count = len(
            [p for p in positions.values() if p.quantity != 0]
        )
        
        # Update unrealized P&L
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        self.risk_manager.update_pnl(unrealized)

    def _on_signal(self, signal):
        """Handle new trading signal from strategy (already passed quality filter)."""
        mode = self.strategy.state.mode
        
        if mode == "full_auto":
            # Signal already passed quality filter - execute!
            can_trade, reason = self.risk_manager.can_trade()
            if can_trade:
                self._execute_signal(signal)
            else:
                logger.info("Signal passed quality filter but BLOCKED by risk manager: %s", reason)
        elif mode == "semi_auto":
            # Show on dashboard for manual confirmation
            quality_grade = signal.factors.get("quality_grade", "?")
            logger.info(
                "SIGNAL READY [%s] (semi-auto): %s %s %s | Confidence=%d%% | "
                "Waiting for user confirmation...",
                quality_grade, signal.signal_type.value, signal.instrument,
                signal.option_type, signal.confidence
            )

    def _execute_signal(self, signal):
        """Execute a trading signal with quality-adjusted position sizing."""
        if signal.signal_type.value.startswith("BUY"):
            action = "BUY"
        else:
            action = "SELL"
        
        # Position sizing from risk manager
        lots = self.risk_manager.calculate_position_size(
            entry_price=signal.entry_price,
            stop_loss_price=signal.stop_loss,
            lot_size=self.config.get("orders", {}).get("lot_sizes", {}).get(signal.instrument, 25),
        )
        
        # Apply money management multiplier
        money_multiplier = self.money_manager.get_position_multiplier()
        lots = max(1, int(lots * money_multiplier))
        
        # Apply QUALITY-BASED size multiplier (from Trade Quality Filter)
        # A+ grade = 1.5x, A/B = 1.0x, C = 0.5x
        quality_multiplier = signal.factors.get("size_multiplier", 1.0)
        lots = max(1, int(lots * quality_multiplier))
        
        quality_grade = signal.factors.get("quality_grade", "?")
        logger.info(
            "EXECUTING signal [Quality: %s | Size: %dx lots | Multiplier: %.1fx]: "
            "%s %s %s",
            quality_grade, lots, quality_multiplier,
            action, signal.instrument, signal.option_type
        )
        
        self.execute_manual_trade(
            index=signal.instrument,
            option_type=signal.option_type,
            action=action,
            lots=lots,
        )

    # =========================================================================
    # STATUS
    # =========================================================================

    def get_status(self) -> dict:
        """Get complete system status."""
        return {
            "connected": self.api.is_authenticated(),
            "ws_connected": self.api._ws_connected,
            "running": self.is_running,
            "paused": self.is_paused,
            "strategy_active": self.strategy.state.active,
            "strategy_mode": self.strategy.state.mode,
            "risk_level": self.risk_manager.current_risk_level.value,
            "circuit_state": self.risk_manager.circuit_state.value,
            "daily_pnl": self.risk_manager.daily_pnl,
            "positions": self.risk_manager.open_position_count,
            "trades_today": len(self.risk_manager.trades_today),
        }

    def shutdown(self):
        """Graceful shutdown."""
        logger.info("Shutting down trading system...")
        self.strategy.stop()
        self.order_manager.cancel_all_orders()
        self.api.disconnect_websocket()
        self.is_running = False
        logger.info("Trading system shutdown complete")



# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def main():
    """Main application entry point."""
    parser = argparse.ArgumentParser(description="AlgoTrade Pro - Trading Platform")
    parser.add_argument("--config", type=str, help="Path to config file")
    parser.add_argument("--headless", action="store_true", help="Run without GUI")
    parser.add_argument("--token", type=str, help="API request token")
    parser.add_argument("--verify", action="store_true", help="Run system verification only")
    args = parser.parse_args()
    
    # Load configuration
    config = load_config(args.config)
    
    # Setup logging
    setup_logging(config)
    
    # Initialize trading system
    trading_system = TradingSystem(config)
    
    # Handle shutdown gracefully
    def signal_handler(sig, frame):
        logger.info("Shutdown signal received")
        trading_system.shutdown()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Verify-only mode
    if args.verify:
        logger.info("Running system verification...")
        ok, summary = trading_system.verify_system()
        print(summary)
        sys.exit(0 if ok else 1)
    
    # Authentication
    request_token = args.token
    if not request_token:
        # Launch browser-based login
        auth = AuthHelper(config.get("account", {}))
        logger.info("No token provided. Launching browser login...")
        request_token = auth.login_via_browser()
        
        if not request_token:
            logger.error("Authentication failed! Could not obtain token.")
            logger.error("You can also pass token manually: python main.py --token YOUR_TOKEN")
            sys.exit(1)
    
    # Connect and validate
    if not trading_system.connect(request_token):
        logger.error("Failed to connect to Flattrade. Exiting.")
        sys.exit(1)
    
    if args.headless:
        # Headless mode - strategy only
        logger.info("Running in headless mode (full auto)")
        trading_system.start_strategy("full_auto")
        
        # Keep running
        import time
        try:
            while trading_system.is_running:
                time.sleep(1)
        except KeyboardInterrupt:
            trading_system.shutdown()
    else:
        # GUI mode
        from PyQt5.QtWidgets import QApplication
        from gui.dashboard import TradingDashboard
        
        app = QApplication(sys.argv)
        app.setStyle("Fusion")
        
        dashboard = TradingDashboard(trading_system)
        dashboard.show()
        
        logger.info("Dashboard launched - Ready for trading")
        
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
