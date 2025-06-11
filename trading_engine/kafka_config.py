import os

class KafkaTradingEngineConfig:
    def __init__(self):
        self.bootstrap_servers = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
        self.new_orders_topic = os.getenv("KAFKA_NEW_ORDERS_TOPIC", "trading.new-orders")
        # Topics for consuming updates from ibkr-gateway-service
        self.order_status_updates_topic = os.getenv("KAFKA_ORDER_STATUS_UPDATES_TOPIC", "ibkr.order-updates")
        self.execution_reports_topic = os.getenv("KAFKA_EXECUTION_REPORTS_TOPIC", "ibkr.execution-reports")
