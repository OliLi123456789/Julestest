# webapp/backend/websocket_manager.py
import logging
from typing import Dict, List, Any
from fastapi import WebSocket # Changed from starlette.websockets as per instruction
import asyncio # For managing multiple client broadcasts

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # {user_id: [WebSocket_connection1, WebSocket_connection2, ...]}
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
        logger.info(f"WebSocket connected for user {user_id}. Total connections for user: {len(self.active_connections[user_id])}")

    def disconnect(self, websocket: WebSocket, user_id: str):
        # This method should not be async, as it's often called from finally blocks or error handlers
        # that might not be awaitable, or when the websocket state is uncertain.
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
                if not self.active_connections[user_id]: # No more connections for this user
                    del self.active_connections[user_id]
                logger.info(f"WebSocket disconnected for user {user_id}. Remaining for user: {len(self.active_connections.get(user_id, []))}")
            # else: logger.debug(f"Attempted to remove websocket for user {user_id}, but it was not in their list.")
        # else: logger.debug(f"Attempted to disconnect WebSocket for user {user_id} but user had no active connections listed.")


    async def broadcast_to_user(self, user_id: str, message_data: Dict[str, Any]):
        if user_id in self.active_connections:
            disconnected_sockets = []
            # Iterate over a copy of the list of sockets for this user,
            # as the original list might be modified if a disconnect occurs during iteration.
            active_sockets_for_user = list(self.active_connections.get(user_id, []))

            for websocket_conn in active_sockets_for_user:
                try:
                    await websocket_conn.send_json(message_data)
                except Exception as e: # Could be WebSocketDisconnect, RuntimeError, etc.
                    logger.warning(f"Failed to send message to user {user_id} via WebSocket: {e}. Marking for disconnect.")
                    disconnected_sockets.append(websocket_conn)

            # Clean up disconnected sockets by calling the synchronous disconnect method
            for sock_to_remove in disconnected_sockets:
                # Check if sock_to_remove is still in the current list for the user,
                # as another part of the code might have already removed it.
                if user_id in self.active_connections and sock_to_remove in self.active_connections[user_id]:
                    self.disconnect(sock_to_remove, user_id)

            if active_sockets_for_user:
                current_live_sockets = len(self.active_connections.get(user_id, []))
                logger.debug(f"Broadcasted message to user {user_id}. Sockets attempted: {len(active_sockets_for_user)}, Sockets live now: {current_live_sockets}. Message type: {message_data.get('type')}")
        # else: logger.debug(f"No active WebSocket connections for user {user_id} to broadcast to.")


# Global instance (or manage via FastAPI app state/dependency injection)
websocket_conn_manager = ConnectionManager()
