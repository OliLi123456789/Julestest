# trading_engine/risk_management/risk_rules.py
from typing import Dict, Any, List, Optional
# from trading_engine.oms.models import Order # Not strictly needed here, but for context
# from trading_engine.oms.position_models import Position # Not strictly needed here

class AccountInfo: # Placeholder for Account Data
    def __init__(self, user_id: str, balance: float, buying_power: float, margin_available: Optional[float] = None):
        self.user_id = user_id
        self.balance = balance
        self.buying_power = buying_power
        # Margin available might not be applicable for all account types or risk checks
        self.margin_available = margin_available if margin_available is not None else buying_power

class RiskRuleViolation(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)

# DEFAULT_RISK_CONFIG has been moved to risk_config_loader.py
# It will be loaded by RiskManager via load_risk_config_from_file.
