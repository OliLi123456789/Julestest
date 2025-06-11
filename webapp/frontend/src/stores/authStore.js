// webapp/frontend/src/stores/authStore.js
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';

// Function to get initial apiToken from localStorage to avoid
// Zustand persist middleware's async nature for initial state if needed synchronously elsewhere.
// However, for this setup, persist middleware handles initialization well.
// const getInitialApiToken = () => localStorage.getItem('apiToken');

const useAuthStore = create(
  persist(
    (set, get) => ({
      apiToken: null, // Initialized by persist middleware from localStorage or as null
      userInfo: null, // Could store decoded JWT info or user profile from an API call
      isAuthenticated: false, // Initialized based on apiToken presence by persist

      setApiToken: (token) => {
        set({ apiToken: token, isAuthenticated: !!token });
        if (token) {
          // localStorage.setItem('apiToken', token); // Handled by persist middleware
          // TODO: Fetch user info from a /users/me endpoint if needed
          // For example:
          // fetchUserInfo(token).then(userInfo => set({ userInfo }));
        } else {
          // localStorage.removeItem('apiToken'); // Handled by persist middleware
          set({ userInfo: null });
        }
      },
      logout: () => {
        set({ apiToken: null, userInfo: null, isAuthenticated: false });
        // localStorage.removeItem('apiToken'); // Handled by persist middleware
        // Any other cleanup, e.g., redirecting, happens in the component calling logout
      },
      // Example action to set user info if fetched separately
      // setUserInfo: (info) => set({ userInfo: info }),
    }),
    {
      name: 'auth-storage', // Name of the item in localStorage
      storage: createJSONStorage(() => localStorage), // Use localStorage
      // Only persist apiToken. Other state like userInfo can be re-fetched or is transient.
      // isAuthenticated is derived, but can be persisted if useful for initial render.
      partialize: (state) => ({ apiToken: state.apiToken, isAuthenticated: !!state.apiToken }),
      // Custom function to run after rehydration is complete
      onRehydrateStorage: () => {
        return (state, error) => {
          if (error) {
            console.error("AuthStore: Failed to rehydrate from localStorage", error);
          }
          if (state) {
            // Ensure isAuthenticated is correctly set based on rehydrated apiToken
            state.isAuthenticated = !!state.apiToken;
            console.log("AuthStore: Rehydrated, isAuthenticated:", state.isAuthenticated);
          }
        };
      }
    }
  )
);

// Initialize isAuthenticated based on the token from localStorage after initial load/rehydration
// This ensures that isAuthenticated is correctly set when the app loads.
// The persist middleware's onRehydrateStorage can also handle this.
// We can also subscribe to changes if needed for immediate effect after rehydration.
// For simplicity, the `partialize` and `onRehydrateStorage` in persist config should handle it.
// useAuthStore.setState({ isAuthenticated: !!useAuthStore.getState().apiToken });


export default useAuthStore;
