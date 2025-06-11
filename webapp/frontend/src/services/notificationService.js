// webapp/frontend/src/services/notificationService.js
import { toast } from 'react-toastify';

const showSuccess = (message, options = {}) => {
    toast.success(message, options);
};

const showError = (message, options = {}) => {
    toast.error(message, options);
};

const showInfo = (message, options = {}) => {
    toast.info(message, options);
};

const showWarning = (message, options = {}) => {
    toast.warn(message, options);
};

// You can also add a generic 'show' if needed, or more specific ones
// const show = (message, type = 'default', options = {}) => {
//    toast(message, { type, ...options });
// };

export const notificationService = { // Named export
    showSuccess,
    showError,
    showInfo,
    showWarning,
    // show,
};
