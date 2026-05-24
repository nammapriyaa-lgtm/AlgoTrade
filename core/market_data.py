"""
Real-Time Market Data Analytics Engine
========================================
LTP tracking, IV calculation, OI analysis, Greeks computation,
market breadth, VWAP, volume profile, and smart money flow analysis.
"""

import math
import time
import logging
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from collections import deque

import numpy as np

logger = logging.getLogger(__name__)



@dataclass
class IndexData:
    """Real-time index data."""
    symbol: str = ""
    ltp: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    change: float = 0.0
    change_percent: float = 0.0
    volume: int = 0
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class OptionData:
    """Option chain data for a single strike."""
    strike: float = 0.0
    ce_ltp: float = 0.0
    pe_ltp: float = 0.0
    ce_oi: int = 0
    pe_oi: int = 0
    ce_oi_change: int = 0
    pe_oi_change: int = 0
    ce_volume: int = 0
    pe_volume: int = 0
    ce_iv: float = 0.0
    pe_iv: float = 0.0
    ce_delta: float = 0.0
    pe_delta: float = 0.0
    ce_gamma: float = 0.0
    pe_gamma: float = 0.0
    ce_theta: float = 0.0
    pe_theta: float = 0.0
    ce_vega: float = 0.0
    pe_vega: float = 0.0
    pcr: float = 0.0  # Put-Call Ratio for this strike



@dataclass
class GreeksSnapshot:
    """Options Greeks for a position."""
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0
    iv: float = 0.0


@dataclass
class MarketBreadth:
    """Market breadth indicators."""
    advances: int = 0
    declines: int = 0
    unchanged: int = 0
    advance_decline_ratio: float = 0.0
    new_highs: int = 0
    new_lows: int = 0
    breadth_percent: float = 0.0
    trend_strength: str = "NEUTRAL"  # STRONG_BULL, BULL, NEUTRAL, BEAR, STRONG_BEAR


@dataclass
class VWAPData:
    """VWAP analytics."""
    vwap: float = 0.0
    upper_band_1: float = 0.0
    upper_band_2: float = 0.0
    lower_band_1: float = 0.0
    lower_band_2: float = 0.0
    deviation: float = 0.0
    price_vs_vwap: str = "AT"  # ABOVE, BELOW, AT



class MarketDataEngine:
    """
    Real-time market data analytics engine.
    
    Provides:
    - Live index prices (NIFTY, BANKNIFTY)
    - Implied Volatility calculations
    - Open Interest tracking with multi-timeframe change
    - Options Greeks (Delta, Gamma, Theta, Vega)
    - Market breadth and trend strength
    - VWAP and volume profile
    - Smart money flow indicators
    - Institutional activity detection
    """

    def __init__(self, api, config: Dict[str, Any]):
        self.api = api
        self.config = config
        
        # Index data
        self.indices: Dict[str, IndexData] = {
            "NIFTY": IndexData(symbol="NIFTY"),
            "BANKNIFTY": IndexData(symbol="BANKNIFTY"),
        }
        
        # Option chain cache
        self.option_chains: Dict[str, List[OptionData]] = {}
        
        # OI history for change tracking
        self._oi_history: Dict[str, deque] = {}  # symbol -> deque of (time, oi)
        
        # VWAP calculation
        self._vwap_data: Dict[str, Dict] = {}
        
        # Volume profile
        self._volume_profile: Dict[str, Dict[float, int]] = {}
        
        # Tick data buffer
        self._tick_buffer: Dict[str, deque] = {}
        
        # Market breadth
        self.breadth = MarketBreadth()
        
        # Threading
        self._running = False
        self._update_thread: Optional[threading.Thread] = None
        
        # Risk-free rate for Greeks
        self.risk_free_rate = 0.07  # 7% for India
        
        logger.info("MarketDataEngine initialized")



    # =========================================================================
    # INDEX DATA
    # =========================================================================

    def update_index_data(self, symbol: str, data: Dict) -> None:
        """Update index data from WebSocket tick."""
        if symbol not in self.indices:
            self.indices[symbol] = IndexData(symbol=symbol)
        
        idx = self.indices[symbol]
        idx.ltp = float(data.get("lp", idx.ltp))
        idx.open = float(data.get("o", idx.open))
        idx.high = float(data.get("h", idx.high))
        idx.low = float(data.get("l", idx.low))
        idx.close = float(data.get("c", idx.close))
        idx.volume = int(data.get("v", idx.volume))
        idx.timestamp = datetime.now()
        
        if idx.close > 0:
            idx.change = idx.ltp - idx.close
            idx.change_percent = (idx.change / idx.close) * 100

    def get_index_ltp(self, symbol: str) -> float:
        """Get last traded price of an index."""
        return self.indices.get(symbol, IndexData()).ltp

    def get_atm_strike(self, symbol: str, step: int = 50) -> float:
        """Calculate ATM strike price for given index."""
        ltp = self.get_index_ltp(symbol)
        if ltp <= 0:
            return 0
        
        if symbol == "BANKNIFTY":
            step = 100
        elif symbol == "NIFTY":
            step = 50
        elif symbol == "FINNIFTY":
            step = 50
        
        return round(ltp / step) * step

    # =========================================================================
    # IMPLIED VOLATILITY
    # =========================================================================

    def calculate_iv(
        self,
        option_price: float,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        option_type: str = "CE",
        r: float = None,
    ) -> float:
        """
        Calculate Implied Volatility using Newton-Raphson method.
        
        Args:
            option_price: Current option premium
            spot_price: Current spot/index price
            strike_price: Option strike price
            time_to_expiry: Time to expiry in years
            option_type: CE or PE
            r: Risk-free rate (default: configured rate)
        
        Returns:
            Implied Volatility as decimal
        """
        if r is None:
            r = self.risk_free_rate
        
        if option_price <= 0 or spot_price <= 0 or time_to_expiry <= 0:
            return 0.0
        
        # Newton-Raphson iteration
        sigma = 0.3  # Initial guess
        max_iterations = 100
        tolerance = 0.0001
        
        for _ in range(max_iterations):
            price = self._black_scholes_price(
                spot_price, strike_price, time_to_expiry, r, sigma, option_type
            )
            vega = self._bs_vega(spot_price, strike_price, time_to_expiry, r, sigma)
            
            if vega < 1e-10:
                break
            
            diff = price - option_price
            if abs(diff) < tolerance:
                return sigma
            
            sigma -= diff / vega
            sigma = max(0.01, min(sigma, 5.0))  # Bound sigma
        
        return sigma



    # =========================================================================
    # OPTIONS GREEKS
    # =========================================================================

    def calculate_greeks(
        self,
        spot_price: float,
        strike_price: float,
        time_to_expiry: float,
        volatility: float,
        option_type: str = "CE",
        r: float = None,
    ) -> GreeksSnapshot:
        """
        Calculate all Greeks for an option.
        
        Returns GreeksSnapshot with delta, gamma, theta, vega, rho.
        """
        if r is None:
            r = self.risk_free_rate
        
        if spot_price <= 0 or time_to_expiry <= 0 or volatility <= 0:
            return GreeksSnapshot()
        
        sqrt_t = math.sqrt(time_to_expiry)
        d1 = (math.log(spot_price / strike_price) + (r + 0.5 * volatility**2) * time_to_expiry) / (volatility * sqrt_t)
        d2 = d1 - volatility * sqrt_t
        
        nd1 = self._norm_cdf(d1)
        nd2 = self._norm_cdf(d2)
        npd1 = self._norm_pdf(d1)
        
        greeks = GreeksSnapshot(iv=volatility)
        
        if option_type == "CE":
            greeks.delta = nd1
            greeks.theta = (-(spot_price * npd1 * volatility) / (2 * sqrt_t)
                          - r * strike_price * math.exp(-r * time_to_expiry) * nd2) / 365
            greeks.rho = strike_price * time_to_expiry * math.exp(-r * time_to_expiry) * nd2 / 100
        else:  # PE
            greeks.delta = nd1 - 1
            nd2_neg = self._norm_cdf(-d2)
            greeks.theta = (-(spot_price * npd1 * volatility) / (2 * sqrt_t)
                          + r * strike_price * math.exp(-r * time_to_expiry) * nd2_neg) / 365
            greeks.rho = -strike_price * time_to_expiry * math.exp(-r * time_to_expiry) * nd2_neg / 100
        
        greeks.gamma = npd1 / (spot_price * volatility * sqrt_t)
        greeks.vega = spot_price * npd1 * sqrt_t / 100
        
        return greeks

    # =========================================================================
    # OPEN INTEREST ANALYSIS
    # =========================================================================

    def update_oi(self, symbol: str, oi: int, timestamp: Optional[datetime] = None) -> None:
        """Record OI data point for change tracking."""
        if timestamp is None:
            timestamp = datetime.now()
        
        if symbol not in self._oi_history:
            self._oi_history[symbol] = deque(maxlen=1000)
        
        self._oi_history[symbol].append((timestamp, oi))

    def get_oi_change(self, symbol: str, interval_minutes: int = 5) -> int:
        """Get OI change over specified interval."""
        if symbol not in self._oi_history or len(self._oi_history[symbol]) < 2:
            return 0
        
        history = self._oi_history[symbol]
        current_oi = history[-1][1]
        cutoff = datetime.now() - timedelta(minutes=interval_minutes)
        
        # Find OI at the beginning of the interval
        for ts, oi in history:
            if ts >= cutoff:
                return current_oi - oi
        
        return current_oi - history[0][1]

    def get_oi_change_multi_timeframe(self, symbol: str) -> Dict[str, int]:
        """Get OI change across multiple timeframes."""
        return {
            "1min": self.get_oi_change(symbol, 1),
            "3min": self.get_oi_change(symbol, 3),
            "5min": self.get_oi_change(symbol, 5),
            "15min": self.get_oi_change(symbol, 15),
        }

    def get_pcr(self, symbol: str = "NIFTY") -> float:
        """Calculate Put-Call Ratio from option chain."""
        chain = self.option_chains.get(symbol, [])
        if not chain:
            return 0.0
        
        total_pe_oi = sum(o.pe_oi for o in chain)
        total_ce_oi = sum(o.ce_oi for o in chain)
        
        if total_ce_oi == 0:
            return 0.0
        return round(total_pe_oi / total_ce_oi, 3)



    # =========================================================================
    # VWAP ANALYTICS
    # =========================================================================

    def update_vwap(self, symbol: str, price: float, volume: int) -> None:
        """Update VWAP calculation with new tick."""
        if symbol not in self._vwap_data:
            self._vwap_data[symbol] = {
                "cum_pv": 0.0,
                "cum_vol": 0,
                "cum_pv2": 0.0,
                "ticks": deque(maxlen=10000),
            }
        
        data = self._vwap_data[symbol]
        data["cum_pv"] += price * volume
        data["cum_vol"] += volume
        data["cum_pv2"] += (price ** 2) * volume
        data["ticks"].append((price, volume))

    def get_vwap(self, symbol: str) -> VWAPData:
        """Get VWAP and bands for a symbol."""
        data = self._vwap_data.get(symbol)
        if not data or data["cum_vol"] == 0:
            return VWAPData()
        
        vwap = data["cum_pv"] / data["cum_vol"]
        
        # Standard deviation bands
        variance = (data["cum_pv2"] / data["cum_vol"]) - (vwap ** 2)
        std_dev = math.sqrt(max(variance, 0))
        
        current_price = self.get_index_ltp(symbol)
        
        result = VWAPData(
            vwap=round(vwap, 2),
            upper_band_1=round(vwap + std_dev, 2),
            upper_band_2=round(vwap + 2 * std_dev, 2),
            lower_band_1=round(vwap - std_dev, 2),
            lower_band_2=round(vwap - 2 * std_dev, 2),
            deviation=round(std_dev, 2),
        )
        
        if current_price > vwap + 0.001:
            result.price_vs_vwap = "ABOVE"
        elif current_price < vwap - 0.001:
            result.price_vs_vwap = "BELOW"
        else:
            result.price_vs_vwap = "AT"
        
        return result

    # =========================================================================
    # VOLUME PROFILE
    # =========================================================================

    def update_volume_profile(self, symbol: str, price: float, volume: int, step: float = 10.0) -> None:
        """Update volume profile with tick data."""
        if symbol not in self._volume_profile:
            self._volume_profile[symbol] = {}
        
        # Round to nearest price level
        level = round(price / step) * step
        self._volume_profile[symbol][level] = self._volume_profile[symbol].get(level, 0) + volume

    def get_volume_profile(self, symbol: str, top_n: int = 10) -> List[Dict[str, Any]]:
        """Get top volume levels (Point of Control, Value Area)."""
        profile = self._volume_profile.get(symbol, {})
        if not profile:
            return []
        
        sorted_levels = sorted(profile.items(), key=lambda x: x[1], reverse=True)
        total_volume = sum(v for _, v in sorted_levels)
        
        result = []
        for price_level, vol in sorted_levels[:top_n]:
            result.append({
                "price": price_level,
                "volume": vol,
                "percent": round(vol / total_volume * 100, 2) if total_volume > 0 else 0,
            })
        
        return result

    def get_poc(self, symbol: str) -> float:
        """Get Point of Control (highest volume price level)."""
        profile = self._volume_profile.get(symbol, {})
        if not profile:
            return 0.0
        return max(profile, key=profile.get)



    # =========================================================================
    # MARKET BREADTH & TREND STRENGTH
    # =========================================================================

    def update_market_breadth(self, advances: int, declines: int, unchanged: int = 0) -> None:
        """Update market breadth data."""
        total = advances + declines + unchanged
        self.breadth.advances = advances
        self.breadth.declines = declines
        self.breadth.unchanged = unchanged
        
        if declines > 0:
            self.breadth.advance_decline_ratio = round(advances / declines, 2)
        else:
            self.breadth.advance_decline_ratio = float(advances) if advances > 0 else 1.0
        
        if total > 0:
            self.breadth.breadth_percent = round(advances / total * 100, 1)
        
        # Trend strength classification
        ratio = self.breadth.advance_decline_ratio
        if ratio >= 3.0:
            self.breadth.trend_strength = "STRONG_BULL"
        elif ratio >= 1.5:
            self.breadth.trend_strength = "BULL"
        elif ratio >= 0.67:
            self.breadth.trend_strength = "NEUTRAL"
        elif ratio >= 0.33:
            self.breadth.trend_strength = "BEAR"
        else:
            self.breadth.trend_strength = "STRONG_BEAR"

    def get_trend_strength_score(self) -> float:
        """Get normalized trend strength score (-100 to +100)."""
        ratio = self.breadth.advance_decline_ratio
        # Normalize: ratio=1 -> 0, ratio=3+ -> 100, ratio=0.33- -> -100
        if ratio >= 1:
            score = min(100, (ratio - 1) * 50)
        else:
            score = max(-100, (ratio - 1) * 100)
        return round(score, 1)

    # =========================================================================
    # SMART MONEY FLOW & INSTITUTIONAL ACTIVITY
    # =========================================================================

    def detect_institutional_activity(self, symbol: str) -> Dict[str, Any]:
        """
        Detect institutional buying/selling based on OI and volume patterns.
        
        Heuristics:
        - Large OI buildup with price rise = Institutional buying
        - Large OI buildup with price fall = Institutional selling
        - OI unwinding with price rise = Short covering
        - OI unwinding with price fall = Long unwinding
        """
        oi_change_5m = self.get_oi_change(symbol + "_CE", 5)
        oi_change_15m = self.get_oi_change(symbol + "_CE", 15)
        
        idx = self.indices.get(symbol, IndexData())
        price_change = idx.change
        
        activity = {
            "signal": "NEUTRAL",
            "strength": 0,
            "description": "",
            "oi_change_5m": oi_change_5m,
            "oi_change_15m": oi_change_15m,
            "price_change": price_change,
        }
        
        if oi_change_15m > 0 and price_change > 0:
            activity["signal"] = "INSTITUTIONAL_BUYING"
            activity["strength"] = min(100, int(abs(oi_change_15m) / 1000))
            activity["description"] = "Long buildup - Institutions adding longs"
        elif oi_change_15m > 0 and price_change < 0:
            activity["signal"] = "INSTITUTIONAL_SELLING"
            activity["strength"] = min(100, int(abs(oi_change_15m) / 1000))
            activity["description"] = "Short buildup - Institutions adding shorts"
        elif oi_change_15m < 0 and price_change > 0:
            activity["signal"] = "SHORT_COVERING"
            activity["strength"] = min(100, int(abs(oi_change_15m) / 1000))
            activity["description"] = "Short covering - Shorts exiting"
        elif oi_change_15m < 0 and price_change < 0:
            activity["signal"] = "LONG_UNWINDING"
            activity["strength"] = min(100, int(abs(oi_change_15m) / 1000))
            activity["description"] = "Long unwinding - Longs exiting"
        
        return activity

    def get_smart_money_flow(self, symbol: str) -> Dict[str, Any]:
        """
        Analyze smart money flow using volume and price action.
        
        Smart money indicators:
        - High volume on small candles (accumulation/distribution)
        - Low volume on large candles (fake moves)
        - OI vs price divergence
        """
        ticks = self._tick_buffer.get(symbol, deque())
        if len(ticks) < 10:
            return {"flow": "NEUTRAL", "score": 0, "description": "Insufficient data"}
        
        # Analyze recent ticks
        recent_ticks = list(ticks)[-50:]
        buy_volume = sum(t.get("bv", 0) for t in recent_ticks if isinstance(t, dict))
        sell_volume = sum(t.get("sv", 0) for t in recent_ticks if isinstance(t, dict))
        total_volume = buy_volume + sell_volume
        
        if total_volume == 0:
            return {"flow": "NEUTRAL", "score": 0, "description": "No volume data"}
        
        buy_ratio = buy_volume / total_volume
        
        if buy_ratio > 0.65:
            flow = "STRONG_INFLOW"
            score = int((buy_ratio - 0.5) * 200)
        elif buy_ratio > 0.55:
            flow = "INFLOW"
            score = int((buy_ratio - 0.5) * 200)
        elif buy_ratio < 0.35:
            flow = "STRONG_OUTFLOW"
            score = -int((0.5 - buy_ratio) * 200)
        elif buy_ratio < 0.45:
            flow = "OUTFLOW"
            score = -int((0.5 - buy_ratio) * 200)
        else:
            flow = "NEUTRAL"
            score = 0
        
        return {
            "flow": flow,
            "score": score,
            "buy_volume": buy_volume,
            "sell_volume": sell_volume,
            "buy_ratio": round(buy_ratio, 3),
            "description": f"Buy ratio: {buy_ratio:.1%}",
        }



    # =========================================================================
    # BLACK-SCHOLES HELPERS
    # =========================================================================

    def _black_scholes_price(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """Calculate Black-Scholes option price."""
        if T <= 0 or sigma <= 0:
            return max(0, S - K) if option_type == "CE" else max(0, K - S)
        
        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        
        if option_type == "CE":
            return S * self._norm_cdf(d1) - K * math.exp(-r * T) * self._norm_cdf(d2)
        else:
            return K * math.exp(-r * T) * self._norm_cdf(-d2) - S * self._norm_cdf(-d1)

    def _bs_vega(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Calculate Black-Scholes Vega."""
        if T <= 0 or sigma <= 0:
            return 0.0
        sqrt_t = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_t)
        return S * self._norm_pdf(d1) * sqrt_t

    @staticmethod
    def _norm_cdf(x: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    @staticmethod
    def _norm_pdf(x: float) -> float:
        """Standard normal probability density function."""
        return math.exp(-0.5 * x**2) / math.sqrt(2 * math.pi)

    # =========================================================================
    # OPTION CHAIN MANAGEMENT
    # =========================================================================

    def update_option_chain(self, symbol: str, chain_data: List[Dict]) -> None:
        """Update option chain from API response."""
        options = []
        for item in chain_data:
            opt = OptionData(
                strike=float(item.get("strprc", 0)),
                ce_ltp=float(item.get("ce_lp", 0)),
                pe_ltp=float(item.get("pe_lp", 0)),
                ce_oi=int(item.get("ce_oi", 0)),
                pe_oi=int(item.get("pe_oi", 0)),
                ce_volume=int(item.get("ce_vol", 0)),
                pe_volume=int(item.get("pe_vol", 0)),
            )
            
            # Calculate PCR for this strike
            if opt.ce_oi > 0:
                opt.pcr = round(opt.pe_oi / opt.ce_oi, 3)
            
            options.append(opt)
            
            # Track OI history
            self.update_oi(f"{symbol}_{opt.strike}_CE", opt.ce_oi)
            self.update_oi(f"{symbol}_{opt.strike}_PE", opt.pe_oi)
        
        self.option_chains[symbol] = sorted(options, key=lambda x: x.strike)

    def get_max_oi_strike(self, symbol: str, option_type: str = "CE") -> Dict[str, Any]:
        """Get strike with maximum OI (support/resistance level)."""
        chain = self.option_chains.get(symbol, [])
        if not chain:
            return {"strike": 0, "oi": 0}
        
        if option_type == "CE":
            max_opt = max(chain, key=lambda x: x.ce_oi)
            return {"strike": max_opt.strike, "oi": max_opt.ce_oi}
        else:
            max_opt = max(chain, key=lambda x: x.pe_oi)
            return {"strike": max_opt.strike, "oi": max_opt.pe_oi}

    def get_market_snapshot(self) -> Dict[str, Any]:
        """Get comprehensive market data snapshot."""
        nifty = self.indices.get("NIFTY", IndexData())
        banknifty = self.indices.get("BANKNIFTY", IndexData())
        
        return {
            "timestamp": datetime.now().isoformat(),
            "nifty": {
                "ltp": nifty.ltp,
                "change": nifty.change,
                "change_pct": nifty.change_percent,
                "high": nifty.high,
                "low": nifty.low,
                "atm_strike": self.get_atm_strike("NIFTY"),
            },
            "banknifty": {
                "ltp": banknifty.ltp,
                "change": banknifty.change,
                "change_pct": banknifty.change_percent,
                "high": banknifty.high,
                "low": banknifty.low,
                "atm_strike": self.get_atm_strike("BANKNIFTY"),
            },
            "breadth": {
                "advances": self.breadth.advances,
                "declines": self.breadth.declines,
                "ratio": self.breadth.advance_decline_ratio,
                "trend": self.breadth.trend_strength,
                "score": self.get_trend_strength_score(),
            },
            "pcr_nifty": self.get_pcr("NIFTY"),
            "pcr_banknifty": self.get_pcr("BANKNIFTY"),
            "vwap_nifty": self.get_vwap("NIFTY").__dict__,
            "vwap_banknifty": self.get_vwap("BANKNIFTY").__dict__,
        }

    # =========================================================================
    # TICK PROCESSING
    # =========================================================================

    def process_tick(self, data: Dict) -> None:
        """Process incoming WebSocket tick and update all analytics."""
        symbol = data.get("tk", "")
        exchange = data.get("e", "")
        
        # Update LTP
        if "lp" in data:
            ltp = float(data["lp"])
            volume = int(data.get("v", 0))
            
            # Update VWAP
            if volume > 0:
                self.update_vwap(symbol, ltp, volume)
                self.update_volume_profile(symbol, ltp, volume)
            
            # Buffer tick
            if symbol not in self._tick_buffer:
                self._tick_buffer[symbol] = deque(maxlen=5000)
            self._tick_buffer[symbol].append(data)
