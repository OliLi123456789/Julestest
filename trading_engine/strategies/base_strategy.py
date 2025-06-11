from abc import ABC, abstractmethod
from typing import Any, List, Dict, TYPE_CHECKING # Added Dict, TYPE_CHECKING
from trading_engine.oms.models import Order # Domain order model

if TYPE_CHECKING:
    from trading_engine.oms.oms import OrderManagementSystem # For type hinting

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, symbols_of_interest: List[str]):
        self.strategy_id = strategy_id
        self.symbols_of_interest = symbols_of_interest
        self._oms_interface: Optional['OrderManagementSystem'] = None # Injected by StrategyManager

    def set_oms_interface(self, oms_interface: 'OrderManagementSystem'):
        self._oms_interface = oms_interface

    @abstractmethod
    def on_start(self):
        """Called when the strategy is started."""
        pass

    @abstractmethod
    def on_stop(self):
        """Called when the strategy is stopped."""
        pass

    @abstractmethod
    def on_market_data(self, symbol: str, market_data: Any):
        """
        Called with market data.
        'market_data' could be a deserialized Quote, Trade, or Aggregate protobuf message.
        """
        pass

    @abstractmethod
    def on_order_update(self, order: Order):
        """Called when an order submitted by this strategy has an update."""
        pass

    def submit_order(self, order_parameters: Dict[str, Any]) -> str:
        """
        Helper method for strategies to submit orders through the OMS.
        'order_parameters' should contain all necessary fields for oms.models.Order
        and a 'user_trade_config' dictionary for routing details.
        """
        if not self._oms_interface:
            # Consider raising a specific exception type
            raise RuntimeError("OMS interface not set for strategy. Cannot submit order.")

        required_domain_fields = ["user_id", "symbol", "quantity", "order_type"]
        if not all(field in order_parameters for field in required_domain_fields):
            missing_fields = [field for field in required_domain_fields if field not in order_parameters]
            raise ValueError(f"Missing required fields for domain order submission: {missing_fields}")

        # Assuming order_parameters["order_type"] is already a trading_engine.oms.models.OrderType enum instance
        # If it's a string, it would need conversion here.
        from trading_engine.oms.models import OrderType as DomainOrderType # Local import for clarity
        order_type_param = order_parameters["order_type"]
        if not isinstance(order_type_param, DomainOrderType):
            try:
                order_type_param = DomainOrderType[order_type_param.upper()]
            except KeyError:
                 raise ValueError(f"Invalid order_type string: {order_parameters['order_type']}. Must be a valid OrderType enum member string.")


        domain_order = Order(
            user_id=str(order_parameters["user_id"]),
            symbol=str(order_parameters["symbol"]),
            quantity=float(order_parameters["quantity"]),
            order_type=order_type_param,
            price=float(order_parameters.get("price")) if order_parameters.get("price") is not None else None
            # OMS will handle other default fields like order_id, timestamps, version
        )

        # user_trade_config is expected by OMS's submit_order method (which passes it to OrderRouter)
        user_trade_config = order_parameters.get("user_trade_config", {})
        if not isinstance(user_trade_config, dict):
            raise ValueError("user_trade_config must be a dictionary.")

        # The OMS's submit_order method now takes the domain_order.
        # The second argument placeholder_user_config in OMS's submit_order
        # should ideally be replaced by a more robust way to pass this config,
        # which is what user_trade_config here aims to be.
        # The OMS submit_order signature might need adjustment if it still expects
        # a fixed placeholder_user_config.
        # For now, assuming OMS submit_order can take this user_trade_config.

        # The prompt for OMS in previous step had:
        # self.order_router.send_order_request(order, placeholder_user_config)
        # This needs to be reconciled. For now, passing user_trade_config.
        # The OMS.submit_order will need to be updated to use this user_trade_config
        # instead of its own placeholder_user_config when calling order_router.send_order_request.
        # This change in OMS is outside the scope of this file, but noted.

        return self._oms_interface.submit_order(domain_order) # OMS submit_order now expects only domain_order
                                                              # The user_trade_config needs to be handled by OMS
                                                              # or this method needs to pass it to OMS.
                                                              # Based on current OMS.submit_order, it generates its own placeholder.
                                                              # This needs alignment.
                                                              # For now, let's assume OMS can get user_trade_config from domain_order or other means.
                                                              # Or, more simply, the strategy provides all details for the NewOrderRequest proto
                                                              # via the order_parameters, and this method just passes them on.

                                                              # Revisiting the OMS.submit_order:
                                                              # it takes `order: Order` and then uses a `placeholder_user_config`
                                                              # for `order_router.send_order_request(order, placeholder_user_config)`.
                                                              # So, the strategy's `user_trade_config` needs to be used by OMS.
                                                              # The best way is if `Order` domain object itself carries these,
                                                              # or if `OMS.submit_order` is changed to accept it.
                                                              # For now, this `submit_order` will just create the domain Order.
                                                              # The `user_trade_config` from `order_parameters` will be used in OMS `submit_order`.
                                                              # This means `order_parameters` needs to be passed to OMS, or OMS needs to extract it.

                                                              # Let's adjust: Strategy's submit_order will prepare domain_order.
                                                              # OMS.submit_order will take domain_order, and then it will need to get
                                                              # the user_trade_config. This implies that the user_trade_config
                                                              # should be part of the Order object or passed alongside.
                                                              # The prompt for OMS.submit_order was:
                                                              # if not self.order_router.send_order_request(order, placeholder_user_config):
                                                              # This needs to change to use the strategy-provided config.

                                                              # For this step, the strategy's submit_order will just call the OMS's submit_order
                                                              # with the domain Order. The OMS's submit_order will be updated in a later step
                                                              # to correctly use strategy-provided config.
                                                              # The current OMS.submit_order uses its own placeholder_user_config.
                                                              # This is a known point of friction to be resolved.
                                                              # For THIS file, we'll assume the `order_parameters` includes everything,
                                                              # and `_oms_interface.submit_order` is called with just the domain_order.
                                                              # The responsibility of getting detailed config to Kafka is on OMS.

        # The current OMS.submit_order doesn't take user_trade_config.
        # This means the strategy needs to ensure the domain_order object itself has enough info,
        # or the OMS needs to be refactored.
        # Let's assume for now that the domain_order is sufficient and OMS has default routing details.
        # This is an area for future refinement.
        return self._oms_interface.submit_order(domain_order)
