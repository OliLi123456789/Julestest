import logging
import threading # Keep threading for lock if fallback to in-memory is used.
from typing import Dict, Optional, List, Tuple # List and Tuple for get_all_mappings_tuples
try:
    import redis # type: ignore
except ImportError:
    redis = None # type: ignore

logger = logging.getLogger(__name__)

class OrderIdMapper:
    """
    Manages mappings between platform-internal order IDs and IBKR broker order IDs.
    Uses Redis for persistent storage if a Redis client is provided, otherwise
    falls back to in-memory dictionaries (for testing or non-HA setups).
    """
    MAP_IB_TO_PLATFORM_HASH = "ordermap:ib_to_plat"
    MAP_PLATFORM_TO_IB_HASH = "ordermap:plat_to_ib"

    def __init__(self, redis_client: Optional['redis.Redis'] = None): # type: ignore
        self._redis_client = redis_client
        self._lock = threading.Lock() # Still useful for in-memory fallback operations

        if self._redis_client:
            logger.info("OrderIdMapper is using Redis for persistent storage.")
            # Test connection or check client status if possible/needed
            try:
                # Assuming redis_client is configured with decode_responses=True later
                # For now, ping might return bytes. This is just a basic check.
                if self._redis_client.ping():
                    logger.info("Successfully pinged Redis server.")
                else:
                    logger.warning("Redis server ping failed. Check connection and configuration.")
            except Exception as e: # Catch if Redis is down during init
                logger.error(f"Error connecting to Redis during OrderIdMapper init: {e}. Falling back to in-memory.")
                self._redis_client = None # Force fallback

        if not self._redis_client: # Fallback to in-memory if not provided or connection failed
            self._ib_to_platform_map: Dict[int, str] = {}
            self._platform_to_ib_map: Dict[str, int] = {}
            logger.warning(
                "OrderIdMapper: Redis client not available or connection failed. "
                "Using in-memory storage. Mappings will be lost on restart. "
                "This is NOT suitable for production HA setups."
            )

    def add_mapping(self, ib_order_id: int, platform_order_id: str):
        ib_order_id_str = str(ib_order_id)
        if self._redis_client:
            try:
                # Note: Assuming redis_client is set up with decode_responses=True in main.py
                # If not, .decode('utf-8') would be needed for results from hget.
                existing_platform_id = self._redis_client.hget(self.MAP_IB_TO_PLATFORM_HASH, ib_order_id_str)
                if existing_platform_id and existing_platform_id != platform_order_id:
                    logger.error(f"Conflict (Redis): IBKR Order ID {ib_order_id_str} already mapped to platform ID '{existing_platform_id}'. Cannot remap to '{platform_order_id}'.")
                    return

                existing_ib_id_str = self._redis_client.hget(self.MAP_PLATFORM_TO_IB_HASH, platform_order_id)
                if existing_ib_id_str and existing_ib_id_str != ib_order_id_str:
                    logger.error(f"Conflict (Redis): Platform Order ID '{platform_order_id}' already mapped to IBKR ID {existing_ib_id_str}. Cannot remap to {ib_order_id_str}.")
                    return

                pipeline = self._redis_client.pipeline()
                pipeline.hset(self.MAP_IB_TO_PLATFORM_HASH, ib_order_id_str, platform_order_id)
                pipeline.hset(self.MAP_PLATFORM_TO_IB_HASH, platform_order_id, ib_order_id_str)
                pipeline.execute()
                logger.debug(f"Added mapping (Redis): IB ID {ib_order_id_str} <-> Platform ID '{platform_order_id}'")
            except Exception as e: # Catch Redis specific errors if preferred
                logger.error(f"Redis error adding mapping for IB ID {ib_order_id_str} <-> '{platform_order_id}': {e}")
        else: # In-memory fallback
            with self._lock:
                if ib_order_id in self._ib_to_platform_map and \
                   self._ib_to_platform_map[ib_order_id] != platform_order_id:
                    logger.error(
                        f"Conflict (In-Memory): IBKR Order ID {ib_order_id} already mapped to platform ID "
                        f"'{self._ib_to_platform_map[ib_order_id]}'. Cannot remap to '{platform_order_id}'."
                    )
                    return
                if platform_order_id in self._platform_to_ib_map and \
                   self._platform_to_ib_map[platform_order_id] != ib_order_id:
                    logger.error(
                        f"Conflict (In-Memory): Platform Order ID '{platform_order_id}' already mapped to IBKR ID "
                        f"{self._platform_to_ib_map[platform_order_id]}. Cannot remap to {ib_order_id}."
                    )
                    return
                self._ib_to_platform_map[ib_order_id] = platform_order_id
                self._platform_to_ib_map[platform_order_id] = ib_order_id
            logger.debug(f"Added mapping (in-memory): IB ID {ib_order_id} <-> Platform ID '{platform_order_id}'")

    def get_platform_id(self, ib_order_id: int) -> Optional[str]:
        ib_order_id_str = str(ib_order_id)
        platform_id: Optional[str] = None
        if self._redis_client:
            try:
                platform_id = self._redis_client.hget(self.MAP_IB_TO_PLATFORM_HASH, ib_order_id_str)
            except Exception as e:
                logger.error(f"Redis error getting platform ID for IB ID {ib_order_id_str}: {e}")
                return None
        else: # In-memory fallback
            with self._lock:
                platform_id = self._ib_to_platform_map.get(ib_order_id)

        # Common logging for both paths
        if platform_id:
            logger.debug(f"Retrieved Platform ID '{platform_id}' for IB ID {ib_order_id_str}")
        else:
            # This is a normal occurrence if an ID hasn't been mapped or was removed.
            logger.debug(f"No Platform ID found for IB ID {ib_order_id_str}")
        return platform_id

    def get_ib_id(self, platform_order_id: str) -> Optional[int]:
        ib_id_str: Optional[str] = None
        if self._redis_client:
            try:
                ib_id_str = self._redis_client.hget(self.MAP_PLATFORM_TO_IB_HASH, platform_order_id)
            except Exception as e:
                logger.error(f"Redis error getting IB ID for Platform ID '{platform_order_id}': {e}")
                return None
        else: # In-memory fallback
            with self._lock:
                ib_id_val = self._platform_to_ib_map.get(platform_order_id)
            if ib_id_val is not None:
                ib_id_str = str(ib_id_val)

        if ib_id_str:
            logger.debug(f"Retrieved IB ID {ib_id_str} for Platform ID '{platform_order_id}'")
            try:
                return int(ib_id_str)
            except ValueError:
                logger.error(f"Corrupted IB ID in storage for Platform ID '{platform_order_id}': '{ib_id_str}' is not an int.")
                return None
        else:
            logger.debug(f"No IB ID found for Platform ID '{platform_order_id}'")
            return None

    def remove_mapping_by_ib_id(self, ib_order_id: int):
        ib_order_id_str = str(ib_order_id)
        # Retrieve platform_order_id first to remove the reverse mapping
        # This uses the already defined get_platform_id which handles Redis/in-memory.
        platform_order_id = self.get_platform_id(ib_order_id)

        if platform_order_id: # If mapping exists
            if self._redis_client:
                try:
                    pipeline = self._redis_client.pipeline()
                    pipeline.hdel(self.MAP_IB_TO_PLATFORM_HASH, ib_order_id_str)
                    pipeline.hdel(self.MAP_PLATFORM_TO_IB_HASH, platform_order_id)
                    pipeline.execute()
                    logger.info(f"Removed mapping (Redis) for IB ID {ib_order_id_str} (was Platform ID '{platform_order_id}')")
                except Exception as e:
                    logger.error(f"Redis error removing mapping for IB ID {ib_order_id_str}: {e}")
            else: # In-memory fallback
                with self._lock:
                    self._ib_to_platform_map.pop(ib_order_id, None)
                    self._platform_to_ib_map.pop(platform_order_id, None)
                logger.info(f"Removed mapping (in-memory) for IB ID {ib_order_id} (was Platform ID '{platform_order_id}')")
        else:
            logger.warning(f"Attempted to remove mapping for non-existent IB ID {ib_order_id_str}")

    def remove_mapping_by_platform_id(self, platform_order_id: str):
        ib_id = self.get_ib_id(platform_order_id) # Uses the updated get_ib_id

        if ib_id is not None:
            ib_order_id_str = str(ib_id)
            if self._redis_client:
                try:
                    pipeline = self._redis_client.pipeline()
                    pipeline.hdel(self.MAP_PLATFORM_TO_IB_HASH, platform_order_id)
                    pipeline.hdel(self.MAP_IB_TO_PLATFORM_HASH, ib_order_id_str)
                    pipeline.execute()
                    logger.info(f"Removed mapping (Redis) for Platform ID '{platform_order_id}' (was IB ID {ib_order_id_str})")
                except Exception as e:
                    logger.error(f"Redis error removing mapping for Platform ID '{platform_order_id}': {e}")
            else: # In-memory fallback
                with self._lock:
                    self._platform_to_ib_map.pop(platform_order_id, None)
                    self._ib_to_platform_map.pop(ib_id, None) # ib_id is already int here
                logger.info(f"Removed mapping (in-memory) for Platform ID '{platform_order_id}' (was IB ID {ib_id})")
        else:
            logger.warning(f"Attempted to remove mapping for non-existent Platform ID '{platform_order_id}'")

    def get_all_ib_to_platform_mappings(self) -> Dict[int, str]:
        if self._redis_client:
            try:
                # Assumes redis_client is configured with decode_responses=True
                raw_map = self._redis_client.hgetall(self.MAP_IB_TO_PLATFORM_HASH)
                # Ensure keys are integers
                return {int(k): v for k, v in raw_map.items()}
            except Exception as e:
                logger.error(f"Redis error getting all IB to Platform mappings: {e}")
                return {} # Return empty on error
        else: # In-memory fallback
            with self._lock:
                return dict(self._ib_to_platform_map)

    def get_all_platform_to_ib_mappings(self) -> Dict[str, int]:
        if self._redis_client:
            try:
                raw_map = self._redis_client.hgetall(self.MAP_PLATFORM_TO_IB_HASH)
                # Ensure values are integers
                return {k: int(v) for k, v in raw_map.items()}
            except Exception as e:
                logger.error(f"Redis error getting all Platform to IB mappings: {e}")
                return {}
        else: # In-memory fallback
            with self._lock:
                return dict(self._platform_to_ib_map)

    def get_all_mappings_tuples(self) -> List[Tuple[int, str]]:
        """Returns a list of (ib_order_id, platform_order_id) tuples."""
        # This method reconstructs from one of the Redis hashes.
        if self._redis_client:
            try:
                raw_map = self._redis_client.hgetall(self.MAP_IB_TO_PLATFORM_HASH)
                return [(int(k), v) for k, v in raw_map.items()]
            except Exception as e:
                logger.error(f"Redis error getting all mappings as tuples: {e}")
                return []
        else: # In-memory fallback
            with self._lock:
                return list(self._ib_to_platform_map.items())

if __name__ == '__main__':
    # Example Usage - This example will only test in-memory mode unless a Redis instance is running and configured.
    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # To test with Redis, you'd need to initialize a Redis client here:
    # import redis as redis_lib
    # test_redis_client = redis_lib.Redis(host='localhost', port=6379, db=0, decode_responses=True)
    # try:
    #     test_redis_client.ping()
    #     logger.info("Test Redis client connected.")
    # except redis_lib.exceptions.ConnectionError as e:
    #     logger.error(f"Test Redis client connection failed: {e}. Running in-memory tests only.")
    #     test_redis_client = None
    # mapper = OrderIdMapper(redis_client=test_redis_client)

    mapper = OrderIdMapper() # Defaults to in-memory for this example run

    mapper.add_mapping(ib_order_id=101, platform_order_id="platform_abc_123")
    mapper.add_mapping(ib_order_id=102, platform_order_id="platform_xyz_789")

    print(f"Platform ID for IB 101: {mapper.get_platform_id(101)}") # Expected: platform_abc_123
    print(f"IB ID for platform_xyz_789: {mapper.get_ib_id('platform_xyz_789')}") # Expected: 102

    # Test conflict logging (won't overwrite due to return statements in add_mapping for conflicts)
    logger.info("Testing conflicting mappings (should log errors):")
    mapper.add_mapping(101, "platform_def_456") # Conflict with IB ID 101
    mapper.add_mapping(103, "platform_abc_123") # Conflict with Platform ID platform_abc_123

    # Verify original mappings are still there if conflicts were correctly handled (not overwritten)
    print(f"Platform ID for IB 101 after conflict test: {mapper.get_platform_id(101)}") # Expected: platform_abc_123
    print(f"IB ID for platform_abc_123 after conflict test: {mapper.get_ib_id('platform_abc_123')}") # Expected: 101


    mapper.remove_mapping_by_platform_id("platform_xyz_789")
    print(f"After removal of 'platform_xyz_789':")
    print(f"  Platform ID for IB 102: {mapper.get_platform_id(102)}") # Expected: None
    print(f"  IB ID for platform_xyz_789: {mapper.get_ib_id('platform_xyz_789')}") # Expected: None

    # Add it back for further tests
    mapper.add_mapping(ib_order_id=102, platform_order_id="platform_xyz_789")
    print(f"Platform ID for IB 102 after re-adding: {mapper.get_platform_id(102)}")


    mapper.remove_mapping_by_ib_id(101)
    print(f"After removal of IB ID 101:")
    print(f"  Platform ID for IB 101: {mapper.get_platform_id(101)}") # Expected: None
    print(f"  IB ID for platform_abc_123: {mapper.get_ib_id('platform_abc_123')}") # Expected: None


    print(f"All IB->Platform: {mapper.get_all_ib_to_platform_mappings()}")
    print(f"All Platform->IB: {mapper.get_all_platform_to_ib_mappings()}")
    print(f"All Tuples: {mapper.get_all_mappings_tuples()}")
