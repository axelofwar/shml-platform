'use client'

import { useEffect } from 'react'

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Log the error to the console with full details
    console.error('=== React Error Boundary ===')
    console.error('Error:', error)
    console.error('Message:', error.message)
    console.error('Stack:', error.stack)
    console.error('Digest:', error.digest)
  }, [error])

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-900 to-slate-800">
      <div className="bg-white rounded-lg shadow-lg p-8 max-w-2xl mx-4">
        <div className="flex items-center justify-center w-12 h-12 mx-auto bg-red-100 rounded-full mb-4">
          <svg
            className="w-6 h-6 text-red-600"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-center text-gray-900 mb-2">
          Application Error
        </h2>
        <div className="mb-6">
          <p className="text-gray-600 text-center mb-4">
            An error occurred in the application. Details have been logged to the console.
          </p>
          <div className="bg-gray-100 p-4 rounded-md overflow-auto max-h-64">
            <pre className="text-sm text-gray-800">{error.message}</pre>
            {error.stack && (
              <pre className="text-xs text-gray-600 mt-2">{error.stack}</pre>
            )}
          </div>
        </div>
        <div className="flex gap-4">
          <button
            onClick={() => reset()}
            className="flex-1 bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 transition-colors"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.href = '/login'}
            className="flex-1 bg-gray-600 text-white py-2 px-4 rounded-md hover:bg-gray-700 transition-colors"
          >
            Go to Login
          </button>
        </div>
      </div>
    </div>
  )
}
