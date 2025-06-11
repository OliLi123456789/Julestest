// webapp/frontend/src/stores/tradingStore.js
import { create } from 'zustand';

const useTradingStore = create((set, get) => ({
  orders: [], // Array of order objects: { order_id: "...", symbol: "...", ... }
  positions: [], // Array of position objects: { symbol: "...", quantity: ..., avg_price: ... }
  currentSymbol: 'AAPL', // Default symbol for charts or order entry focus

  setCurrentSymbol: (symbol) => set({ currentSymbol: symbol.toUpperCase() }),

  // --- Order Actions ---
  // Adds an order or updates it if it already exists in the list
  addOrUpdateOrder: (orderData) => set((state) => {
    const existingOrderIndex = state.orders.findIndex(o => o.order_id === orderData.order_id);
    let newOrdersArray = [...state.orders];
    if (existingOrderIndex !== -1) {
      // Update existing order by merging new data
      newOrdersArray[existingOrderIndex] = { ...newOrdersArray[existingOrderIndex], ...orderData };
    } else {
      // Add new order
      newOrdersArray.push(orderData);
    }
    // Sort orders, e.g., by timestamp descending or status (optional)
    // newOrdersArray.sort((a, b) => (b.timestamp_utc || 0) - (a.timestamp_utc || 0));
    return { orders: newOrdersArray };
  }),

  // Replaces all orders; useful for initial load or full refresh from API
  setOrders: (ordersData) => set({ orders: ordersData || [] }),

  // --- Position Actions ---
  // Adds a position or updates it if it already exists
  addOrUpdatePosition: (positionData) => set((state) => {
    // Assuming 'symbol' + 'user_id' (if positions could be for multiple users in an admin view)
    // or just 'symbol' is the unique key for a position in this user-specific store.
    const positionKey = positionData.symbol;
    const existingPosIndex = state.positions.findIndex(p => p.symbol === positionKey);
    let newPositionsArray = [...state.positions];
    if (existingPosIndex !== -1) {
      newPositionsArray[existingPosIndex] = { ...newPositionsArray[existingPosIndex], ...positionData };
    } else {
      newPositionsArray.push(positionData);
    }
    return { positions: newPositionsArray };
  }),

  // Replaces all positions
  setPositions: (positionsData) => set({ positions: positionsData || [] }),

  // Example of an action that could use other parts of the store or async logic
  // This is conceptual and would need e.g. an API service passed in or imported
  // fetchAndSetInitialOrders: async (apiService, userId) => {
  //   try {
  //     const initialOrders = await apiService.getAllOrders(userId); // Assuming an apiService method
  //     set({ orders: initialOrders });
  //   } catch (error) {
  //     console.error("Failed to fetch initial orders:", error);
  //     // Handle error appropriately, maybe set an error state in the store
  //   }
  // },
}));

export default useTradingStore;
