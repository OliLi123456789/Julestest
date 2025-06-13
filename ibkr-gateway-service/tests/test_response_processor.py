import unittest
from unittest.mock import MagicMock, patch, call, ANY
import threading
import time
import logging

from google.protobuf.timestamp_pb2 import Timestamp as ProtoTimestamp

from ibkr_gateway_service.response_processor import ResponseProcessor, _get_proto_timestamp, normalize_ib_contract_to_broker_instrument
from ibkr_gateway_service.config import KafkaConfig
# from ibkr_gateway_service.ib_wrapper import IBWrapperImpl # Mocked
# from ibkr_gateway_service.kafka_producer import BrokerEventProducer # Mocked
# from ibkr_gateway_service.order_id_mapper import OrderIdMapper # Mocked
# from common.gen.python.broker_events import broker_events_pb2 as broker_pb # Mocked or use real for type checks

# Mock the generated protobuf module if not easily available in test environment
# or to simplify testing specific fields.
broker_pb = MagicMock()
broker_pb.BrokerInstrument = MagicMock()
broker_pb.OrderStatusEvent = MagicMock()
broker_pb.ExecutionReportEvent = MagicMock()
broker_pb.CommissionReportData = MagicMock()
broker_pb.PortfolioUpdateEvent = MagicMock()
broker_pb.AccountValueUpdateEvent = MagicMock()
broker_pb.BrokerErrorEvent = MagicMock()


class TestResponseProcessorHelpers(unittest.TestCase):
    @patch('time.time')
    def test_get_proto_timestamp_none(self, mock_time):
        mock_time.return_value = 1678886400.123456 # Example: 2023-03-15 12:00:00.123456 UTC
        ts = _get_proto_timestamp()
        self.assertEqual(ts.seconds, 1678886400)
        self.assertEqual(ts.nanos, 123456000)

    def test_get_proto_timestamp_specific(self):
        input_ts = 1678886401.987654
        ts = _get_proto_timestamp(input_ts)
        self.assertEqual(ts.seconds, 1678886401)
        self.assertEqual(ts.nanos, 987654000)

    def test_normalize_ib_contract_to_broker_instrument_full(self):
        mock_ib_contract = MagicMock()
        mock_ib_contract.symbol = "AAPL"
        mock_ib_contract.secType = "STK"
        mock_ib_contract.exchange = "SMART"
        mock_ib_contract.currency = "USD"
        mock_ib_contract.conId = 12345
        mock_ib_contract.lastTradeDateOrContractMonth = "20240119"
        mock_ib_contract.strike = 150.0
        mock_ib_contract.right = "C"
        mock_ib_contract.multiplier = "100"
        mock_ib_contract.primaryExchange = "NASDAQ"

        instrument = normalize_ib_contract_to_broker_instrument(mock_ib_contract)
        broker_pb.BrokerInstrument.assert_called_once_with(
            symbol="AAPL", sec_type="STK", exchange="SMART", currency="USD",
            con_id=12345, last_trade_date_or_contract_month="20240119",
            strike=150.0, right="C", multiplier="100", primary_exchange="NASDAQ"
        )
        self.assertEqual(instrument, broker_pb.BrokerInstrument.return_value)

    def test_normalize_ib_contract_to_broker_instrument_minimal(self):
        mock_ib_contract = MagicMock(spec=['symbol', 'secType']) # Only these attrs exist
        mock_ib_contract.symbol = "EUR"
        mock_ib_contract.secType = "CASH"

        instrument = normalize_ib_contract_to_broker_instrument(mock_ib_contract)
        broker_pb.BrokerInstrument.assert_called_once_with(
            symbol="EUR", sec_type="CASH", exchange="", currency="",
            con_id=0, last_trade_date_or_contract_month="",
            strike=0.0, right="", multiplier="", primary_exchange=""
        )


class TestResponseProcessor(unittest.TestCase):

    def setUp(self):
        self.mock_wrapper = MagicMock(name="IBWrapperImplMock")
        self.mock_kafka_producer = MagicMock(name="BrokerEventProducerMock")
        self.mock_kafka_cfg = MagicMock(spec=KafkaConfig)
        self.mock_kafka_cfg.order_updates_topic = "test.orders"
        self.mock_kafka_cfg.execution_reports_topic = "test.execs"
        self.mock_kafka_cfg.position_data_topic = "test.positions"
        self.mock_kafka_cfg.account_data_topic = "test.accounts"
        self.mock_kafka_cfg.error_events_topic = "test.errors"
        self.mock_order_id_mapper = MagicMock(name="OrderIdMapperMock")
        self.service_instance_id = "test_instance_01"

        # Initialize queues on the mock_wrapper
        self.mock_wrapper.order_status_queue = []
        self.mock_wrapper.exec_details_queue = []
        self.mock_wrapper.portfolio_updates_queue = []
        self.mock_wrapper.streaming_account_value_queue = []
        self.mock_wrapper.error_messages_queue = []
        self.mock_wrapper.commission_reports_cache = {}
        self.mock_wrapper.commission_reports_cache_lock = MagicMock(spec=threading.Lock)

        # Mock conn_manager and its config if accessed (e.g. for account_code)
        self.mock_wrapper.conn_manager = MagicMock()
        self.mock_wrapper.conn_manager.config = MagicMock(account_code="U123")


        self.processor = ResponseProcessor(
            wrapper=self.mock_wrapper,
            kafka_producer=self.mock_kafka_producer,
            kafka_cfg=self.mock_kafka_cfg,
            order_id_mapper=self.mock_order_id_mapper,
            service_instance_id=self.service_instance_id
        )
        # Patch _get_proto_timestamp for predictable timestamps in events
        self.mock_proto_ts_patcher = patch('ibkr_gateway_service.response_processor._get_proto_timestamp')
        self.mock_get_proto_timestamp = self.mock_proto_ts_patcher.start()
        self.mock_get_proto_timestamp.return_value = ProtoTimestamp(seconds=1678886400, nanos=0)


    def tearDown(self):
        self.mock_proto_ts_patcher.stop()

    # 1. Initialization
    def test_init(self):
        self.assertEqual(self.processor.wrapper, self.mock_wrapper)
        self.assertEqual(self.processor.kafka_producer, self.mock_kafka_producer)
        self.assertEqual(self.processor.kafka_cfg, self.mock_kafka_cfg)
        self.assertEqual(self.processor.order_id_mapper, self.mock_order_id_mapper)
        self.assertEqual(self.processor.service_instance_id, self.service_instance_id)
        self.assertIsInstance(self.processor._stop_event, threading.Event)
        self.assertIsNone(self.processor._thread)
        self.assertEqual(self.processor.consecutive_processing_errors, 0) # From enhanced error handling

    # 2. Queue Processing Methods
    def test_process_order_status_queue_success(self):
        status_data = {"orderId": 101, "permId": 12345, "status": "Filled", "filled": 10.0,
                       "remaining": 0.0, "avgFillPrice": 150.0, "lastFillPrice": 150.1,
                       "clientId": 1, "whyHeld": "", "mktCapPrice": 0.0, "timestamp": time.time()}
        self.mock_wrapper.order_status_queue.append(status_data)
        self.mock_order_id_mapper.get_internal_id.return_value = "platform_order_A"

        self.processor._process_order_status_queue()

        self.assertEqual(len(self.mock_wrapper.order_status_queue), 0)
        self.mock_order_id_mapper.get_internal_id.assert_called_once_with(101)
        broker_pb.OrderStatusEvent.assert_called_once_with(
            platform_order_id="platform_order_A", broker_order_id=101, perm_id=12345,
            status="Filled", filled_quantity=10.0, remaining_quantity=0.0,
            average_fill_price=150.0, last_fill_price=150.1, client_id=1, why_held="",
            mkt_cap_price=0.0, event_timestamp_utc=self.mock_get_proto_timestamp.return_value,
            ib_account_id="U123"
        )
        self.mock_kafka_producer.publish_message.assert_called_once_with(
            broker_pb.OrderStatusEvent.return_value, "101", "test.orders"
        )

    def test_process_order_status_no_platform_id(self):
        status_data = {"orderId": 102, "status": "Submitted", "timestamp": time.time()}
        self.mock_wrapper.order_status_queue.append(status_data)
        self.mock_order_id_mapper.get_internal_id.return_value = None # Simulate no mapping

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.response_processor'), level='DEBUG') as log_cm:
            self.processor._process_order_status_queue()

        # Check that it still publishes with a placeholder ID
        broker_pb.OrderStatusEvent.assert_called_once()
        self.mock_kafka_producer.publish_message.assert_called_once()
        args, _ = broker_pb.OrderStatusEvent.call_args
        self.assertEqual(args[0].platform_order_id, "UNMAPPED_IB_102")


    def test_process_exec_details_queue_success_no_commission(self):
        mock_contract = MagicMock(symbol="TSLA", currency="USD")
        mock_execution = MagicMock(orderId=201, execId="exec001", permId=54321, side="BOT", shares=5.0,
                                   price=300.0, time="20230315  10:00:00", exchange="NASDAQ",
                                   acctNumber="U123", avgPrice=300.0, cumQty=5.0)
        exec_item = {"contract": mock_contract, "execution": mock_execution, "received_at": time.time()}
        self.mock_wrapper.exec_details_queue.append(exec_item)
        self.mock_order_id_mapper.get_internal_id.return_value = "platform_order_B"

        # Simulate commission cache miss
        self.mock_wrapper.commission_reports_cache = {}

        with patch('ibkr_gateway_service.response_processor.normalize_ib_contract_to_broker_instrument') as mock_normalize:
            mock_normalized_instrument = broker_pb.BrokerInstrument.return_value
            mock_normalize.return_value = mock_normalized_instrument

            self.processor._process_exec_details_queue()

            self.assertEqual(len(self.mock_wrapper.exec_details_queue), 0)
            mock_normalize.assert_called_once_with(mock_contract)
            broker_pb.ExecutionReportEvent.assert_called_once_with(
                platform_order_id="platform_order_B", broker_order_id=201, execution_id="exec001",
                perm_id=54321, instrument=mock_normalized_instrument, side="BOT",
                filled_quantity=5.0, fill_price=300.0, execution_time_str="20230315  10:00:00",
                executing_exchange="NASDAQ", currency="USD",
                commission_data=broker_pb.CommissionReportData.return_value, # Empty default
                event_timestamp_utc=self.mock_get_proto_timestamp.return_value,
                ib_account_id="U123", average_price=300.0, cumulative_quantity=5.0
            )
            broker_pb.CommissionReportData.assert_called_once_with() # Called for empty default
            self.mock_kafka_producer.publish_message.assert_called_once_with(
                broker_pb.ExecutionReportEvent.return_value, "exec001", "test.execs"
            )

    def test_process_exec_details_queue_with_commission(self):
        mock_contract = MagicMock(symbol="MSFT", currency="USD")
        mock_execution = MagicMock(orderId=202, execId="exec002", permId=54322, side="SLD", shares=2.0,
                                   price=400.0, time="20230315  11:00:00", exchange="SMART",
                                   acctNumber="U123", avgPrice=400.0, cumQty=2.0)
        exec_item = {"contract": mock_contract, "execution": mock_execution, "received_at": time.time()}
        self.mock_wrapper.exec_details_queue.append(exec_item)
        self.mock_order_id_mapper.get_internal_id.return_value = "platform_order_C"

        mock_commission_report = MagicMock(execId="exec002", commission=1.50, currency="USD", realizedPNL=50.0)
        setattr(mock_commission_report, 'yield', 0.0) # Ensure 'yield' attribute exists
        setattr(mock_commission_report, 'yieldRedemptionDate', 0)

        self.mock_wrapper.commission_reports_cache = {"exec002": mock_commission_report}

        with patch('ibkr_gateway_service.response_processor.normalize_ib_contract_to_broker_instrument') as mock_normalize:
            self.processor._process_exec_details_queue()

        broker_pb.CommissionReportData.assert_called_with(
            execution_id="exec002", commission=1.50, currency="USD", realized_pnl=50.0,
            yield_val=0.0, yield_redemption_date=0
        )
        self.mock_kafka_producer.publish_message.assert_called_once()
        # Ensure cache was cleared for this execId
        self.assertNotIn("exec002", self.mock_wrapper.commission_reports_cache)


    def test_process_portfolio_updates_queue(self):
        mock_contract = MagicMock(symbol="GOOG") # Will be passed to normalize
        portfolio_data = {"accountName": "U123", "contract_object": mock_contract, "position": 10.0,
                          "marketPrice": 2000.0, "marketValue": 20000.0, "averageCost": 1900.0,
                          "unrealizedPNL": 1000.0, "realizedPNL": 0.0, "timestamp": time.time()}
        self.mock_wrapper.portfolio_updates_queue.append(portfolio_data)

        with patch('ibkr_gateway_service.response_processor.normalize_ib_contract_to_broker_instrument') as mock_normalize:
            mock_normalized_instrument = broker_pb.BrokerInstrument.return_value
            mock_normalized_instrument.symbol = "GOOG" # For key generation
            mock_normalized_instrument.con_id = 0 # For key generation
            mock_normalize.return_value = mock_normalized_instrument

            self.processor._process_portfolio_updates_queue()

            self.assertEqual(len(self.mock_wrapper.portfolio_updates_queue), 0)
            broker_pb.PortfolioUpdateEvent.assert_called_once_with(
                ib_account_id="U123", instrument=mock_normalized_instrument, position=10.0,
                market_price=2000.0, market_value=20000.0, average_cost=1900.0,
                unrealized_pnl=1000.0, realized_pnl=0.0,
                event_timestamp_utc=self.mock_get_proto_timestamp.return_value
            )
            self.mock_kafka_producer.publish_message.assert_called_once_with(
                broker_pb.PortfolioUpdateEvent.return_value, "U123:GOOG", "test.positions"
            )

    def test_process_streaming_account_values_queue_updateAccountValue(self):
        item = {"type": "AccountValueUpdate", "accountName": "U123", "key": "NetLiquidation",
                "val": "500000", "currency": "USD", "timestamp": time.time()}
        self.mock_wrapper.streaming_account_value_queue.append(item)
        self.processor._process_streaming_account_values_queue()
        broker_pb.AccountValueUpdateEvent.assert_called_once_with(
            account_id="U123", key="NetLiquidation", value="500000", currency="USD",
            event_timestamp_utc=self.mock_get_proto_timestamp.return_value
        )
        self.mock_kafka_producer.publish_message.assert_called_once_with(
            broker_pb.AccountValueUpdateEvent.return_value, "U123:NetLiquidation", "test.accounts"
        )

    def test_process_streaming_account_values_queue_accountSummaryStream(self):
        item = {"type": "AccountSummaryStream", "account": "U123", "tag": "BuyingPower",
                "value": "250000", "currency": "USD", "timestamp": time.time()}
        self.mock_wrapper.streaming_account_value_queue.append(item)
        self.processor._process_streaming_account_values_queue()
        broker_pb.AccountValueUpdateEvent.assert_called_once_with(
            account_id="U123", key="BuyingPower", value="250000", currency="USD",
            event_timestamp_utc=self.mock_get_proto_timestamp.return_value
        )
        self.mock_kafka_producer.publish_message.assert_called_once_with(
            broker_pb.AccountValueUpdateEvent.return_value, "U123:BuyingPower", "test.accounts"
        )

    def test_process_error_messages_queue(self):
        error_data = {"reqId": -1, "errorCode": 502, "errorString": "Connectivity error",
                      "advancedOrderRejectJson": "", "timestamp": time.time()}
        self.mock_wrapper.error_messages_queue.append(error_data)

        # Mock conn_manager on wrapper for source_client_id
        self.mock_wrapper.conn_manager.config.client_id = 777

        self.processor._process_error_messages_queue()
        broker_pb.BrokerErrorEvent.assert_called_once_with(
            request_id=-1, error_code=502, error_message="Connectivity error",
            advanced_order_reject_json="",
            event_timestamp_utc=self.mock_get_proto_timestamp.return_value,
            source_client_id="777"
        )
        self.mock_kafka_producer.publish_message.assert_called_once_with(
            broker_pb.BrokerErrorEvent.return_value, "502", "test.errors"
        )

    # 3. _run_processor_loop tests
    @patch.object(ResponseProcessor, '_process_order_status_queue')
    @patch.object(ResponseProcessor, '_process_exec_details_queue')
    # Add patches for other process_..._queue methods
    def test_run_processor_loop_calls_processors_and_stops(self, mock_proc_exec, mock_proc_status):
        self.processor._stop_event.is_set.side_effect = [False, False, True] # Run loop twice

        # Simulate queues having data to reset error counter
        self.mock_wrapper.order_status_queue = [MagicMock()]

        self.processor._run_processor_loop()

        self.assertGreaterEqual(mock_proc_status.call_count, 1)
        self.assertGreaterEqual(mock_proc_exec.call_count, 1)
        self.assertEqual(self.processor.consecutive_processing_errors, 0)


    @patch.object(ResponseProcessor, '_process_order_status_queue', side_effect=Exception("Test processing error"))
    def test_run_processor_loop_error_handling_and_alert(self, mock_proc_status_error):
        self.processor._stop_event.is_set.side_effect = [False] * (self.processor.PROCESSING_ERROR_THRESHOLD + 2) + [True]
        self.processor.PROCESSING_ERROR_THRESHOLD = 2 # Lower for test

        with self.assertLogs(logging.getLogger('ibkr_gateway_service.response_processor'), level='CRITICAL') as log_cm:
            with patch('time.sleep'): # Mock time.sleep to speed up test
                 self.processor._run_processor_loop()

        self.assertGreater(self.processor.consecutive_processing_errors, self.processor.PROCESSING_ERROR_THRESHOLD)
        self.assertTrue(any("CRITICAL_ALERT: ResponseProcessor" in rec.getMessage() for rec in log_cm.records))


    # 4. Start and Stop methods
    @patch('threading.Thread')
    def test_start_method(self, MockThread):
        self.processor.start()
        self.assertFalse(self.processor._stop_event.is_set())
        MockThread.assert_called_once_with(target=self.processor._run_processor_loop, name="IBResponseProcLoop", daemon=True)
        self.processor._thread.start.assert_called_once()

    def test_stop_method(self):
        self.processor._thread = MagicMock(spec=threading.Thread)
        self.processor._thread.is_alive.return_value = True

        self.processor.stop()

        self.assertTrue(self.processor._stop_event.is_set())
        self.processor._thread.join.assert_called_with(timeout=10)
        self.mock_kafka_producer.flush.assert_called_once()


if __name__ == '__main__':
    unittest.main()
