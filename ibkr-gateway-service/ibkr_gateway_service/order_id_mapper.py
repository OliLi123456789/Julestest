import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class OrderIdMapper:
    """
    Manages mappings between platform-internal order IDs and IBKR broker order IDs.

    NOTE: This is an in-memory implementation. For a production High Availability (HA) setup
    with multiple instances of IBKRGatewayService, this mapping needs to be stored
    in a shared, persistent store (e.g., Redis, or a database table) to ensure
    all instances have a consistent view, especially during failover or if different
    instances handle different orders for the same internal ID (though less likely).
    If only one instance is active at a time (active/passive HA), then this in-memory
    approach might be acceptable if state can be rebuilt on failover (e.g., by querying
    open orders and their states).
    """
    def __init__(self):
        self._ib_to_platform_map: Dict[int, str] = {} # Maps IBKR OrderID -> Platform OrderID
        self._platform_to_ib_map: Dict[str, int] = {} # Maps Platform OrderID -> IBKR OrderID
        self._lock = threading.Lock()
        logger.warning(
            "OrderIdMapper is using in-memory storage. "
            "This is NOT suitable for production HA setups with multiple active instances "
            "without an external persistent and shared store for these mappings."
        )

    def add_mapping(self, ib_order_id: int, platform_order_id: str):
        """
        Adds a mapping between an IBKR order ID and a platform order ID.
        Logs errors if a conflict is detected (e.g., one ID already mapped to another different ID).
        """
        with self._lock:
            # Check for IBKR ID conflict
            if ib_order_id in self._ib_to_platform_map and \
               self._ib_to_platform_map[ib_order_id] != platform_order_id:
                logger.error(
                    f"Conflict: IBKR Order ID {ib_order_id} already mapped to platform ID "
                    f"'{self._ib_to_platform_map[ib_order_id]}'. Cannot remap to '{platform_order_id}'."
                )
                # Depending on strategy, could raise an error or just log and not update.
                return # Or raise an exception

            # Check for Platform ID conflict
            if platform_order_id in self._platform_to_ib_map and \
               self._platform_to_ib_map[platform_order_id] != ib_order_id:
                logger.error(
                    f"Conflict: Platform Order ID '{platform_order_id}' already mapped to IBKR ID "
                    f"{self._platform_to_ib_map[platform_order_id]}. Cannot remap to {ib_order_id}."
                )
                return # Or raise an exception

            self._ib_to_platform_map[ib_order_id] = platform_order_id
            self._platform_to_ib_map[platform_order_id] = ib_order_id
            logger.debug(f"Added Order ID mapping: IBKR {ib_order_id} <-> Platform '{platform_order_id}'")

    def get_platform_id(self, ib_order_id: int) -> Optional[str]:
        """Retrieves the platform order ID given an IBKR order ID."""
        with self._lock:
            return self._ib_to_platform_map.get(ib_order_id)

    def get_ib_id(self, platform_order_id: str) -> Optional[int]:
        """Retrieves the IBKR order ID given a platform order ID."""
        with self._lock:
            return self._platform_to_ib_map.get(platform_order_id)

    def remove_mapping_by_ib_id(self, ib_order_id: int):
        """Removes mappings associated with an IBKR order ID."""
        with self._lock:
            platform_id = self._ib_to_platform_map.pop(ib_order_id, None)
            if platform_id:
                self._platform_to_ib_map.pop(platform_id, None)
                logger.debug(f"Removed Order ID mapping for IBKR ID: {ib_order_id}")

    def remove_mapping_by_platform_id(self, platform_order_id: str):
        """Removes mappings associated with a platform order ID."""
        with self._lock:
            ib_id = self._platform_to_ib_map.pop(platform_order_id, None)
            if ib_id is not None: # Check for None as 0 is a valid IBKR order ID
                self._ib_to_platform_map.pop(ib_id, None)
                logger.debug(f"Removed Order ID mapping for Platform ID: '{platform_order_id}'")

    def get_all_ib_to_platform_mappings(self) -> Dict[int, str]:
        """Returns a copy of the IBKR to Platform ID mappings."""
        with self._lock:
            return dict(self._ib_to_platform_map)

    def get_all_platform_to_ib_mappings(self) -> Dict[str, int]:
        """Returns a copy of the Platform to IBKR ID mappings."""
        with self._lock:
            return dict(self._platform_to_ib_map)

    # Methods to load/persist mappings would be needed if this moves to a persistent store.
    # def load_mappings(self, persister_interface): ...
    # def save_mappings(self, persister_interface): ...

if __name__ == '__main__':
    # Example Usage
    logging.basicConfig(level=logging.DEBUG)
    mapper = OrderIdMapper()

    mapper.add_mapping(ib_order_id=101, platform_order_id="platform_abc_123")
    mapper.add_mapping(ib_order_id=102, platform_order_id="platform_xyz_789")

    print(f"Platform ID for IB 101: {mapper.get_platform_id(101)}")
    print(f"IB ID for platform_xyz_789: {mapper.get_ib_id('platform_xyz_789')}")

    mapper.add_mapping(101, "platform_def_456") # Test conflict for IB ID
    mapper.add_mapping(103, "platform_abc_123") # Test conflict for Platform ID

    mapper.remove_mapping_by_platform_id("platform_xyz_789")
    print(f"After removal, Platform ID for IB 102: {mapper.get_platform_id(102)}")
    print(f"After removal, IB ID for platform_xyz_789: {mapper.get_ib_id('platform_xyz_789')}")

    print(f"All IB->Platform: {mapper.get_all_ib_to_platform_mappings()}")
    print(f"All Platform->IB: {mapper.get_all_platform_to_ib_mappings()}")
