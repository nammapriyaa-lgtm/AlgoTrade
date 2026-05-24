"""
Order Management System
========================
Comprehensive order lifecycle management with slicing,
validation, tracking, and execution analytics.
"""

import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    TRIGGER_PENDING = "TRIGGER_PENDING"
    MODIFIED = "MODIFIED"
    PARTIAL = "PARTIAL"


@dataclass
class Order:
    """Represents a trading order with full lifecycle tracking."""
    order_id: str = ""
    broker_order_id: str = ""
    exchange: str = ""
    tradingsymbol: str = ""
    transaction_type: str = ""  # B or S
    quantity: int = 0
    filled_quantity: int = 0
    pending_quantity: int = 0
    order_type: str = "MKT"
    product_type: str = "I"
    price: float = 0.0
    trigger_price: float = 0.0
    average_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    remarks: str = ""
    parent_order_id: str = ""  # For sliced orders
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    executed_at: Optional[datetime] = None
    
    # Execution Metrics
    slippage: float = 0.0
    execution_time_ms: float = 0.0
    
    # Strategy Link
    strategy_id: str = ""
    signal_id: str = ""


@dataclass
class Position:
    """Represents an open position."""
    symbol: str = ""
    exchange: str = ""
    product_type: str = "I"
    quantity: int = 0
    buy_quantity: int = 0
    sell_quantity: int = 0
    buy_average: float = 0.0
    sell_average: float = 0.0
    ltp: float = 0.0
    pnl: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    
    # Risk Parameters
    stop_loss: float = 0.0
    target: float = 0.0
    trailing_sl: float = 0.0
    max_pnl: float = 0.0
    
    # Metadata
    entry_time: datetime = field(default_factory=datetime.now)
    strategy_id: str = ""


class OrderManager:
    """
    Professional-grade order management system.
    
    Features:
    - Order validation and pre-checks
    - Smart order slicing for large quantities
    - Real-time order tracking and status updates
    - Position aggregation and P&L calculation
    - Auto square-off at specified time
    - Execution analytics and slippage tracking
    """

    def __init__(self, api, config: Dict[str, Any]):
        self.api = api
        self.config = config
        
        # Order tracking
        self.orders: Dict[str, Order] = {}
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict] = []
        
        # Execution metrics
        self.total_orders_today = 0
        self.total_trades_today = 0
        self.successful_orders = 0
        self.rejected_orders = 0
        self.total_slippage = 0.0
        
        # Callbacks
        self._order_callbacks: List[Callable] = []
        self._position_callbacks: List[Callable] = []
        
        # Auto square-off
        self._square_off_timer: Optional[threading.Timer] = None
        self._setup_auto_square_off()
        
        # Order queue for execution
        self._order_queue = deque()
        self._processing = False
        
        logger.info("OrderManager initialized")

    # =========================================================================
    # ORDER PLACEMENT
    # =========================================================================

    def place_order(
        self,
        exchange: str,
        tradingsymbol: str,
        transaction_type: str,
        quantity: int,
        order_type: str = "MKT",
        product_type: str = "I",
        price: float = 0.0,
        trigger_price: float = 0.0,
        remarks: str = "",
        strategy_id: str = "",
        signal_id: str = "",
        slice_order: bool = True,
    ) -> Dict[str, Any]:
        """
        Place order with validation, slicing, and tracking.
        
        Returns:
            Dict with order details and status
        """
        # Pre-validation
        validation = self._validate_order(
            exchange, tradingsymbol, transaction_type, quantity, order_type, price
        )
        if not validation["valid"]:
            return {"status": "error", "message": validation["message"]}
        
        # Check if order slicing needed
        freeze_qty = self._get_freeze_quantity(tradingsymbol)
        if slice_order and quantity > freeze_qty:
            return self._place_sliced_order(
                exchange, tradingsymbol, transaction_type, quantity,
                order_type, product_type, price, trigger_price,
                remarks, strategy_id, signal_id, freeze_qty
            )
        
        # Create order object
        order = Order(
            order_id=self._generate_order_id(),
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            quantity=quantity,
            pending_quantity=quantity,
            order_type=order_type,
            product_type=product_type,
            price=price,
            trigger_price=trigger_price,
            remarks=remarks,
            strategy_id=strategy_id,
            signal_id=signal_id,
        )
        
        # Execute order
        start_time = time.time()
        
        result = self.api.place_order(
            exchange=exchange,
            tradingsymbol=tradingsymbol,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type=order_type,
            product_type=product_type,
            price=price,
            trigger_price=trigger_price,
            remarks=remarks,
        )
        
        execution_time = (time.time() - start_time) * 1000
        order.execution_time_ms = execution_time
        
        if result["status"] == "success":
            order.broker_order_id = result["data"].get("norenordno", "")
            order.status = OrderStatus.OPEN
            self.successful_orders += 1
            logger.info(
                "Order placed: %s %s %s qty=%d | Exec time: %.1fms",
                transaction_type, tradingsymbol, order_type, quantity, execution_time
            )
        else:
            order.status = OrderStatus.REJECTED
            self.rejected_orders += 1
            logger.warning("Order rejected: %s - %s", tradingsymbol, result["message"])
        
        # Track order
        self.orders[order.order_id] = order
        self.total_orders_today += 1
        
        # Notify callbacks
        self._notify_order_update(order)
        
        return {
            "status": result["status"],
            "order_id": order.order_id,
            "broker_order_id": order.broker_order_id,
            "execution_time_ms": execution_time,
            "message": result.get("message", ""),
        }

    def _place_sliced_order(
        self, exchange, tradingsymbol, transaction_type, quantity,
        order_type, product_type, price, trigger_price,
        remarks, strategy_id, signal_id, freeze_qty
    ) -> Dict[str, Any]:
        """Place large orders in slices within freeze limits."""
        parent_id = self._generate_order_id()
        slices = []
        remaining = quantity
        
        while remaining > 0:
            slice_qty = min(remaining, freeze_qty)
            result = self.place_order(
                exchange=exchange,
                tradingsymbol=tradingsymbol,
                transaction_type=transaction_type,
                quantity=slice_qty,
                order_type=order_type,
                product_type=product_type,
                price=price,
                trigger_price=trigger_price,
                remarks=f"{remarks}_slice",
                strategy_id=strategy_id,
                signal_id=signal_id,
                slice_order=False,  # Prevent recursive slicing
            )
            slices.append(result)
            remaining -= slice_qty
            
            if result["status"] == "error":
                logger.error("Slice order failed at qty %d/%d", quantity - remaining, quantity)
                break
            
            time.sleep(0.1)  # Small delay between slices
        
        return {
            "status": "success" if all(s["status"] == "success" for s in slices) else "partial",
            "parent_order_id": parent_id,
            "slices": slices,
            "total_quantity": quantity,
            "filled_slices": sum(1 for s in slices if s["status"] == "success"),
        }

    # =========================================================================
    # ORDER MODIFICATION & CANCELLATION
    # =========================================================================

    def modify_order(
        self, order_id: str, price: float = 0.0,
        trigger_price: float = 0.0, quantity: int = 0
    ) -> Dict[str, Any]:
        """Modify an existing order."""
        order = self.orders.get(order_id)
        if not order:
            return {"status": "error", "message": "Order not found"}
        
        if order.status not in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING):
            return {"status": "error", "message": f"Cannot modify order in {order.status.value} status"}
        
        new_qty = quantity if quantity > 0 else order.quantity
        new_price = price if price > 0 else order.price
        new_trigger = trigger_price if trigger_price > 0 else order.trigger_price
        
        result = self.api.modify_order(
            order_no=order.broker_order_id,
            exchange=order.exchange,
            tradingsymbol=order.tradingsymbol,
            quantity=new_qty,
            order_type=order.order_type,
            price=new_price,
            trigger_price=new_trigger,
        )
        
        if result["status"] == "success":
            order.price = new_price
            order.trigger_price = new_trigger
            order.quantity = new_qty
            order.status = OrderStatus.MODIFIED
            order.updated_at = datetime.now()
            self._notify_order_update(order)
        
        return result

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an existing order."""
        order = self.orders.get(order_id)
        if not order:
            return {"status": "error", "message": "Order not found"}
        
        if order.status not in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING):
            return {"status": "error", "message": f"Cannot cancel order in {order.status.value} status"}
        
        result = self.api.cancel_order(order_no=order.broker_order_id)
        
        if result["status"] == "success":
            order.status = OrderStatus.CANCELLED
            order.updated_at = datetime.now()
            self._notify_order_update(order)
        
        return result

    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open/pending orders."""
        cancelled = 0
        failed = 0
        
        for order_id, order in self.orders.items():
            if order.status in (OrderStatus.OPEN, OrderStatus.TRIGGER_PENDING):
                result = self.cancel_order(order_id)
                if result["status"] == "success":
                    cancelled += 1
                else:
                    failed += 1
        
        return {"cancelled": cancelled, "failed": failed}

    # =========================================================================
    # POSITION MANAGEMENT
    # =========================================================================

    def update_positions(self) -> None:
        """Fetch and update current positions from broker."""
        result = self.api.get_positions()
        if result["status"] != "success":
            return
        
        positions_data = result.get("data", [])
        if isinstance(positions_data, dict):
            positions_data = [positions_data]
        
        for pos_data in positions_data:
            if isinstance(pos_data, dict):
                symbol = pos_data.get("tsym", "")
                if symbol:
                    position = Position(
                        symbol=symbol,
                        exchange=pos_data.get("exch", ""),
                        product_type=pos_data.get("prd", ""),
                        quantity=int(pos_data.get("netqty", 0)),
                        buy_quantity=int(pos_data.get("daybuyqty", 0)),
                        sell_quantity=int(pos_data.get("daysellqty", 0)),
                        buy_average=float(pos_data.get("daybuyavgprc", 0)),
                        sell_average=float(pos_data.get("daysellavgprc", 0)),
                        ltp=float(pos_data.get("lp", 0)),
                        unrealized_pnl=float(pos_data.get("urmtom", 0)),
                        realized_pnl=float(pos_data.get("rpnl", 0)),
                    )
                    position.pnl = position.unrealized_pnl + position.realized_pnl
                    self.positions[symbol] = position
        
        self._notify_position_update()

    def get_net_pnl(self) -> float:
        """Get total P&L across all positions."""
        return sum(pos.pnl for pos in self.positions.values())

    def get_open_positions(self) -> List[Position]:
        """Get list of positions with non-zero quantity."""
        return [pos for pos in self.positions.values() if pos.quantity != 0]

    def square_off_position(self, symbol: str) -> Dict[str, Any]:
        """Square off a specific position."""
        position = self.positions.get(symbol)
        if not position or position.quantity == 0:
            return {"status": "error", "message": "No open position for symbol"}
        
        # Determine exit transaction type
        transaction_type = "S" if position.quantity > 0 else "B"
        quantity = abs(position.quantity)
        
        return self.place_order(
            exchange=position.exchange,
            tradingsymbol=symbol,
            transaction_type=transaction_type,
            quantity=quantity,
            order_type="MKT",
            product_type=position.product_type,
            remarks="SQUARE_OFF",
        )

    def square_off_all(self) -> Dict[str, Any]:
        """Square off all open positions."""
        results = []
        for symbol in list(self.positions.keys()):
            if self.positions[symbol].quantity != 0:
                result = self.square_off_position(symbol)
                results.append({"symbol": symbol, "result": result})
        
        return {
            "squared_off": sum(1 for r in results if r["result"]["status"] == "success"),
            "failed": sum(1 for r in results if r["result"]["status"] != "success"),
            "details": results,
        }

    # =========================================================================
    # ORDER UPDATE HANDLER
    # =========================================================================

    def handle_order_update(self, update_data: Dict) -> None:
        """Process real-time order update from WebSocket."""
        broker_order_id = update_data.get("norenordno", "")
        status = update_data.get("status", "")
        
        # Find matching order
        for order in self.orders.values():
            if order.broker_order_id == broker_order_id:
                if status == "COMPLETE":
                    order.status = OrderStatus.COMPLETE
                    order.filled_quantity = order.quantity
                    order.pending_quantity = 0
                    order.average_price = float(update_data.get("avgprc", 0))
                    order.executed_at = datetime.now()
                    self.total_trades_today += 1
                    
                    # Calculate slippage
                    if order.price > 0:
                        order.slippage = abs(order.average_price - order.price)
                        self.total_slippage += order.slippage
                        
                elif status == "REJECTED":
                    order.status = OrderStatus.REJECTED
                elif status == "CANCELLED":
                    order.status = OrderStatus.CANCELLED
                elif status == "OPEN":
                    order.status = OrderStatus.OPEN
                elif status == "TRIGGER_PENDING":
                    order.status = OrderStatus.TRIGGER_PENDING
                
                order.updated_at = datetime.now()
                self._notify_order_update(order)
                break

    # =========================================================================
    # AUTO SQUARE-OFF
    # =========================================================================

    def _setup_auto_square_off(self):
        """Setup timer for auto square-off before market close."""
        sq_off_time_str = self.config.get("auto_square_off_time", "15:15:00")
        now = datetime.now()
        sq_off_time = datetime.strptime(
            f"{now.strftime('%Y-%m-%d')} {sq_off_time_str}", "%Y-%m-%d %H:%M:%S"
        )
        
        if sq_off_time > now:
            delay = (sq_off_time - now).total_seconds()
            self._square_off_timer = threading.Timer(delay, self._auto_square_off)
            self._square_off_timer.daemon = True
            self._square_off_timer.start()
            logger.info("Auto square-off scheduled at %s", sq_off_time_str)

    def _auto_square_off(self):
        """Execute auto square-off of all positions."""
        logger.warning("AUTO SQUARE-OFF TRIGGERED - Closing all positions")
        self.cancel_all_orders()
        time.sleep(1)
        self.square_off_all()

    # =========================================================================
    # CALLBACKS & NOTIFICATIONS
    # =========================================================================

    def on_order_update(self, callback: Callable) -> None:
        """Register callback for order updates."""
        self._order_callbacks.append(callback)

    def on_position_update(self, callback: Callable) -> None:
        """Register callback for position updates."""
        self._position_callbacks.append(callback)

    def _notify_order_update(self, order: Order) -> None:
        for cb in self._order_callbacks:
            try:
                cb(order)
            except Exception as e:
                logger.error("Order callback error: %s", str(e))

    def _notify_position_update(self) -> None:
        for cb in self._position_callbacks:
            try:
                cb(self.positions)
            except Exception as e:
                logger.error("Position callback error: %s", str(e))

    # =========================================================================
    # VALIDATION
    # =========================================================================

    def _validate_order(
        self, exchange, tradingsymbol, transaction_type, quantity, order_type, price
    ) -> Dict[str, Any]:
        """Validate order parameters before placement."""
        if not tradingsymbol:
            return {"valid": False, "message": "Trading symbol required"}
        if quantity <= 0:
            return {"valid": False, "message": "Quantity must be positive"}
        if transaction_type not in ("B", "S"):
            return {"valid": False, "message": "Invalid transaction type"}
        if order_type not in ("MKT", "LMT", "SL-LMT", "SL-MKT"):
            return {"valid": False, "message": "Invalid order type"}
        if order_type in ("LMT", "SL-LMT") and price <= 0:
            return {"valid": False, "message": "Price required for limit orders"}
        if exchange not in ("NSE", "NFO", "BSE", "BFO", "MCX"):
            return {"valid": False, "message": "Invalid exchange"}
        
        # Check max order value
        max_value = self.config.get("max_order_value", 500000)
        if price * quantity > max_value and price > 0:
            return {"valid": False, "message": f"Order value exceeds max: {max_value}"}
        
        return {"valid": True, "message": "OK"}

    def _get_freeze_quantity(self, tradingsymbol: str) -> int:
        """Get exchange freeze quantity for the instrument."""
        freeze_config = self.config.get("order_freeze_quantity", {})
        for symbol, freeze_qty in freeze_config.items():
            if symbol in tradingsymbol:
                return freeze_qty
        return 1800  # Default

    def _generate_order_id(self) -> str:
        """Generate unique internal order ID."""
        return f"ORD_{int(time.time() * 1000)}_{self.total_orders_today}"

    # =========================================================================
    # EXECUTION ANALYTICS
    # =========================================================================

    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution performance statistics."""
        completed_orders = [o for o in self.orders.values() if o.status == OrderStatus.COMPLETE]
        
        avg_exec_time = 0
        avg_slippage = 0
        if completed_orders:
            avg_exec_time = sum(o.execution_time_ms for o in completed_orders) / len(completed_orders)
            avg_slippage = sum(o.slippage for o in completed_orders) / len(completed_orders)
        
        return {
            "total_orders": self.total_orders_today,
            "successful": self.successful_orders,
            "rejected": self.rejected_orders,
            "fill_rate": (self.successful_orders / max(self.total_orders_today, 1)) * 100,
            "avg_execution_time_ms": round(avg_exec_time, 2),
            "avg_slippage": round(avg_slippage, 2),
            "total_slippage": round(self.total_slippage, 2),
            "total_trades": self.total_trades_today,
        }
