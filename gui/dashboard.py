"""
Main Trading Dashboard - PyQt5 GUI
=====================================
Professional-grade trading dashboard with real-time monitoring,
execution buttons, and comprehensive analytics panels.
"""

import sys
import logging
from datetime import datetime
from typing import Dict, Any, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTabWidget, QFrame,
    QGroupBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QStatusBar, QMessageBox, QSplitter, QProgressBar,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QTextEdit, QScrollArea
)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt5.QtGui import QFont, QColor, QPalette, QIcon

logger = logging.getLogger(__name__)



class StyleSheet:
    """Professional dark theme stylesheet."""
    
    DARK_THEME = """
    QMainWindow {
        background-color: #1a1a2e;
    }
    QWidget {
        background-color: #1a1a2e;
        color: #e0e0e0;
        font-family: 'Segoe UI', 'Consolas';
        font-size: 11px;
    }
    QGroupBox {
        border: 1px solid #333355;
        border-radius: 5px;
        margin-top: 10px;
        padding-top: 10px;
        font-weight: bold;
        color: #00d4ff;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 5px;
    }
    QPushButton {
        background-color: #2d2d5e;
        border: 1px solid #4444aa;
        border-radius: 4px;
        padding: 8px 16px;
        color: #ffffff;
        font-weight: bold;
        min-height: 30px;
    }
    QPushButton:hover {
        background-color: #3d3d7e;
        border-color: #6666cc;
    }
    QPushButton:pressed {
        background-color: #1d1d4e;
    }
    QPushButton#buyButton {
        background-color: #0d6e3f;
        border-color: #10b981;
    }
    QPushButton#buyButton:hover {
        background-color: #10b981;
    }
    QPushButton#sellButton {
        background-color: #7f1d1d;
        border-color: #ef4444;
    }
    QPushButton#sellButton:hover {
        background-color: #ef4444;
    }
    QPushButton#emergencyButton {
        background-color: #dc2626;
        border-color: #ff0000;
        font-size: 14px;
    }
    QTableWidget {
        background-color: #16213e;
        gridline-color: #333355;
        border: 1px solid #333355;
        border-radius: 3px;
    }
    QTableWidget::item {
        padding: 4px;
    }
    QHeaderView::section {
        background-color: #1a1a3e;
        color: #00d4ff;
        padding: 5px;
        border: 1px solid #333355;
        font-weight: bold;
    }
    QLabel#priceUp {
        color: #10b981;
        font-weight: bold;
    }
    QLabel#priceDown {
        color: #ef4444;
        font-weight: bold;
    }
    QLabel#headerLabel {
        color: #00d4ff;
        font-size: 13px;
        font-weight: bold;
    }
    QLabel#bigPrice {
        font-size: 24px;
        font-weight: bold;
    }
    QFrame#separator {
        background-color: #333355;
        max-height: 1px;
    }
    QProgressBar {
        border: 1px solid #333355;
        border-radius: 3px;
        text-align: center;
        background-color: #16213e;
    }
    QProgressBar::chunk {
        background-color: #10b981;
        border-radius: 2px;
    }
    QComboBox, QSpinBox, QDoubleSpinBox {
        background-color: #16213e;
        border: 1px solid #333355;
        border-radius: 3px;
        padding: 4px;
        color: #e0e0e0;
    }
    QTabWidget::pane {
        border: 1px solid #333355;
        background-color: #1a1a2e;
    }
    QTabBar::tab {
        background-color: #16213e;
        color: #888;
        padding: 8px 20px;
        border: 1px solid #333355;
        border-bottom: none;
        border-top-left-radius: 4px;
        border-top-right-radius: 4px;
    }
    QTabBar::tab:selected {
        background-color: #1a1a2e;
        color: #00d4ff;
        border-bottom: 2px solid #00d4ff;
    }
    QTextEdit {
        background-color: #16213e;
        border: 1px solid #333355;
        border-radius: 3px;
        color: #e0e0e0;
    }
    """



class TradingDashboard(QMainWindow):
    """
    Main Trading Dashboard Window.
    
    Panels:
    - Market Overview (Index LTP, Change, Range)
    - Option Chain with OI & Greeks
    - Trading Buttons (Buy/Sell CE/PE with confirmation)
    - P&L Monitor
    - Risk Dashboard
    - Signal Monitor
    - Order Book
    - Performance Analytics
    """
    
    # Signals
    signal_received = pyqtSignal(dict)
    order_update = pyqtSignal(dict)
    
    def __init__(self, trading_system=None):
        super().__init__()
        self.trading_system = trading_system
        self.setWindowTitle("AlgoTrade Pro - Institutional Trading Platform")
        self.setMinimumSize(1600, 900)
        self.setStyleSheet(StyleSheet.DARK_THEME)
        
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(5, 5, 5, 5)
        
        # Build UI
        self._build_header(main_layout)
        self._build_main_content(main_layout)
        self._build_status_bar()
        
        # Update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self._refresh_data)
        self.update_timer.start(500)  # 500ms refresh
        
        logger.info("Trading Dashboard initialized")



    # =========================================================================
    # HEADER - Market Overview
    # =========================================================================

    def _build_header(self, parent_layout):
        """Build top header with index prices and key metrics."""
        header = QFrame()
        header.setMaximumHeight(120)
        header_layout = QHBoxLayout(header)
        
        # NIFTY Panel
        nifty_group = self._create_index_panel("NIFTY 50")
        self.nifty_ltp = nifty_group.findChild(QLabel, "ltp_label")
        self.nifty_change = nifty_group.findChild(QLabel, "change_label")
        header_layout.addWidget(nifty_group)
        
        # BANKNIFTY Panel
        banknifty_group = self._create_index_panel("BANK NIFTY")
        self.banknifty_ltp = banknifty_group.findChild(QLabel, "ltp_label")
        self.banknifty_change = banknifty_group.findChild(QLabel, "change_label")
        header_layout.addWidget(banknifty_group)
        
        # Key Metrics Panel
        metrics_group = QGroupBox("Key Metrics")
        metrics_layout = QGridLayout(metrics_group)
        
        self.iv_label = QLabel("IV: --")
        self.pcr_label = QLabel("PCR: --")
        self.trend_label = QLabel("Trend: --")
        self.vwap_label = QLabel("VWAP: --")
        
        metrics_layout.addWidget(self.iv_label, 0, 0)
        metrics_layout.addWidget(self.pcr_label, 0, 1)
        metrics_layout.addWidget(self.trend_label, 1, 0)
        metrics_layout.addWidget(self.vwap_label, 1, 1)
        header_layout.addWidget(metrics_group)
        
        # P&L Summary
        pnl_group = QGroupBox("P&L Today")
        pnl_layout = QGridLayout(pnl_group)
        
        self.daily_pnl_label = QLabel("0.00")
        self.daily_pnl_label.setObjectName("bigPrice")
        self.daily_pnl_label.setAlignment(Qt.AlignCenter)
        self.trades_count_label = QLabel("Trades: 0")
        self.win_rate_label = QLabel("Win Rate: --%")
        
        pnl_layout.addWidget(self.daily_pnl_label, 0, 0, 1, 2)
        pnl_layout.addWidget(self.trades_count_label, 1, 0)
        pnl_layout.addWidget(self.win_rate_label, 1, 1)
        header_layout.addWidget(pnl_group)
        
        # Risk Status
        risk_group = QGroupBox("Risk Status")
        risk_layout = QVBoxLayout(risk_group)
        
        self.risk_level_label = QLabel("LOW")
        self.risk_level_label.setAlignment(Qt.AlignCenter)
        self.risk_level_label.setStyleSheet("color: #10b981; font-size: 16px; font-weight: bold;")
        self.drawdown_bar = QProgressBar()
        self.drawdown_bar.setMaximum(100)
        self.drawdown_bar.setFormat("DD: %v%")
        
        risk_layout.addWidget(self.risk_level_label)
        risk_layout.addWidget(self.drawdown_bar)
        header_layout.addWidget(risk_group)
        
        parent_layout.addWidget(header)

    def _create_index_panel(self, name: str) -> QGroupBox:
        """Create an index price display panel."""
        group = QGroupBox(name)
        layout = QVBoxLayout(group)
        
        ltp = QLabel("---.--")
        ltp.setObjectName("ltp_label")
        ltp.setAlignment(Qt.AlignCenter)
        ltp.setFont(QFont("Consolas", 20, QFont.Bold))
        
        change = QLabel("+0.00 (0.00%)")
        change.setObjectName("change_label")
        change.setAlignment(Qt.AlignCenter)
        
        layout.addWidget(ltp)
        layout.addWidget(change)
        
        return group



    # =========================================================================
    # MAIN CONTENT - Tabs
    # =========================================================================

    def _build_main_content(self, parent_layout):
        """Build main content area with tabs."""
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Trading & Analysis
        left_tabs = QTabWidget()
        left_tabs.addTab(self._build_trading_panel(), "Trading")
        left_tabs.addTab(self._build_option_chain_panel(), "Option Chain")
        left_tabs.addTab(self._build_oi_analysis_panel(), "OI Analysis")
        left_tabs.addTab(self._build_greeks_panel(), "Greeks")
        left_tabs.addTab(self._build_strategy_panel(), "Strategy")
        splitter.addWidget(left_tabs)
        
        # Right panel - Orders & Analytics
        right_tabs = QTabWidget()
        right_tabs.addTab(self._build_order_book_panel(), "Orders")
        right_tabs.addTab(self._build_positions_panel(), "Positions")
        right_tabs.addTab(self._build_performance_panel(), "Performance")
        right_tabs.addTab(self._build_risk_panel(), "Risk Monitor")
        right_tabs.addTab(self._build_signal_log_panel(), "Signal Log")
        splitter.addWidget(right_tabs)
        
        splitter.setSizes([900, 700])
        parent_layout.addWidget(splitter)

    # =========================================================================
    # TRADING PANEL - Buttons & Execution
    # =========================================================================

    def _build_trading_panel(self) -> QWidget:
        """Build the main trading execution panel with buttons."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Instrument Selection
        sel_group = QGroupBox("Instrument Selection")
        sel_layout = QHBoxLayout(sel_group)
        
        sel_layout.addWidget(QLabel("Index:"))
        self.index_combo = QComboBox()
        self.index_combo.addItems(["NIFTY", "BANKNIFTY", "FINNIFTY"])
        sel_layout.addWidget(self.index_combo)
        
        sel_layout.addWidget(QLabel("Lots:"))
        self.lots_spin = QSpinBox()
        self.lots_spin.setRange(1, 50)
        self.lots_spin.setValue(1)
        sel_layout.addWidget(self.lots_spin)
        
        sel_layout.addWidget(QLabel("Order Type:"))
        self.order_type_combo = QComboBox()
        self.order_type_combo.addItems(["MARKET", "LIMIT", "SL-MARKET", "SL-LIMIT"])
        sel_layout.addWidget(self.order_type_combo)
        
        self.confirm_check = QCheckBox("Confirm Before Execution")
        self.confirm_check.setChecked(True)
        sel_layout.addWidget(self.confirm_check)
        
        layout.addWidget(sel_group)
        
        # ATM Info Display
        atm_group = QGroupBox("ATM Strike Info")
        atm_layout = QGridLayout(atm_group)
        
        self.atm_strike_label = QLabel("ATM: ---")
        self.atm_strike_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.ce_price_label = QLabel("CE LTP: ---.--")
        self.pe_price_label = QLabel("PE LTP: ---.--")
        self.ce_iv_label = QLabel("CE IV: --.--%")
        self.pe_iv_label = QLabel("PE IV: --.--%")
        self.spread_label = QLabel("Spread: ---")
        
        atm_layout.addWidget(self.atm_strike_label, 0, 0, 1, 2)
        atm_layout.addWidget(self.ce_price_label, 1, 0)
        atm_layout.addWidget(self.pe_price_label, 1, 1)
        atm_layout.addWidget(self.ce_iv_label, 2, 0)
        atm_layout.addWidget(self.pe_iv_label, 2, 1)
        atm_layout.addWidget(self.spread_label, 3, 0, 1, 2)
        
        layout.addWidget(atm_group)
        
        # Trading Buttons
        buttons_group = QGroupBox("EXECUTION CONTROLS")
        buttons_layout = QGridLayout(buttons_group)
        
        # Buy CE Button
        self.buy_ce_btn = QPushButton("BUY CE (CALL)")
        self.buy_ce_btn.setObjectName("buyButton")
        self.buy_ce_btn.setMinimumHeight(60)
        self.buy_ce_btn.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.buy_ce_btn.clicked.connect(lambda: self._execute_trade("BUY", "CE"))
        buttons_layout.addWidget(self.buy_ce_btn, 0, 0)
        
        # Buy PE Button
        self.buy_pe_btn = QPushButton("BUY PE (PUT)")
        self.buy_pe_btn.setObjectName("buyButton")
        self.buy_pe_btn.setMinimumHeight(60)
        self.buy_pe_btn.setFont(QFont("Segoe UI", 14, QFont.Bold))
        self.buy_pe_btn.clicked.connect(lambda: self._execute_trade("BUY", "PE"))
        buttons_layout.addWidget(self.buy_pe_btn, 0, 1)
        
        # Sell/Exit CE Button
        self.sell_ce_btn = QPushButton("EXIT CE")
        self.sell_ce_btn.setObjectName("sellButton")
        self.sell_ce_btn.setMinimumHeight(50)
        self.sell_ce_btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.sell_ce_btn.clicked.connect(lambda: self._execute_trade("SELL", "CE"))
        buttons_layout.addWidget(self.sell_ce_btn, 1, 0)
        
        # Sell/Exit PE Button
        self.sell_pe_btn = QPushButton("EXIT PE")
        self.sell_pe_btn.setObjectName("sellButton")
        self.sell_pe_btn.setMinimumHeight(50)
        self.sell_pe_btn.setFont(QFont("Segoe UI", 12, QFont.Bold))
        self.sell_pe_btn.clicked.connect(lambda: self._execute_trade("SELL", "PE"))
        buttons_layout.addWidget(self.sell_pe_btn, 1, 1)
        
        # Square Off All
        self.squareoff_btn = QPushButton("SQUARE OFF ALL POSITIONS")
        self.squareoff_btn.setObjectName("emergencyButton")
        self.squareoff_btn.setMinimumHeight(50)
        self.squareoff_btn.clicked.connect(self._square_off_all)
        buttons_layout.addWidget(self.squareoff_btn, 2, 0, 1, 2)
        
        # Cancel All Orders
        self.cancel_all_btn = QPushButton("CANCEL ALL ORDERS")
        self.cancel_all_btn.setStyleSheet(
            "background-color: #b45309; border-color: #f59e0b; font-weight: bold;"
        )
        self.cancel_all_btn.setMinimumHeight(40)
        self.cancel_all_btn.clicked.connect(self._cancel_all_orders)
        buttons_layout.addWidget(self.cancel_all_btn, 3, 0, 1, 2)
        
        layout.addWidget(buttons_group)
        
        # Signal Display
        signal_group = QGroupBox("Current Signal")
        signal_layout = QVBoxLayout(signal_group)
        self.signal_display = QLabel("No Active Signal")
        self.signal_display.setAlignment(Qt.AlignCenter)
        self.signal_display.setFont(QFont("Consolas", 12))
        self.signal_confidence = QProgressBar()
        self.signal_confidence.setMaximum(100)
        self.signal_confidence.setFormat("Confidence: %v%")
        signal_layout.addWidget(self.signal_display)
        signal_layout.addWidget(self.signal_confidence)
        layout.addWidget(signal_group)
        
        return panel



    # =========================================================================
    # OPTION CHAIN PANEL
    # =========================================================================

    def _build_option_chain_panel(self) -> QWidget:
        """Build option chain display with OI, IV, Greeks."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Option chain table
        self.oc_table = QTableWidget()
        self.oc_table.setColumnCount(13)
        self.oc_table.setHorizontalHeaderLabels([
            "CE OI", "CE OI Chg", "CE Vol", "CE IV", "CE LTP",
            "CE Delta", "STRIKE", "PE Delta",
            "PE LTP", "PE IV", "PE Vol", "PE OI Chg", "PE OI"
        ])
        self.oc_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.oc_table.setAlternatingRowColors(True)
        
        layout.addWidget(self.oc_table)
        return panel

    # =========================================================================
    # OI ANALYSIS PANEL
    # =========================================================================

    def _build_oi_analysis_panel(self) -> QWidget:
        """Build OI change analysis with multi-timeframe view."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # OI Change table
        oi_group = QGroupBox("OI Change Analysis (Multi-Timeframe)")
        oi_layout = QVBoxLayout(oi_group)
        
        self.oi_table = QTableWidget()
        self.oi_table.setColumnCount(9)
        self.oi_table.setHorizontalHeaderLabels([
            "Strike", "CE OI", "PE OI",
            "CE 1m Chg", "CE 5m Chg", "CE 15m Chg",
            "PE 1m Chg", "PE 5m Chg", "PE 15m Chg"
        ])
        self.oi_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        oi_layout.addWidget(self.oi_table)
        layout.addWidget(oi_group)
        
        # PCR and Max OI display
        summary_group = QGroupBox("OI Summary")
        summary_layout = QGridLayout(summary_group)
        
        self.total_ce_oi_label = QLabel("Total CE OI: ---")
        self.total_pe_oi_label = QLabel("Total PE OI: ---")
        self.pcr_display = QLabel("PCR: ---")
        self.pcr_display.setFont(QFont("Consolas", 14, QFont.Bold))
        self.max_ce_oi_label = QLabel("Max CE OI Strike: ---")
        self.max_pe_oi_label = QLabel("Max PE OI Strike: ---")
        
        summary_layout.addWidget(self.total_ce_oi_label, 0, 0)
        summary_layout.addWidget(self.total_pe_oi_label, 0, 1)
        summary_layout.addWidget(self.pcr_display, 0, 2)
        summary_layout.addWidget(self.max_ce_oi_label, 1, 0)
        summary_layout.addWidget(self.max_pe_oi_label, 1, 1)
        
        layout.addWidget(summary_group)
        return panel

    # =========================================================================
    # GREEKS PANEL
    # =========================================================================

    def _build_greeks_panel(self) -> QWidget:
        """Build Greeks display panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        greeks_group = QGroupBox("Options Greeks (ATM)")
        greeks_layout = QGridLayout(greeks_group)
        
        headers = ["", "Delta", "Gamma", "Theta", "Vega", "IV"]
        for col, h in enumerate(headers):
            lbl = QLabel(h)
            lbl.setFont(QFont("Consolas", 10, QFont.Bold))
            lbl.setStyleSheet("color: #00d4ff;")
            greeks_layout.addWidget(lbl, 0, col)
        
        # CE Greeks row
        greeks_layout.addWidget(QLabel("CE:"), 1, 0)
        self.ce_delta_val = QLabel("---")
        self.ce_gamma_val = QLabel("---")
        self.ce_theta_val = QLabel("---")
        self.ce_vega_val = QLabel("---")
        self.ce_iv_val = QLabel("---")
        greeks_layout.addWidget(self.ce_delta_val, 1, 1)
        greeks_layout.addWidget(self.ce_gamma_val, 1, 2)
        greeks_layout.addWidget(self.ce_theta_val, 1, 3)
        greeks_layout.addWidget(self.ce_vega_val, 1, 4)
        greeks_layout.addWidget(self.ce_iv_val, 1, 5)
        
        # PE Greeks row
        greeks_layout.addWidget(QLabel("PE:"), 2, 0)
        self.pe_delta_val = QLabel("---")
        self.pe_gamma_val = QLabel("---")
        self.pe_theta_val = QLabel("---")
        self.pe_vega_val = QLabel("---")
        self.pe_iv_val = QLabel("---")
        greeks_layout.addWidget(self.pe_delta_val, 2, 1)
        greeks_layout.addWidget(self.pe_gamma_val, 2, 2)
        greeks_layout.addWidget(self.pe_theta_val, 2, 3)
        greeks_layout.addWidget(self.pe_vega_val, 2, 4)
        greeks_layout.addWidget(self.pe_iv_val, 2, 5)
        
        layout.addWidget(greeks_group)
        
        # Portfolio Greeks
        port_group = QGroupBox("Portfolio Greeks (Net)")
        port_layout = QGridLayout(port_group)
        
        self.net_delta_label = QLabel("Net Delta: 0.000")
        self.net_gamma_label = QLabel("Net Gamma: 0.000")
        self.net_theta_label = QLabel("Net Theta: 0.00")
        self.net_vega_label = QLabel("Net Vega: 0.00")
        
        port_layout.addWidget(self.net_delta_label, 0, 0)
        port_layout.addWidget(self.net_gamma_label, 0, 1)
        port_layout.addWidget(self.net_theta_label, 1, 0)
        port_layout.addWidget(self.net_vega_label, 1, 1)
        
        layout.addWidget(port_group)
        layout.addStretch()
        return panel



    # =========================================================================
    # STRATEGY PANEL
    # =========================================================================

    def _build_strategy_panel(self) -> QWidget:
        """Build strategy control and analysis panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Strategy Controls
        ctrl_group = QGroupBox("Strategy Controls")
        ctrl_layout = QHBoxLayout(ctrl_group)
        
        self.strategy_mode_combo = QComboBox()
        self.strategy_mode_combo.addItems(["Full Auto", "Semi Auto", "Manual"])
        self.strategy_mode_combo.setCurrentIndex(1)
        ctrl_layout.addWidget(QLabel("Mode:"))
        ctrl_layout.addWidget(self.strategy_mode_combo)
        
        self.start_strategy_btn = QPushButton("START")
        self.start_strategy_btn.setStyleSheet("background-color: #0d6e3f; min-width: 100px;")
        self.start_strategy_btn.clicked.connect(self._start_strategy)
        ctrl_layout.addWidget(self.start_strategy_btn)
        
        self.stop_strategy_btn = QPushButton("STOP")
        self.stop_strategy_btn.setStyleSheet("background-color: #7f1d1d; min-width: 100px;")
        self.stop_strategy_btn.clicked.connect(self._stop_strategy)
        ctrl_layout.addWidget(self.stop_strategy_btn)
        
        layout.addWidget(ctrl_group)
        
        # Analysis Display
        analysis_group = QGroupBox("Market Analysis Scores")
        analysis_layout = QGridLayout(analysis_group)
        
        self.oi_score_label = QLabel("OI Score: ---")
        self.iv_score_label = QLabel("IV Score: ---")
        self.trend_score_label = QLabel("Trend Score: ---")
        self.vwap_score_label = QLabel("VWAP Score: ---")
        self.volume_score_label = QLabel("Volume Score: ---")
        self.flow_score_label = QLabel("Flow Score: ---")
        self.composite_score_label = QLabel("COMPOSITE: ---")
        self.composite_score_label.setFont(QFont("Consolas", 14, QFont.Bold))
        self.bias_label = QLabel("BIAS: NEUTRAL")
        self.bias_label.setFont(QFont("Consolas", 16, QFont.Bold))
        
        analysis_layout.addWidget(self.oi_score_label, 0, 0)
        analysis_layout.addWidget(self.iv_score_label, 0, 1)
        analysis_layout.addWidget(self.trend_score_label, 1, 0)
        analysis_layout.addWidget(self.vwap_score_label, 1, 1)
        analysis_layout.addWidget(self.volume_score_label, 2, 0)
        analysis_layout.addWidget(self.flow_score_label, 2, 1)
        analysis_layout.addWidget(self.composite_score_label, 3, 0)
        analysis_layout.addWidget(self.bias_label, 3, 1)
        
        layout.addWidget(analysis_group)
        
        # Institutional Activity
        inst_group = QGroupBox("Institutional Activity")
        inst_layout = QVBoxLayout(inst_group)
        self.inst_signal_label = QLabel("Signal: NEUTRAL")
        self.inst_signal_label.setFont(QFont("Consolas", 12, QFont.Bold))
        self.inst_desc_label = QLabel("---")
        self.smart_flow_label = QLabel("Smart Money: NEUTRAL")
        
        inst_layout.addWidget(self.inst_signal_label)
        inst_layout.addWidget(self.inst_desc_label)
        inst_layout.addWidget(self.smart_flow_label)
        layout.addWidget(inst_group)
        
        layout.addStretch()
        return panel

    # =========================================================================
    # ORDER BOOK PANEL
    # =========================================================================

    def _build_order_book_panel(self) -> QWidget:
        """Build order book display."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        self.order_table = QTableWidget()
        self.order_table.setColumnCount(9)
        self.order_table.setHorizontalHeaderLabels([
            "Time", "Symbol", "Type", "Qty", "Price",
            "Status", "Avg Price", "Order ID", "Remarks"
        ])
        self.order_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.order_table)
        
        return panel

    # =========================================================================
    # POSITIONS PANEL
    # =========================================================================

    def _build_positions_panel(self) -> QWidget:
        """Build positions display."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        self.position_table = QTableWidget()
        self.position_table.setColumnCount(10)
        self.position_table.setHorizontalHeaderLabels([
            "Symbol", "Qty", "Avg Price", "LTP", "P&L",
            "P&L %", "SL", "Target", "Product", "Action"
        ])
        self.position_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.position_table)
        
        return panel



    # =========================================================================
    # PERFORMANCE PANEL
    # =========================================================================

    def _build_performance_panel(self) -> QWidget:
        """Build performance analytics panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Daily stats
        stats_group = QGroupBox("Trading Performance")
        stats_layout = QGridLayout(stats_group)
        
        self.perf_labels = {}
        stats = [
            ("Total Trades", "total_trades"),
            ("Winners", "winners"),
            ("Losers", "losers"),
            ("Win Rate", "win_rate"),
            ("Avg Win", "avg_win"),
            ("Avg Loss", "avg_loss"),
            ("Profit Factor", "profit_factor"),
            ("Largest Win", "largest_win"),
            ("Largest Loss", "largest_loss"),
            ("Net P&L", "net_pnl"),
            ("Max Drawdown", "max_dd"),
            ("Avg Exec Time", "exec_time"),
        ]
        
        for i, (name, key) in enumerate(stats):
            row, col = divmod(i, 3)
            lbl = QLabel(f"{name}: ---")
            self.perf_labels[key] = lbl
            stats_layout.addWidget(lbl, row, col)
        
        layout.addWidget(stats_group)
        
        # Execution metrics
        exec_group = QGroupBox("Execution Analytics")
        exec_layout = QGridLayout(exec_group)
        
        self.fill_rate_label = QLabel("Fill Rate: ---")
        self.avg_slippage_label = QLabel("Avg Slippage: ---")
        self.total_slippage_label = QLabel("Total Slippage: ---")
        self.order_success_label = QLabel("Order Success: ---")
        
        exec_layout.addWidget(self.fill_rate_label, 0, 0)
        exec_layout.addWidget(self.avg_slippage_label, 0, 1)
        exec_layout.addWidget(self.total_slippage_label, 1, 0)
        exec_layout.addWidget(self.order_success_label, 1, 1)
        
        layout.addWidget(exec_group)
        layout.addStretch()
        return panel

    # =========================================================================
    # RISK MONITOR PANEL
    # =========================================================================

    def _build_risk_panel(self) -> QWidget:
        """Build risk monitoring panel."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        # Capital Status
        cap_group = QGroupBox("Capital & Exposure")
        cap_layout = QGridLayout(cap_group)
        
        self.total_capital_label = QLabel("Total Capital: ---")
        self.deployed_label = QLabel("Deployed: ---")
        self.available_label = QLabel("Available: ---")
        self.exposure_label = QLabel("Exposure: ---")
        
        cap_layout.addWidget(self.total_capital_label, 0, 0)
        cap_layout.addWidget(self.deployed_label, 0, 1)
        cap_layout.addWidget(self.available_label, 1, 0)
        cap_layout.addWidget(self.exposure_label, 1, 1)
        layout.addWidget(cap_group)
        
        # Risk Limits
        limits_group = QGroupBox("Risk Limits Status")
        limits_layout = QGridLayout(limits_group)
        
        self.daily_loss_bar = QProgressBar()
        self.daily_loss_bar.setMaximum(100)
        self.daily_loss_bar.setFormat("Daily Loss: %v%")
        
        self.trades_bar = QProgressBar()
        self.trades_bar.setMaximum(100)
        self.trades_bar.setFormat("Trades Used: %v%")
        
        self.consec_loss_label = QLabel("Consecutive Losses: 0")
        self.circuit_label = QLabel("Circuit Breaker: NORMAL")
        self.circuit_label.setStyleSheet("color: #10b981; font-weight: bold;")
        
        limits_layout.addWidget(QLabel("Daily Loss Limit:"), 0, 0)
        limits_layout.addWidget(self.daily_loss_bar, 0, 1)
        limits_layout.addWidget(QLabel("Daily Trades:"), 1, 0)
        limits_layout.addWidget(self.trades_bar, 1, 1)
        limits_layout.addWidget(self.consec_loss_label, 2, 0)
        limits_layout.addWidget(self.circuit_label, 2, 1)
        
        layout.addWidget(limits_group)
        
        # Circuit Breaker Controls
        cb_group = QGroupBox("Circuit Breaker Controls")
        cb_layout = QHBoxLayout(cb_group)
        
        self.reset_circuit_btn = QPushButton("Reset Circuit Breaker")
        self.reset_circuit_btn.clicked.connect(self._reset_circuit)
        self.pause_trading_btn = QPushButton("Pause Trading")
        self.pause_trading_btn.clicked.connect(self._pause_trading)
        
        cb_layout.addWidget(self.reset_circuit_btn)
        cb_layout.addWidget(self.pause_trading_btn)
        layout.addWidget(cb_group)
        
        layout.addStretch()
        return panel

    # =========================================================================
    # SIGNAL LOG PANEL
    # =========================================================================

    def _build_signal_log_panel(self) -> QWidget:
        """Build signal history log."""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        self.signal_log = QTextEdit()
        self.signal_log.setReadOnly(True)
        self.signal_log.setFont(QFont("Consolas", 10))
        layout.addWidget(self.signal_log)
        
        return panel



    # =========================================================================
    # STATUS BAR
    # =========================================================================

    def _build_status_bar(self):
        """Build status bar with connection info."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.connection_label = QLabel("Disconnected")
        self.connection_label.setStyleSheet("color: #ef4444;")
        self.ws_status_label = QLabel("WS: OFF")
        self.time_label = QLabel(datetime.now().strftime("%H:%M:%S"))
        self.mode_label = QLabel("Mode: Semi-Auto")
        
        self.status_bar.addWidget(self.connection_label)
        self.status_bar.addWidget(self.ws_status_label)
        self.status_bar.addPermanentWidget(self.mode_label)
        self.status_bar.addPermanentWidget(self.time_label)

    # =========================================================================
    # TRADING EXECUTION
    # =========================================================================

    def _execute_trade(self, action: str, option_type: str):
        """Execute a trade with optional confirmation."""
        index = self.index_combo.currentText()
        lots = self.lots_spin.value()
        order_type = self.order_type_combo.currentText()
        
        # Build trade details
        trade_desc = f"{action} {index} ATM {option_type} x {lots} lots ({order_type})"
        
        # Confirmation dialog
        if self.confirm_check.isChecked():
            reply = QMessageBox.question(
                self, "Confirm Trade",
                f"Execute the following trade?\n\n{trade_desc}\n\n"
                f"Are you sure you want to proceed?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply != QMessageBox.Yes:
                self._log_signal(f"Trade cancelled by user: {trade_desc}")
                return
        
        # Execute via trading system
        if self.trading_system:
            self.trading_system.execute_manual_trade(
                index=index,
                option_type=option_type,
                action=action,
                lots=lots,
                order_type=order_type,
            )
        
        self._log_signal(f"EXECUTED: {trade_desc}")

    def _square_off_all(self):
        """Square off all positions with confirmation."""
        reply = QMessageBox.warning(
            self, "SQUARE OFF ALL",
            "This will close ALL open positions at market price.\n\n"
            "Are you absolutely sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.trading_system:
                self.trading_system.square_off_all()
            self._log_signal("EMERGENCY: All positions squared off!")

    def _cancel_all_orders(self):
        """Cancel all pending orders."""
        reply = QMessageBox.question(
            self, "Cancel All Orders",
            "Cancel all pending/open orders?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.trading_system:
                self.trading_system.cancel_all_orders()
            self._log_signal("All pending orders cancelled")

    def _start_strategy(self):
        """Start automated strategy."""
        mode = self.strategy_mode_combo.currentText().lower().replace(" ", "_")
        if self.trading_system:
            self.trading_system.start_strategy(mode)
        self._log_signal(f"Strategy started in {mode} mode")

    def _stop_strategy(self):
        """Stop automated strategy."""
        if self.trading_system:
            self.trading_system.stop_strategy()
        self._log_signal("Strategy stopped")

    def _reset_circuit(self):
        """Reset circuit breaker."""
        reply = QMessageBox.question(
            self, "Reset Circuit Breaker",
            "Reset circuit breaker and resume trading?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.trading_system:
                self.trading_system.reset_circuit_breaker()
            self._log_signal("Circuit breaker reset")

    def _pause_trading(self):
        """Pause all trading activity."""
        if self.trading_system:
            self.trading_system.pause_trading()
        self._log_signal("Trading paused manually")

    # =========================================================================
    # DATA REFRESH
    # =========================================================================

    def _refresh_data(self):
        """Periodic data refresh (called by timer)."""
        self.time_label.setText(datetime.now().strftime("%H:%M:%S"))
        
        if not self.trading_system:
            return
        
        # This would be connected to real data in production
        # For now, structure is in place for data binding

    def _log_signal(self, message: str):
        """Add message to signal log."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.signal_log.append(f"[{timestamp}] {message}")

    # =========================================================================
    # PUBLIC UPDATE METHODS (called by trading system)
    # =========================================================================

    def update_index_display(self, nifty_data: Dict, banknifty_data: Dict):
        """Update index price displays."""
        if self.nifty_ltp:
            self.nifty_ltp.setText(f"{nifty_data.get('ltp', 0):.2f}")
        if self.banknifty_ltp:
            self.banknifty_ltp.setText(f"{banknifty_data.get('ltp', 0):.2f}")

    def update_pnl_display(self, pnl: float, trades: int, win_rate: float):
        """Update P&L display."""
        self.daily_pnl_label.setText(f"{pnl:+,.2f}")
        if pnl >= 0:
            self.daily_pnl_label.setStyleSheet("color: #10b981; font-size: 24px; font-weight: bold;")
        else:
            self.daily_pnl_label.setStyleSheet("color: #ef4444; font-size: 24px; font-weight: bold;")
        self.trades_count_label.setText(f"Trades: {trades}")
        self.win_rate_label.setText(f"Win Rate: {win_rate:.1f}%")

    def update_signal_display(self, signal_data: Dict):
        """Update current signal display."""
        signal_type = signal_data.get("type", "NONE")
        confidence = signal_data.get("confidence", 0)
        
        self.signal_display.setText(
            f"{signal_type} | Confidence: {confidence}%"
        )
        self.signal_confidence.setValue(int(confidence))
        
        if "CE" in signal_type:
            self.signal_display.setStyleSheet("color: #10b981; font-weight: bold;")
        elif "PE" in signal_type:
            self.signal_display.setStyleSheet("color: #ef4444; font-weight: bold;")
        else:
            self.signal_display.setStyleSheet("color: #888;")
