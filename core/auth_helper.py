"""
Authentication Helper
======================
Handles Flattrade OAuth login flow and token management.

Flow:
1. Open browser to Flattrade login page
2. User authenticates with credentials + TOTP
3. Redirect captures request_token
4. Generate session token using API key + secret + request_token
"""

import hashlib
import webbrowser
import logging
import json
import os
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_CACHE_FILE = "config/.token_cache.json"


class TokenCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler to capture OAuth redirect with request token."""
    
    token = None
    
    def do_GET(self):
        """Handle redirect from Flattrade OAuth."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if "code" in params:
            TokenCallbackHandler.token = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            response = """
            <html><body style="background:#1a1a2e;color:#10b981;
            font-family:monospace;text-align:center;padding:50px;">
            <h1>Authentication Successful!</h1>
            <p>Token received. You can close this window.</p>
            <p>Return to AlgoTrade application.</p>
            </body></html>
            """
            self.wfile.write(response.encode())
        else:
            self.send_response(400)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


class AuthHelper:
    """
    Manages Flattrade authentication lifecycle.
    
    Features:
    - Browser-based OAuth login
    - Token caching with expiry
    - Auto-refresh on expiry
    - Secure token storage
    """

    def __init__(self, config: Dict[str, Any]):
        self.api_key = config.get("api_key", "")
        self.api_secret = config.get("api_secret", "")
        self.user_id = config.get("user_id", "")
        self.redirect_port = 8765
        self.redirect_uri = f"http://127.0.0.1:{self.redirect_port}/callback"
        
        # Flattrade auth URL
        self.auth_base_url = "https://auth.flattrade.in/"

    def login_via_browser(self) -> Optional[str]:
        """
        Initiate browser-based login and capture request token.
        
        Returns:
            request_token if successful, None otherwise
        """
        # Check cached token first
        cached = self._load_cached_token()
        if cached:
            logger.info("Using cached token (valid until: %s)", cached.get("expiry"))
            return cached.get("request_token")
        
        # Build auth URL
        auth_url = (
            f"{self.auth_base_url}?"
            f"app_key={self.api_key}"
            f"&redirect_uri={self.redirect_uri}"
        )
        
        logger.info("Opening browser for authentication...")
        logger.info("Auth URL: %s", auth_url)
        
        # Open browser
        webbrowser.open(auth_url)
        
        # Start local server to capture redirect
        TokenCallbackHandler.token = None
        server = HTTPServer(("127.0.0.1", self.redirect_port), TokenCallbackHandler)
        server.timeout = 120  # 2 minute timeout
        
        logger.info("Waiting for authentication callback on port %d...", self.redirect_port)
        
        while TokenCallbackHandler.token is None:
            server.handle_request()
            if TokenCallbackHandler.token:
                break
        
        server.server_close()
        
        request_token = TokenCallbackHandler.token
        if request_token:
            logger.info("Request token received successfully")
            self._cache_token(request_token)
            return request_token
        else:
            logger.error("Failed to receive request token")
            return None

    def generate_api_token(self, request_token: str) -> str:
        """
        Generate API session token hash.
        Token = SHA256(api_key + request_token + api_secret)
        """
        token_string = f"{self.api_key}{request_token}{self.api_secret}"
        return hashlib.sha256(token_string.encode()).hexdigest()

    def _cache_token(self, request_token: str) -> None:
        """Cache token to file with expiry."""
        cache_data = {
            "request_token": request_token,
            "user_id": self.user_id,
            "timestamp": datetime.now().isoformat(),
            "expiry": (datetime.now() + timedelta(hours=8)).isoformat(),
        }
        
        cache_path = Path(TOKEN_CACHE_FILE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(cache_path, 'w') as f:
            json.dump(cache_data, f)
        
        logger.info("Token cached until %s", cache_data["expiry"])

    def _load_cached_token(self) -> Optional[Dict]:
        """Load cached token if still valid."""
        cache_path = Path(TOKEN_CACHE_FILE)
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r') as f:
                cache = json.load(f)
            
            expiry = datetime.fromisoformat(cache["expiry"])
            if datetime.now() < expiry:
                return cache
            else:
                logger.info("Cached token expired")
                cache_path.unlink()
                return None
        except Exception:
            return None

    def clear_cache(self) -> None:
        """Clear cached tokens."""
        cache_path = Path(TOKEN_CACHE_FILE)
        if cache_path.exists():
            cache_path.unlink()
            logger.info("Token cache cleared")
