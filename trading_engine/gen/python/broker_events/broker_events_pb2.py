# Conceptual - Simulate Protobuf Generation
import json
import time # For event_timestamp_utc default if needed

class BrokerInstrument:
    def __init__(self, symbol='', sec_type='', exchange='', currency='', con_id=0,
                 last_trade_date_or_contract_month='', strike=0.0, right='',
                 multiplier='', primary_exchange='', **kwargs):
        self.symbol = symbol
        self.sec_type = sec_type
        self.exchange = exchange
        self.currency = currency
        self.con_id = con_id
        self.last_trade_date_or_contract_month = last_trade_date_or_contract_month
        self.strike = strike
        self.right = right
        self.multiplier = multiplier
        self.primary_exchange = primary_exchange
        # Ignore other fields for simplicity via **kwargs

class CommissionReportData:
    def __init__(self, execution_id='', commission=0.0, currency='', realized_pnl=0.0,
                 yield_val=0.0, yield_redemption_date=0, **kwargs): # Matched 'yield_val' from previous step
        self.execution_id = execution_id
        self.commission = commission
        self.currency = currency
        self.realized_pnl = realized_pnl
        self.yield_val = yield_val # Changed from 'yield' to 'yield_val'
        self.yield_redemption_date = yield_redemption_date
        # Ignore other fields

class OrderStatusEvent:
    def __init__(self, platform_order_id='', broker_order_id=0, perm_id=0, status='',
                 filled_quantity=0.0, remaining_quantity=0.0, average_fill_price=0.0,
                 last_fill_price=0.0, client_id=0, why_held='', mkt_cap_price=0.0,
                 parent_broker_order_id='', event_timestamp_utc=None, ib_account_id='', **kwargs):
        self.platform_order_id = platform_order_id
        self.broker_order_id = broker_order_id # This is usually an int from IB
        self.perm_id = perm_id
        self.status = status # This will be a string like "FILLED", "SUBMITTED"
        self.filled_quantity = float(filled_quantity)
        self.remaining_quantity = float(remaining_quantity)
        self.average_fill_price = float(average_fill_price)
        self.last_fill_price = float(last_fill_price)
        self.client_id = client_id
        self.why_held = why_held
        self.mkt_cap_price = float(mkt_cap_price)
        self.parent_broker_order_id = str(parent_broker_order_id) if parent_broker_order_id else ""

        # event_timestamp_utc might be a dict like {'seconds': ..., 'nanos': ...} from proto
        # For mock, allow float or dict.
        if isinstance(event_timestamp_utc, dict):
            self.event_timestamp_utc = event_timestamp_utc.get('seconds', time.time())
        elif event_timestamp_utc is None:
            self.event_timestamp_utc = time.time()
        else:
            self.event_timestamp_utc = float(event_timestamp_utc)

        self.ib_account_id = ib_account_id
        # Ignore other fields via **kwargs

    @classmethod
    def FromString(cls, byte_string):
        data = json.loads(byte_string.decode('utf-8'))
        return cls(**data)

class ExecutionReportEvent:
    def __init__(self, platform_order_id='', broker_order_id=0, execution_id='', perm_id=0,
                 instrument=None, side='', filled_quantity=0.0, fill_price=0.0,
                 execution_time_str='', executing_exchange='', currency='', # currency here is often from contract
                 commission_data=None, event_timestamp_utc=None, ib_account_id='',
                 average_price=0.0, cumulative_quantity=0.0, **kwargs):
        self.platform_order_id = platform_order_id
        self.broker_order_id = broker_order_id # This is usually an int from IB
        self.execution_id = execution_id
        self.perm_id = perm_id
        self.instrument = BrokerInstrument(**instrument) if isinstance(instrument, dict) else (instrument if isinstance(instrument, BrokerInstrument) else BrokerInstrument())
        self.side = side
        self.filled_quantity = float(filled_quantity) # Quantity of this specific fill
        self.fill_price = float(fill_price)
        self.execution_time_str = execution_time_str
        self.executing_exchange = executing_exchange
        self.currency = currency
        self.commission_data = CommissionReportData(**commission_data) if isinstance(commission_data, dict) else (commission_data if isinstance(commission_data, CommissionReportData) else CommissionReportData())

        if isinstance(event_timestamp_utc, dict):
            self.event_timestamp_utc = event_timestamp_utc.get('seconds', time.time())
        elif event_timestamp_utc is None:
            self.event_timestamp_utc = time.time()
        else:
            self.event_timestamp_utc = float(event_timestamp_utc)

        self.ib_account_id = ib_account_id
        self.average_price = float(average_price) # Avg price of all fills for the order so far
        self.cumulative_quantity = float(cumulative_quantity) # Total filled quantity for the order so far
        # Ignore other fields

    @classmethod
    def FromString(cls, byte_string):
        data = json.loads(byte_string.decode('utf-8'))
        # Need to handle nested structures if instrument and commission_data are dicts
        if 'instrument' in data and isinstance(data['instrument'], dict):
            data['instrument'] = BrokerInstrument(**data['instrument'])
        if 'commission_data' in data and isinstance(data['commission_data'], dict):
            data['commission_data'] = CommissionReportData(**data['commission_data'])
        return cls(**data)

# Placeholder for other enums if needed from broker_events.proto
class FillType:
    FULL = 0
    PARTIAL = 1
