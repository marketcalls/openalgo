/**
 * Toast utility with alert category support
 *
 * This utility wraps the sonner toast library to provide category-based
 * toast filtering. Toasts are only shown if:
 * 1. Master toasts toggle is enabled
 * 2. The specific category is enabled (if category is specified)
 *
 * Usage:
 * import { showToast } from '@/utils/toast'
 *
 * // With category (respects user settings)
 * showToast.success('Order placed', 'orders')
 * showToast.error('Failed to save', 'strategy')
 *
 * // Without category (always shows if master toggle enabled)
 * showToast.success('Copied to clipboard')
 *
 * // For validation errors (should always show - don't use category)
 * showToast.error('Please fill all required fields')
 */

import { toast } from 'sonner'
import { useAlertStore, type AlertCategories } from '@/stores/alertStore'

type ToastType = 'success' | 'error' | 'warning' | 'info'

interface ToastOptions {
  duration?: number
  description?: string
}

/**
 * Show a toast notification respecting alert settings
 * @param type - Toast type (success, error, warning, info)
 * @param message - Toast message
 * @param category - Optional category for filtering
 * @param options - Optional toast options
 */
const show = (
  type: ToastType,
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  const { shouldShowToast } = useAlertStore.getState()

  if (!shouldShowToast(category)) {
    return
  }

  toast[type](message, options)
}

/**
 * Show a success toast
 */
const success = (
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show('success', message, category, options)
}

/**
 * Show an error toast
 */
const error = (
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show('error', message, category, options)
}

/**
 * Show a warning toast
 */
const warning = (
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show('warning', message, category, options)
}

/**
 * Show an info toast
 */
const info = (
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show('info', message, category, options)
}

/**
 * Dismiss all toasts
 */
const dismissAll = () => {
  toast.dismiss()
}

/**
 * Show a dynamic toast based on type
 */
const dynamic = (
  type: ToastType,
  message: string,
  category?: keyof AlertCategories,
  options?: ToastOptions
) => {
  show(type, message, category, options)
}

export const showToast = {
  success,
  error,
  warning,
  info,
  dismissAll,
  dynamic,
  show,
}

// Re-export the raw toast for cases where category filtering is not needed
// (e.g., validation errors that must always show)
export { toast }
