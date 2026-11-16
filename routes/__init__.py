"""Flask blueprints."""
from .dns_routes import dns_bp
from .history_routes import history_bp
from .main_routes import main_bp

__all__ = ["dns_bp", "history_bp", "main_bp"]
