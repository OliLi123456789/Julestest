import json
import time
# Assuming oms.models is accessible for DomainOrderType. If not, adjust import or simplify.
# For this simulated environment, direct import might be tricky depending on how tools handle paths.
# Let's try a relative import path assuming a certain structure or simplify the mapping.
# from ....oms.models import OrderType as DomainOrderType # This path is unlikely to work in tool's flat structure

# Simplified mapping for this simulated file:
class DomainOrderTypeSimulated: # Simulate the structure if direct import fails
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    TRAIL = "TRAIL"

class OrderTypeProto: # Simplified enum
    UNKNOWN_ORDER_TYPE = 0
    MARKET = 1
    LIMIT = 2
    STOP = 3
    STOP_LIMIT = 4
    TRAIL = 5

class NewOrderRequest:
    def __init__(self, platform_order_id='', user_id='', symbol='', sec_type='STK',
                 exchange='SMART', currency='USD', quantity=0.0, order_type=OrderTypeProto.MARKET,
                 limit_price=0.0, # Used for LIMIT and STOP_LIMIT orders
                 stop_price=0.0,  # Used for STOP and STOP_LIMIT orders
                 trailing_percent=0.0, # Used for TRAIL orders
                 trailing_amount=0.0,  # Used for TRAIL orders
                 trail_stop_price=0.0, # Used for TRAIL orders (initial stop price to start trailing)
                 time_in_force='DAY', account_id='',
                 request_timestamp_utc=None,
                 last_trade_date_or_contract_month='', strike=0.0, right='',
                 multiplier='', primary_exchange=''):
        self.platform_order_id = platform_order_id
        self.user_id = user_id
        self.symbol = symbol
        self.sec_type = sec_type
        self.exchange = exchange
        self.currency = currency
        self.quantity = quantity
        self.order_type = order_type # This should be an int from OrderTypeProto
        self.limit_price = limit_price
        self.stop_price = stop_price
        self.trailing_percent = trailing_percent
        self.trailing_amount = trailing_amount
        self.trail_stop_price = trail_stop_price
        self.time_in_force = time_in_force
        self.account_id = account_id
        # Ensure request_timestamp_utc is a float (Unix timestamp)
        if hasattr(request_timestamp_utc, 'timestamp'): # If it's a datetime object
            self.request_timestamp_utc = request_timestamp_utc.timestamp()
        elif request_timestamp_utc is None:
            self.request_timestamp_utc = time.time()
        else: # Assume it's already a float/int timestamp
            self.request_timestamp_utc = float(request_timestamp_utc)

        self.last_trade_date_or_contract_month = last_trade_date_or_contract_month
        self.strike = strike
        self.right = right
        self.multiplier = multiplier
        self.primary_exchange = primary_exchange

    def SerializeToString(self):
        # Dummy serialization for simulation
        # Create a dictionary of attributes
        attrs = {k: v for k, v in self.__dict__.items()}
        # Ensure order_type is its value for JSON serialization if it's an int enum
        if isinstance(self.order_type, int): # Assuming OrderTypeProto values are ints
             pass # It's already a serializable int
        elif hasattr(self.order_type, 'value'): # If it's a proper Enum object
            attrs['order_type'] = self.order_type.value

        return json.dumps(attrs).encode('utf-8')

    @classmethod
    def FromDomainOrder(cls, domain_order, user_config=None):
        # domain_order is trading_engine.oms.models.Order

        proto_order_type = OrderTypeProto.UNKNOWN_ORDER_TYPE
        # Accessing domain_order.order_type.value as per current Enum definition in models.py
        domain_order_type_str = domain_order.order_type.value # e.g. "LIMIT"
        if domain_order_type_str == DomainOrderTypeSimulated.MARKET:
            proto_order_type = OrderTypeProto.MARKET
        elif domain_order_type_str == DomainOrderTypeSimulated.LIMIT:
            proto_order_type = OrderTypeProto.LIMIT
        elif domain_order_type_str == DomainOrderTypeSimulated.STOP:
            proto_order_type = OrderTypeProto.STOP
        elif domain_order_type_str == DomainOrderTypeSimulated.STOP_LIMIT:
            proto_order_type = OrderTypeProto.STOP_LIMIT
        elif domain_order_type_str == DomainOrderTypeSimulated.TRAIL:
            proto_order_type = OrderTypeProto.TRAIL

        sec_type = user_config.get("sec_type", "STK") if user_config else "STK"
        exchange = user_config.get("exchange", "SMART") if user_config else "SMART" # Default to SMART for stocks
        currency = user_config.get("currency", "USD") if user_config else "USD"
        account_id = user_config.get("account_id", "") if user_config else ""
        time_in_force = user_config.get("time_in_force", "DAY") if user_config else "DAY"
        primary_exchange = user_config.get("primary_exchange", "") if user_config else ""


        last_trade_date_or_contract_month = user_config.get("last_trade_date_or_contract_month", "") if user_config else ""
        strike = user_config.get("strike", 0.0) if user_config else 0.0
        right = user_config.get("right", "") if user_config else ""
        multiplier = user_config.get("multiplier", "") if user_config else ""

        created_ts = domain_order.created_at.timestamp() if hasattr(domain_order.created_at, 'timestamp') else float(domain_order.created_at)

        return cls(
            platform_order_id=domain_order.order_id,
            user_id=domain_order.user_id,
            symbol=domain_order.symbol,
            sec_type=sec_type,
            exchange=exchange,
            currency=currency,
            quantity=domain_order.quantity,
            order_type=proto_order_type, # This is now an int from OrderTypeProto
            limit_price=domain_order.price if domain_order.order_type.value in [DomainOrderTypeSimulated.LIMIT, DomainOrderTypeSimulated.STOP_LIMIT] else 0.0,
            stop_price=domain_order.stop_price if domain_order.stop_price is not None else 0.0,
            trailing_percent=domain_order.trailing_percent if domain_order.trailing_percent is not None else 0.0,
            trailing_amount=domain_order.trailing_amount if domain_order.trailing_amount is not None else 0.0,
            trail_stop_price=domain_order.trail_stop_price if domain_order.trail_stop_price is not None else 0.0,
            time_in_force=time_in_force,
            account_id=account_id,
            request_timestamp_utc=created_ts,
            last_trade_date_or_contract_month=last_trade_date_or_contract_month,
            strike=strike,
            right=right,
            multiplier=multiplier,
            primary_exchange=primary_exchange
        )
