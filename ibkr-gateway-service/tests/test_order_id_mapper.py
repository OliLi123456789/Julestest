import unittest
from unittest.mock import MagicMock, patch
import logging

# Assuming OrderIdMapper is in the parent directory or PYTHONPATH is set up correctly
# For a typical project structure, it might be:
# from ibkr_gateway_service.order_id_mapper import OrderIdMapper
# For this environment, let's assume it's importable directly if files are in the same service root
from ibkr_gateway_service.order_id_mapper import OrderIdMapper

# Mock redis module if it's not installed in the test environment,
# or to ensure we are always using our mock.
try:
    import redis
except ImportError:
    redis = None # Will be mocked later where needed

class TestOrderIdMapper(unittest.TestCase):

    def setUp(self):
        # Suppress the specific warning about in-memory storage during tests unless testing for it.
        # Or, use self.assertLogs for specific tests.
        # For now, let's allow warnings to be emitted and test for them explicitly.
        # logging.disable(logging.WARNING)
        self.logger = logging.getLogger('ibkr_gateway_service.order_id_mapper') # Get the specific logger

    def tearDown(self):
        # logging.disable(logging.NOTSET)
        pass

    # 1. Initialization Tests
    def test_init_no_redis_client(self):
        with self.assertLogs(self.logger, level='WARNING') as log_capture:
            mapper = OrderIdMapper(redis_client=None)
            self.assertIsNone(mapper._redis_client)
            self.assertTrue(hasattr(mapper, '_ib_to_platform_map')) # Check if in-memory dicts exist
            self.assertTrue(hasattr(mapper, '_platform_to_ib_map'))

        self.assertTrue(any("Redis client not available" in record.getMessage() for record in log_capture.records))

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True) # Ensure redis is mocked if not installed
    def test_init_with_mock_redis_client_success(self, mock_redis_module):
        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True

        # If OrderIdMapper directly instantiates redis.Redis, we need to mock that.
        # But it takes redis_client as an arg, so we pass our mock.
        mapper = OrderIdMapper(redis_client=mock_redis_client)

        self.assertEqual(mapper._redis_client, mock_redis_client)
        mock_redis_client.ping.assert_called_once()
        self.assertFalse(hasattr(mapper, '_ib_to_platform_map')) # In-memory dicts should not exist

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_init_with_mock_redis_client_ping_fails(self, mock_redis_module):
        mock_redis_client = MagicMock()
        mock_redis_client.ping.side_effect = Exception("Redis connection failed") # Simulate redis.exceptions.ConnectionError

        with self.assertLogs(self.logger, level='ERROR') as log_error_capture:
            with self.assertLogs(self.logger, level='WARNING') as log_warning_capture:
                mapper = OrderIdMapper(redis_client=mock_redis_client)

        self.assertIsNone(mapper._redis_client) # Should fall back to None
        mock_redis_client.ping.assert_called_once()
        self.assertTrue(hasattr(mapper, '_ib_to_platform_map')) # Should fall back to in-memory
        self.assertTrue(hasattr(mapper, '_platform_to_ib_map'))

        self.assertTrue(any("Error connecting to Redis" in record.getMessage() for record in log_error_capture.records))
        self.assertTrue(any("Falling back to in-memory" in record.getMessage() for record in log_error_capture.records)) # from error log
        self.assertTrue(any("Redis client not available" in record.getMessage() for record in log_warning_capture.records)) # from final warning

    # 2. In-Memory Mode Tests
    def test_add_mapping_in_memory(self):
        mapper = OrderIdMapper(redis_client=None) # Force in-memory
        mapper.add_mapping(101, "platform_A")
        self.assertEqual(mapper._ib_to_platform_map[101], "platform_A")
        self.assertEqual(mapper._platform_to_ib_map["platform_A"], 101)

    def test_add_mapping_conflict_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")

        with self.assertLogs(self.logger, level='ERROR') as log_capture:
            mapper.add_mapping(101, "platform_B") # Conflict: IB ID 101 already mapped
        self.assertEqual(mapper._ib_to_platform_map[101], "platform_A") # Original should be preserved
        self.assertTrue(any("Conflict (In-Memory): IBKR Order ID 101 already mapped" in record.getMessage() for record in log_capture.records))

        with self.assertLogs(self.logger, level='ERROR') as log_capture:
            mapper.add_mapping(102, "platform_A") # Conflict: Platform ID "platform_A" already mapped
        self.assertEqual(mapper._platform_to_ib_map["platform_A"], 101) # Original should be preserved
        self.assertTrue(any("Conflict (In-Memory): Platform Order ID 'platform_A' already mapped" in record.getMessage() for record in log_capture.records))

    def test_get_platform_id_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")
        self.assertEqual(mapper.get_platform_id(101), "platform_A")
        self.assertIsNone(mapper.get_platform_id(102))

    def test_get_ib_id_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")
        self.assertEqual(mapper.get_ib_id("platform_A"), 101)
        self.assertIsNone(mapper.get_ib_id("platform_B"))

    def test_remove_mapping_by_ib_id_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")
        mapper.remove_mapping_by_ib_id(101)
        self.assertNotIn(101, mapper._ib_to_platform_map)
        self.assertNotIn("platform_A", mapper._platform_to_ib_map)
        mapper.remove_mapping_by_ib_id(102) # Test removing non-existent

    def test_remove_mapping_by_platform_id_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")
        mapper.remove_mapping_by_platform_id("platform_A")
        self.assertNotIn(101, mapper._ib_to_platform_map)
        self.assertNotIn("platform_A", mapper._platform_to_ib_map)
        mapper.remove_mapping_by_platform_id("platform_B") # Test removing non-existent

    def test_get_all_mappings_in_memory(self):
        mapper = OrderIdMapper(redis_client=None)
        mapper.add_mapping(101, "platform_A")
        mapper.add_mapping(102, "platform_B")
        self.assertEqual(mapper.get_all_ib_to_platform_mappings(), {101: "platform_A", 102: "platform_B"})
        self.assertEqual(mapper.get_all_platform_to_ib_mappings(), {"platform_A": 101, "platform_B": 102})
        self.assertCountEqual(mapper.get_all_mappings_tuples(), [(101, "platform_A"), (102, "platform_B")])


    # 3. Redis Mode Tests
    def _get_mocked_redis_mapper(self):
        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        # Simulate decode_responses=True by having mocks return strings
        mock_redis_client.hget.return_value = None # Default for hget

        # Setup pipeline mock
        mock_pipeline = MagicMock()
        mock_redis_client.pipeline.return_value = mock_pipeline
        mock_pipeline.hset.return_value = mock_pipeline # for chaining
        mock_pipeline.hdel.return_value = mock_pipeline # for chaining

        mapper = OrderIdMapper(redis_client=mock_redis_client)
        self.assertEqual(mapper._redis_client, mock_redis_client) # Ensure Redis mode
        return mapper, mock_redis_client, mock_pipeline

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_add_mapping_redis(self, mock_redis_module):
        mapper, mock_redis, mock_pipeline = self._get_mocked_redis_mapper()

        # Simulate no existing conflicting mappings
        mock_redis.hget.side_effect = [None, None] # First for ib_to_plat, second for plat_to_ib check

        mapper.add_mapping(101, "platform_A")

        mock_redis.pipeline.assert_called_once()
        mock_pipeline.hset.assert_any_call(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH, "101", "platform_A")
        mock_pipeline.hset.assert_any_call(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH, "platform_A", "101")
        mock_pipeline.execute.assert_called_once()

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_add_mapping_redis_conflict_ib_id(self, mock_redis_module):
        mapper, mock_redis, mock_pipeline = self._get_mocked_redis_mapper()

        # Simulate IB ID 101 already mapped to "platform_X"
        mock_redis.hget.side_effect = ["platform_X", None]

        with self.assertLogs(self.logger, level='ERROR') as log_capture:
            mapper.add_mapping(101, "platform_A")

        mock_pipeline.hset.assert_not_called() # Should not proceed to set
        self.assertTrue(any("Conflict (Redis): IBKR Order ID 101 already mapped" in record.getMessage() for record in log_capture.records))

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_add_mapping_redis_conflict_platform_id(self, mock_redis_module):
        mapper, mock_redis, mock_pipeline = self._get_mocked_redis_mapper()

        # Simulate "platform_A" already mapped to IB ID "999"
        mock_redis.hget.side_effect = [None, "999"]

        with self.assertLogs(self.logger, level='ERROR') as log_capture:
            mapper.add_mapping(101, "platform_A")

        mock_pipeline.hset.assert_not_called()
        self.assertTrue(any("Conflict (Redis): Platform Order ID 'platform_A' already mapped" in record.getMessage() for record in log_capture.records))


    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_get_platform_id_redis(self, mock_redis_module):
        mapper, mock_redis, _ = self._get_mocked_redis_mapper()
        mock_redis.hget.return_value = "platform_A" # Assume decode_responses=True

        self.assertEqual(mapper.get_platform_id(101), "platform_A")
        mock_redis.hget.assert_called_once_with(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH, "101")

        mock_redis.hget.return_value = None
        self.assertIsNone(mapper.get_platform_id(102))

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_get_ib_id_redis(self, mock_redis_module):
        mapper, mock_redis, _ = self._get_mocked_redis_mapper()
        mock_redis.hget.return_value = "101" # Assume decode_responses=True

        self.assertEqual(mapper.get_ib_id("platform_A"), 101)
        mock_redis.hget.assert_called_once_with(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH, "platform_A")

        mock_redis.hget.return_value = None
        self.assertIsNone(mapper.get_ib_id("platform_B"))

        # Test corrupted data
        mock_redis.hget.return_value = "not_an_int"
        with self.assertLogs(self.logger, level='ERROR') as log_capture:
            self.assertIsNone(mapper.get_ib_id("platform_C"))
        self.assertTrue(any("Corrupted IB ID in storage" in record.getMessage() for record in log_capture.records))


    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_remove_mapping_by_ib_id_redis(self, mock_redis_module):
        mapper, mock_redis, mock_pipeline = self._get_mocked_redis_mapper()
        # get_platform_id will be called first
        mock_redis.hget.return_value = "platform_A"

        mapper.remove_mapping_by_ib_id(101)

        mock_redis.hget.assert_called_once_with(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH, "101")
        mock_redis.pipeline.assert_called_once()
        mock_pipeline.hdel.assert_any_call(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH, "101")
        mock_pipeline.hdel.assert_any_call(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH, "platform_A")
        mock_pipeline.execute.assert_called_once()

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_remove_mapping_by_platform_id_redis(self, mock_redis_module):
        mapper, mock_redis, mock_pipeline = self._get_mocked_redis_mapper()
        # get_ib_id will be called first
        mock_redis.hget.return_value = "101"

        mapper.remove_mapping_by_platform_id("platform_A")

        mock_redis.hget.assert_called_once_with(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH, "platform_A")
        mock_redis.pipeline.assert_called_once()
        mock_pipeline.hdel.assert_any_call(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH, "platform_A")
        mock_pipeline.hdel.assert_any_call(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH, "101")
        mock_pipeline.execute.assert_called_once()

    @patch('ibkr_gateway_service.order_id_mapper.redis', create=True)
    def test_get_all_mappings_redis(self, mock_redis_module):
        mapper, mock_redis, _ = self._get_mocked_redis_mapper()

        mock_redis.hgetall.return_value = {"101": "platform_A", "102": "platform_B"}
        self.assertEqual(mapper.get_all_ib_to_platform_mappings(), {101: "platform_A", 102: "platform_B"})
        mock_redis.hgetall.assert_called_once_with(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH)

        mock_redis.hgetall.reset_mock()
        mock_redis.hgetall.return_value = {"platform_A": "101", "platform_B": "102"}
        self.assertEqual(mapper.get_all_platform_to_ib_mappings(), {"platform_A": 101, "platform_B": 102})
        mock_redis.hgetall.assert_called_once_with(OrderIdMapper.MAP_PLATFORM_TO_IB_HASH)

        mock_redis.hgetall.reset_mock()
        mock_redis.hgetall.return_value = {"101": "platform_A", "102": "platform_B"} # For MAP_IB_TO_PLATFORM_HASH
        self.assertCountEqual(mapper.get_all_mappings_tuples(), [(101, "platform_A"), (102, "platform_B")])
        mock_redis.hgetall.assert_called_once_with(OrderIdMapper.MAP_IB_TO_PLATFORM_HASH)


if __name__ == '__main__':
    unittest.main()
