import '@testing-library/jest-dom/vitest'

// jsdom doesn't ship ResizeObserver / IntersectionObserver — provide no-op stubs for unit tests
if (typeof ResizeObserver === 'undefined') {
  global.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}

if (typeof IntersectionObserver === 'undefined') {
  global.IntersectionObserver = class IntersectionObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() { return [] }
    readonly root = null
    readonly rootMargin = ''
    readonly thresholds = []
  }
}
