"""
Flattrade API Integration Module
================================
Handles authentication, REST API calls, WebSocket connections,
order execution, and market data retrieval.

Based on Flattrade Pi Connect API (NorenRestApi architecture)
Endpoints: https://piconnect.flattrade.in/PiConnectTP/
"""

import hashlib
import json
import time
import threading
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable, List
from enum import Enum

import requests
import websocket

logger = logging.getLogger(__name__)


class OrderType(Enum):
    MARKET = "MKT"
    LIMIT = "LMT"
    STOP_LOSS_LIMIT = "SL-LMT"
    STOP_LOSS_MARKET = "SL-MKT"


class ProductType(Enum):
    INTRADAY = "I"
    DELIVERY = "C"
    MARGIN = "M"
    BO = "B"
    CO = "H"


class TransactionType(Enum):
    BUY = "B"
    SELL = "S"


class Exchange(Enum):
    NSE = "NSE"
    NFO = "NFO"
    BSE = "BSE"
    BFO = "BFO"
    MCX = "MCX"


class FlattradeAPI:
    """
    Core Flattrade API client with full REST and WebSocket support.
    Provides institutional-grade connectivity with automatic reconnection,
    rate limiting, and comprehensive error handling.
    """

    # API Endpoints
    ENDPOINTS = {
        "login": "/QuickAuth",
        "logout": "/Logout",
        "place_order": "/PlaceOrder",
        "modify_order": "/ModifyOrder",
        "cancel_order": "/CancelOrder",
        "order_book": "/OrderBook",
        "trade_book": "/TradeBook",
        "positions": "/PositionBook",
        "holdings": "/Holdings",
        "limits": "/Limits",
        "get_quotes": "/GetQuotes",
        "get_option_chain": "/GetOptionChain",
        "search_scrip": "/SearchScrip",
        "get_security_info": "/GetSecurityInfo",
        "get_index_list": "/GetIndexList",
        "time_price_series": "/TPSeries",
        "span_calculator": "/SpanCalculator",
        "order_margin": "/GetOrderMargin",
        "basket_margin": "/GetBasketMargin",
        "order_history": "/SingleOrdHist",
    }

    def __init__(self, config: Dict[str, Any]):
        """Initialize API client with configuration."""
        self.config = config
        self.base_url = config.get("base_url", "https://piconnect.flattrade.in/PiConnectTP")
        self.ws_url = config.get("websocket_url", "wss://piconnect.flattrade.in/PiConnectWSTp/")
        self.auth_url = config.get("auth_url", "https://authapi.flattrade.in/trade/apitoken")
        
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.user_id = config.get("user_id", "")
        self.totp_key = config.get("totp_key", "")
        
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        
        # WebSocket
        self._ws: Optional[websocket.WebSocketApp] = None
        self._ws_thread: Optional[threading.Thread] = None
        self._ws_connected = False
        self._ws_callbacks: Dict[str, List[Callable]] = {
            "order_update": [],
            "quote_update": [],
            "depth_update": [],
            "error": [],
            "connection": [],
        }
        self._subscribed_tokens: set = set()
        
        # Rate limiting
        self._last_request_time = 0
        self._min_request_interval = 1.0 / config.get("rate_limit_per_second", 10)
        
        # Connection state
        self._is_authenticated = False
        self._reconnect_attempts = 0
        self._max_reconnect = config.get("reconnect_attempts", 5)
        
        logger.info("FlattradeAPI initialized for user: %s", self.user_id)

    # =========================================================================
    # AUTHENTICATION
    # =========================================================================

    def authenticate(self, request_token: Optional[str] = None) -> Dict[str, Any]:
        """
        Authenticate with Flattrade API.
        
        Flow:
        1. User logs in via browser to get request_token
        2. Generate API token using request_token + api_secret hash
        3. Store session token for subsequent requests
        
        Args:
            request_token: Token received from OAuth login redirect
            
        Returns:
            Authentication response dict
        """
        try:
            if not request_token:
                logger.error("Request token required for authentication")
                return {"status": "error", "message": "Request token required"}
            
            # Generate token hash: SHA-256(api_key + request_token + api_secret)
            token_hash = hashlib.sha256(
                (self.api_key + request_token + self.api_secret).encode()
            ).hexdigest()
            
            payload = {
                "api_key": self.api_key,
                "request_token": request_token,
                "api_secret": token_hash,
            }
            
            logger.info("Authenticating with token hash for user: %s", self.user_id)
            
            # Flattrade expects form-urlencoded POST
            response = self.session.post(
                self.auth_url,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.config.get("timeout", 10),
            )
            
            logger.info("Auth response status: %d", response.status_code)
            logger.info("Auth response body: %s", response.text[:200])
            
            result = response.json()
            
            if result.get("stat") == "Ok":
                self.token = result.get("token")
                self._is_authenticated = True
                logger.info("Authentication successful for user: %s", self.user_id)
                return {"status": "success", "data": result}
            else:
                logger.error("Authentication failed: %s", result.get("emsg", "Unknown error"))
                return {"status": "error", "message": result.get("emsg", "Authentication failed")}
                
        except Exception as e:
            logger.exception("Authentication error: %s", str(e))
            return {"status": "error", "message": str(e)}

    def is_authenticated(self) -> bool:
        """Check if currently authenticated."""
        return self._is_authenticated and self.token is not None

    # =========================================================================
    # ORDER MANAGEMENT
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
        disclosed_qty: int = 0,
        retention: str = "DAY",
        remarks: str = "",
        amo: str = "NO",
    ) -> Dict[str, Any]:
        """
        Place an order on Flattrade.
        
        Args:
            exchange: Exchange segment (NSE, NFO, BSE, BFO, MCX)
            tradingsymbol: Trading symbol (e.g., NIFTY23DEC21500CE)
            transaction_type: B (Buy) or S (Sell)
            quantity: Order quantity
            order_type: MKT, LMT, SL-LMT, SL-MKT
            product_type: I (Intraday), C (Delivery), M (Margin)
            price: Limit price (0 for market orders)
            trigger_price: Trigger price for SL orders
            disclosed_qty: Disclosed quantity
            retention: DAY, IOC, EOS
            remarks: Order remarks/tag
            amo: YES/NO for After Market Order
            
        Returns:
            Order response with order number
        """
        payload = {
            "uid": self.user_id,
            "actid": self.user_id,
            "exch": exchange,
            "tsym": tradingsymbol,
            "qty": str(quantity),
            "prc": str(price),
            "trgprc": str(trigger_price),
            "dscqty": str(disclosed_qty),
            "prd": product_type,
            "trantype": transaction_type,
            "prctyp": order_type,
            "ret": retention,
            "remarks": remarks,
            "amo": amo,
            "ordersource": "API",
        }
        
        return self._post("place_order", payload)

    def modify_order(
        self,
        order_no: str,
        exchange: str,
        tradingsymbol: str,
        quantity: int,
        order_type: str,
        price: float = 0.0,
        trigger_price: float = 0.0,
    ) -> Dict[str, Any]:
        """Modify an existing order."""
        payload = {
            "uid": self.user_id,
            "actid": self.user_id,
            "norenordno": order_no,
            "exch": exchange,
            "tsym": tradingsymbol,
            "qty": str(quantity),
            "prc": str(price),
            "trgprc": str(trigger_price),
            "prctyp": order_type,
        }
        return self._post("modify_order", payload)

    def cancel_order(self, order_no: str) -> Dict[str, Any]:
        """Cancel an existing order."""
        payload = {
            "uid": self.user_id,
            "actid": self.user_id,
            "norenordno": order_no,
        }
        return self._post("cancel_order", payload)

    def get_order_book(self) -> Dict[str, Any]:
        """Get all orders for the day."""
        payload = {"uid": self.user_id, "actid": self.user_id}
        return self._post("order_book", payload)

    def get_trade_book(self) -> Dict[str, Any]:
        """Get all executed trades for the day."""
        payload = {"uid": self.user_id, "actid": self.user_id}
        return self._post("trade_book", payload)

    def get_order_history(self, order_no: str) -> Dict[str, Any]:
        """Get history of a specific order."""
        payload = {"uid": self.user_id, "norenordno": order_no}
        return self._post("order_history", payload)

    # =========================================================================
    # POSITION & PORTFOLIO
    # =========================================================================

    def get_positions(self) -> Dict[str, Any]:
        """Get current positions."""
        payload = {"uid": self.user_id, "actid": self.user_id}
        return self._post("positions", payload)

    def get_holdings(self) -> Dict[str, Any]:
        """Get current holdings."""
        payload = {"uid": self.user_id, "actid": self.user_id}
        return self._post("holdings", payload)

    def get_limits(self) -> Dict[str, Any]:
        """Get account margins and limits."""
        payload = {"uid": self.user_id, "actid": self.user_id}
        return self._post("limits", payload)

    # =========================================================================
    # MARKET DATA
    # =========================================================================

    def get_quotes(self, exchange: str, token: str) -> Dict[str, Any]:
        """Get real-time quotes for a scrip."""
        payload = {"uid": self.user_id, "exch": exchange, "token": token}
        return self._post("get_quotes", payload)

    def get_option_chain(
        self, exchange: str, tradingsymbol: str, strike_price: float, count: int = 10
    ) -> Dict[str, Any]:
        """Get option chain data."""
        payload = {
            "uid": self.user_id,
            "exch": exchange,
            "tsym": tradingsymbol,
            "strprc": str(strike_price),
            "cnt": str(count),
        }
        return self._post("get_option_chain", payload)

    def search_scrip(self, exchange: str, search_text: str) -> Dict[str, Any]:
        """Search for a scrip/instrument."""
        payload = {"uid": self.user_id, "exch": exchange, "stext": search_text}
        return self._post("search_scrip", payload)

    def get_security_info(self, exchange: str, token: str) -> Dict[str, Any]:
        """Get detailed security information."""
        payload = {"uid": self.user_id, "exch": exchange, "token": token}
        return self._post("get_security_info", payload)

    def get_time_price_series(
        self,
        exchange: str,
        token: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        interval: str = "1",
    ) -> Dict[str, Any]:
        """
        Get historical OHLCV candle data.
        
        Args:
            exchange: Exchange segment
            token: Instrument token
            start_time: Start epoch time
            end_time: End epoch time (default: current time)
            interval: Candle interval in minutes (1, 3, 5, 15, 60, 240)
        """
        if end_time is None:
            end_time = str(int(time.time()))
        if start_time is None:
            start_time = str(int(time.time()) - 86400)  # 1 day back
            
        payload = {
            "uid": self.user_id,
            "exch": exchange,
            "token": token,
            "st": start_time,
            "et": end_time,
            "intrv": interval,
        }
        return self._post("time_price_series", payload)

    def get_index_list(self, exchange: str) -> Dict[str, Any]:
        """Get list of indices."""
        payload = {"uid": self.user_id, "exch": exchange}
        return self._post("get_index_list", payload)

    # =========================================================================
    # MARGIN CALCULATORS
    # =========================================================================

    def get_order_margin(
        self,
        exchange: str,
        tradingsymbol: str,
        quantity: int,
        price: float,
        product_type: str,
        transaction_type: str,
    ) -> Dict[str, Any]:
        """Calculate margin required for an order."""
        payload = {
            "uid": self.user_id,
            "actid": self.user_id,
            "exch": exchange,
            "tsym": tradingsymbol,
            "qty": str(quantity),
            "prc": str(price),
            "prd": product_type,
            "trantype": transaction_type,
        }
        return self._post("order_margin", payload)

    def get_span_margin(self, positions: List[Dict]) -> Dict[str, Any]:
        """Calculate SPAN margin for multiple positions."""
        payload = {"uid": self.user_id, "actid": self.user_id, "pos": positions}
        return self._post("span_calculator", payload)

    # =========================================================================
    # WEBSOCKET - REAL-TIME DATA
    # =========================================================================

    def connect_websocket(self) -> bool:
        """Establish WebSocket connection for real-time data."""
        if not self.is_authenticated():
            logger.error("Must authenticate before connecting WebSocket")
            return False

        try:
            self._ws = websocket.WebSocketApp(
                self.ws_url,
                on_open=self._on_ws_open,
                on_message=self._on_ws_message,
                on_error=self._on_ws_error,
                on_close=self._on_ws_close,
            )
            
            self._ws_thread = threading.Thread(
                target=self._ws.run_forever,
                kwargs={"ping_interval": 30, "ping_timeout": 10},
                daemon=True,
            )
            self._ws_thread.start()
            
            # Wait for connection
            timeout = 10
            start = time.time()
            while not self._ws_connected and time.time() - start < timeout:
                time.sleep(0.1)
            
            return self._ws_connected
            
        except Exception as e:
            logger.exception("WebSocket connection error: %s", str(e))
            return False

    def subscribe(self, instruments: List[str], feed_type: str = "t") -> None:
        """
        Subscribe to real-time market data.
        
        Args:
            instruments: List of "exchange|token" strings
            feed_type: 't' for touchline, 'd' for depth, 'o' for order updates
        """
        if not self._ws_connected:
            logger.warning("WebSocket not connected. Cannot subscribe.")
            return
            
        subscribe_data = {
            "t": feed_type,
            "k": "#".join(instruments),
        }
        self._ws.send(json.dumps(subscribe_data))
        self._subscribed_tokens.update(instruments)
        logger.info("Subscribed to %d instruments", len(instruments))

    def unsubscribe(self, instruments: List[str]) -> None:
        """Unsubscribe from real-time data."""
        if not self._ws_connected:
            return
            
        unsubscribe_data = {
            "t": "u",
            "k": "#".join(instruments),
        }
        self._ws.send(json.dumps(unsubscribe_data))
        self._subscribed_tokens -= set(instruments)

    def subscribe_orders(self) -> None:
        """Subscribe to real-time order updates."""
        if not self._ws_connected:
            return
        order_sub = {"t": "o", "actid": self.user_id}
        self._ws.send(json.dumps(order_sub))

    def on(self, event: str, callback: Callable) -> None:
        """Register callback for WebSocket events."""
        if event in self._ws_callbacks:
            self._ws_callbacks[event].append(callback)

    def disconnect_websocket(self) -> None:
        """Disconnect WebSocket."""
        if self._ws:
            self._ws.close()
            self._ws_connected = False
            logger.info("WebSocket disconnected")

    # =========================================================================
    # WEBSOCKET HANDLERS
    # =========================================================================

    def _on_ws_open(self, ws):
        """Handle WebSocket connection opened."""
        # Send authentication
        auth_msg = {
            "t": "c",
            "uid": self.user_id,
            "actid": self.user_id,
            "susertoken": self.token,
            "source": "API",
        }
        ws.send(json.dumps(auth_msg))
        logger.info("WebSocket connection opened, authenticating...")

    def _on_ws_message(self, ws, message):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)
            msg_type = data.get("t")
            
            if msg_type == "ck":
                # Connection acknowledgment
                self._ws_connected = True
                self._reconnect_attempts = 0
                logger.info("WebSocket authenticated successfully")
                for cb in self._ws_callbacks["connection"]:
                    cb({"status": "connected"})
                    
            elif msg_type in ("tf", "tk"):
                # Touchline/Quote update
                for cb in self._ws_callbacks["quote_update"]:
                    cb(data)
                    
            elif msg_type in ("df", "dk"):
                # Market depth update
                for cb in self._ws_callbacks["depth_update"]:
                    cb(data)
                    
            elif msg_type == "om":
                # Order update
                for cb in self._ws_callbacks["order_update"]:
                    cb(data)
                    
        except Exception as e:
            logger.error("WebSocket message parse error: %s", str(e))

    def _on_ws_error(self, ws, error):
        """Handle WebSocket errors."""
        logger.error("WebSocket error: %s", str(error))
        for cb in self._ws_callbacks["error"]:
            cb({"error": str(error)})

    def _on_ws_close(self, ws, close_status_code, close_msg):
        """Handle WebSocket connection closed."""
        self._ws_connected = False
        logger.warning("WebSocket closed: %s - %s", close_status_code, close_msg)
        
        # Auto-reconnect
        if self._reconnect_attempts < self._max_reconnect:
            self._reconnect_attempts += 1
            delay = self.config.get("reconnect_delay", 5) * self._reconnect_attempts
            logger.info("Reconnecting in %d seconds (attempt %d/%d)...",
                       delay, self._reconnect_attempts, self._max_reconnect)
            threading.Timer(delay, self.connect_websocket).start()

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    def _post(self, endpoint_key: str, payload: Dict) -> Dict[str, Any]:
        """Execute authenticated POST request with rate limiting."""
        if not self.is_authenticated() and endpoint_key != "login":
            return {"status": "error", "message": "Not authenticated"}
        
        # Rate limiting
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_request_interval:
            time.sleep(self._min_request_interval - elapsed)
        
        endpoint = self.ENDPOINTS.get(endpoint_key, "")
        url = f"{self.base_url}{endpoint}"
        
        # Add authentication token
        jdata = json.dumps(payload)
        data = f"jKey={self.token}&jData={jdata}"
        
        try:
            response = self.session.post(
                url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=self.config.get("timeout", 10),
            )
            self._last_request_time = time.time()
            
            result = response.json()
            
            if result.get("stat") == "Ok":
                return {"status": "success", "data": result}
            else:
                error_msg = result.get("emsg", "Unknown error")
                logger.warning("API error on %s: %s", endpoint_key, error_msg)
                return {"status": "error", "message": error_msg, "data": result}
                
        except requests.Timeout:
            logger.error("Request timeout on %s", endpoint_key)
            return {"status": "error", "message": "Request timeout"}
        except requests.ConnectionError:
            logger.error("Connection error on %s", endpoint_key)
            return {"status": "error", "message": "Connection error"}
        except Exception as e:
            logger.exception("Request error on %s: %s", endpoint_key, str(e))
            return {"status": "error", "message": str(e)}

    def __del__(self):
        """Cleanup on destruction."""
        self.disconnect_websocket()
