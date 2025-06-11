import logging
import json
from typing import Any, Optional, List, Dict # Use Dict for InternalOrderRequest

from ibapi.contract import Contract, ContractDetails #type: ignore

# Assuming relative imports work for sibling modules
from .ib_client_wrapper import IBClientWrapper, InternalOrderRequest
from .ib_wrapper import IBWrapperImpl

logger = logging.getLogger(__name__)

class RequestHandler:
    def __init__(self, ib_client_wrapper: IBClientWrapper, wrapper: IBWrapperImpl):
        """
        Initializes the RequestHandler.
        :param ib_client_wrapper: An instance of IBClientWrapper for interacting with EClient.
        :param wrapper: An instance of IBWrapperImpl for accessing next order ID and other wrapper data.
        """
        self.ib_client_wrapper = ib_client_wrapper
        self.wrapper = wrapper # This is the IBWrapperImpl instance
        self.active_account_summary_reqs: Dict[int, str] = {} # req_id -> user_id or context
        self.active_positions_reqs: Dict[int, str] = {} # Using int as placeholder for actual reqId if needed, or just a flag
        self.active_pnl_reqs: Dict[int, str] = {}


    def _choose_best_contract_details(self, details_list: Optional[List[ContractDetails]], internal_order: InternalOrderRequest) -> Optional[Contract]:
        """
        Selects the most appropriate contract from a list of ContractDetails.
        This is crucial if reqContractDetails returns multiple matches.
        """
        if not details_list:
            logger.warning(f"No contract details found for symbol {internal_order.get('symbol')}.")
            return None

        if len(details_list) == 1:
            logger.info(f"Single contract detail found for {internal_order.get('symbol')}: ConId={details_list[0].contract.conId}")
            return details_list[0].contract

        logger.warning(f"Multiple contracts ({len(details_list)}) resolved for {internal_order.get('symbol')}. Applying filtering logic.")

        # Attempt to filter based on provided exchange, primary_exchange, currency, etc.
        # This logic needs to be robust and might require more specific inputs in InternalOrderRequest
        # if ambiguity is common for the traded instruments.

        target_exchange = str(internal_order.get("exchange", "SMART")).upper()
        target_primary_exchange = str(internal_order.get("primary_exchange", "")).upper()
        target_currency = str(internal_order.get("currency", "USD")).upper()

        # Exact match on exchange if not SMART, or on primaryExchange if SMART
        for cd in details_list:
            contract = cd.contract
            if contract.currency == target_currency: # Always match currency first
                if target_exchange == "SMART":
                    if target_primary_exchange and contract.primaryExchange == target_primary_exchange:
                        logger.info(f"Selected contract {contract.conId} for {contract.symbol} on SMART with primary exch {target_primary_exchange}")
                        return contract
                elif contract.exchange == target_exchange:
                    logger.info(f"Selected contract {contract.conId} for {contract.symbol} on specific exchange {target_exchange}")
                    return contract

        # Fallback: if SMART was requested and no primary_exchange match, take first SMART if any
        if target_exchange == "SMART":
            for cd in details_list:
                contract = cd.contract
                if contract.currency == target_currency and contract.exchange == "SMART":
                    logger.warning(f"Using first available SMART contract {contract.conId} for {contract.symbol} as primary_exchange did not match or wasn't specified.")
                    return contract

        # Further fallback: take the first one in the list if still ambiguous (log warning)
        if details_list:
            logger.warning(f"Could not definitively choose a contract for {internal_order.get('symbol')} with specified criteria. Using the first contract found: {details_list[0].contract.conId}")
            return details_list[0].contract

        logger.error(f"No suitable contract found after filtering for {internal_order.get('symbol')}.")
        return None


    def process_internal_order_request(self, internal_order_data: InternalOrderRequest) -> bool:
        """
        Processes an internal order request:
        1. Checks API readiness.
        2. Gets a new IBKR order ID.
        3. Creates an IBKR Contract object.
        4. Resolves ContractDetails if necessary (e.g., to get conId).
        5. Creates an IBKR Order object.
        6. Places the order via IBClientWrapper.
        Returns True if order submission was attempted, False otherwise.
        """
        order_desc = f"InternalOrderID {internal_order_data.get('internal_order_id', 'N/A')} for {internal_order_data.get('symbol')}"
        logger.info(f"RequestHandler: Processing order request: {order_desc}")

        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.error(f"RequestHandler: Cannot process order {order_desc}: IBKR API not ready.")
            # TODO: Publish a failure event back to OMS/caller
            return False

        ib_order_id = self.wrapper.get_next_order_id_and_increment()
        if ib_order_id is None:
            logger.error(f"RequestHandler: Cannot process order {order_desc}: Next valid IBKR order ID not available from wrapper.")
            # TODO: Publish a failure event
            return False

        try:
            # 1. Create initial IBKR Contract object from internal order data
            contract_to_resolve = self.ib_client_wrapper.create_ib_contract(internal_order_data)

            final_contract = contract_to_resolve

            # 2. Resolve ContractDetails if conId is not provided or is 0
            #    Some assets like options might *require* conId for accurate order placement,
            #    or if SMART routing needs disambiguation via primaryExchange.
            #    For simple stocks via SMART, often symbol, secType, currency, exchange is enough.
            #    However, best practice is to resolve conId.
            if not final_contract.conId: # conId is 0 by default for a new Contract object
                logger.info(f"RequestHandler: conId not present for {order_desc} (Symbol: {final_contract.symbol}). Attempting to resolve contract details...")
                resolved_details_list = self.ib_client_wrapper.resolve_contract_details(contract_to_resolve)

                chosen_contract_from_details = self._choose_best_contract_details(resolved_details_list, internal_order_data)

                if not chosen_contract_from_details:
                    logger.error(f"RequestHandler: Failed to resolve unique and valid contract details for {order_desc}. Order cannot be placed.")
                    # TODO: Publish failure event
                    return False
                final_contract = chosen_contract_from_details
                logger.info(f"RequestHandler: Resolved contract for {order_desc} to ConID: {final_contract.conId}, Exchange: {final_contract.exchange}, PrimaryExch: {final_contract.primaryExchange}")

            # 3. Create IBKR Order object
            ib_order = self.ib_client_wrapper.create_ib_order(internal_order_data, ib_order_id)

            # 4. Place the order
            self.ib_client_wrapper.place_order(final_contract, ib_order)
            logger.info(f"RequestHandler: Order {order_desc} submitted to IBKR with IBOrderID {ib_order_id} for ConID {final_contract.conId}.")
            return True # Indicates submission attempt was made

        except ValueError as ve: # From create_ib_contract or create_ib_order if params missing/invalid
            logger.error(f"RequestHandler: ValueError preparing order {order_desc}: {ve}")
        except ConnectionError as ce: # From place_order if not connected (should be caught by is_api_ready generally)
            logger.error(f"RequestHandler: ConnectionError placing order {order_desc}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: General exception processing order {order_desc}: {e}", exc_info=True)

        # TODO: Publish failure event if any exception occurred
        return False

    def process_order_modification_request(self, internal_order_data: InternalOrderRequest, ib_order_id_to_modify: int) -> bool:
        order_desc = f"InternalOrderID {internal_order_data.get('internal_order_id', 'N/A')} for IBOrderID {ib_order_id_to_modify}"
        logger.info(f"RequestHandler: Processing modification for {order_desc}")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.error(f"RequestHandler: Cannot modify order {order_desc}: API not ready.")
            # TODO: Publish failure event
            return False
        try:
            # For modification, the contract usually doesn't change, but quantity or price might.
            # The EClient.placeOrder call for modification requires the full new Order object
            # and the original Contract object (or one that identifies it, conId is best).
            contract = self.ib_client_wrapper.create_ib_contract(internal_order_data)
            if not contract.conId and "con_id" in internal_order_data: # Ensure conId is used if provided
                contract.conId = int(internal_order_data["con_id"])

            if not contract.conId:
                 # Attempt to resolve if not provided and critical (e.g. if symbol changed, though not typical for mod)
                 logger.warning(f"ConId not provided for modification of order {ib_order_id_to_modify}. Using provided contract fields.")
                 # In many cases, for modification, you might not need to re-resolve contract details if only price/qty change.
                 # However, if key contract identifiers changed in the request, resolution might be needed.

            modified_ib_order = self.ib_client_wrapper.create_ib_order(internal_order_data, ib_order_id_to_modify)

            self.ib_client_wrapper.place_or_modify_order(contract, modified_ib_order)
            logger.info(f"Order modification for {order_desc} (IBOrderID {ib_order_id_to_modify}) submitted.")
            return True
        except ValueError as ve:
            logger.error(f"RequestHandler: ValueError preparing order modification for {order_desc}: {ve}")
        except ConnectionError as ce:
            logger.error(f"RequestHandler: ConnectionError on order modification for {order_desc}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: General exception processing order modification for {order_desc}: {e}", exc_info=True)
        # TODO: Publish failure event
        return False

    def process_order_cancellation_request(self, ib_order_id_to_cancel: int, internal_id_ref: str = "N/A") -> bool:
        order_desc = f"IBOrderID {ib_order_id_to_cancel} (InternalRef: {internal_id_ref})"
        logger.info(f"RequestHandler: Processing cancellation for {order_desc}")
        if not self.wrapper.conn_manager or not self.wrapper.conn_manager.is_api_ready():
            logger.error(f"RequestHandler: Cannot cancel order {order_desc}: API not ready.")
            # TODO: Publish failure event
            return False
        try:
            self.ib_client_wrapper.cancel_order(ib_order_id_to_cancel)
            # Actual confirmation of cancellation comes via orderStatus callback
            logger.info(f"Order cancellation request for {order_desc} submitted.")
            return True
        except ConnectionError as ce:
            logger.error(f"RequestHandler: ConnectionError on order cancellation for {order_desc}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: General exception processing order cancellation for {order_desc}: {e}", exc_info=True)
        # TODO: Publish failure event
        return False

    # --- Conceptual Data Request Methods ---
    def request_and_get_account_summary(self, user_id: str, timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        logger.info(f"RequestHandler: Requesting account summary for user {user_id}")
        # If timeout is None, ib_client_wrapper will use its configured default.
        try:
            # The IBClientWrapper method `request_account_summary_sync` handles reqID and event internally
            summary_data = self.ib_client_wrapper.request_account_summary_sync(timeout_seconds=timeout)
            if summary_data:
                logger.info(f"RequestHandler: Successfully retrieved account summary for user {user_id}.")
                # TODO: Potentially normalize/filter summary_data before returning or publishing
                return summary_data.get("summary_values") # Return just the map of tags to values
            else:
                logger.warning(f"RequestHandler: No account summary data returned for user {user_id} (timeout or empty).")
                return None
        except ConnectionError as ce:
            logger.error(f"RequestHandler: ConnectionError requesting account summary for {user_id}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: Exception requesting account summary for {user_id}: {e}", exc_info=True)
        return None

    def request_and_get_positions(self, user_id: str, timeout: Optional[int] = None) -> Optional[List[Dict[str, Any]]]:
        logger.info(f"RequestHandler: Requesting positions for user {user_id}")
        # If timeout is None, ib_client_wrapper will use its configured default.
        try:
            positions = self.ib_client_wrapper.request_positions_sync(timeout_seconds=timeout)
            if positions is not None: # Can be an empty list if no positions
                logger.info(f"RequestHandler: Successfully retrieved {len(positions)} positions for user {user_id}.")
                # TODO: Normalize positions if needed
                return positions
            else:
                logger.warning(f"RequestHandler: No positions data returned for user {user_id} (timeout or error).")
                return None
        except ConnectionError as ce:
            logger.error(f"RequestHandler: ConnectionError requesting positions for {user_id}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: Exception requesting positions for {user_id}: {e}", exc_info=True)
        return None

    def request_and_get_pnl(self, account_id: str, con_id: int = 0, model_code: str = "", timeout: Optional[int] = None) -> Optional[Dict[str, Any]]:
        logger.info(f"RequestHandler: Requesting PnL for account {account_id}, con_id {con_id}, model '{model_code}'")
        # If timeout is None, ib_client_wrapper will use its configured default.
        try:
            pnl_data = self.ib_client_wrapper.request_pnl_sync(account=account_id, model_code=model_code, con_id=con_id, timeout_seconds=timeout)
            if pnl_data:
                logger.info(f"RequestHandler: Successfully retrieved PnL for account {account_id}.")
                return pnl_data
            else:
                logger.warning(f"RequestHandler: No PnL data returned for account {account_id} (timeout or error).")
                return None
        except ConnectionError as ce:
            logger.error(f"RequestHandler: ConnectionError requesting PnL for {account_id}: {ce}")
        except Exception as e:
            logger.error(f"RequestHandler: Exception requesting PnL for {account_id}: {e}", exc_info=True)
        return None
```
