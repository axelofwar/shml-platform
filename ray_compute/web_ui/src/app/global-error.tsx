'use client'

import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('=== Global Error Handler ===')
    console.error('Error:', error)
    console.error('Message:', error.message)
    console.error('Stack:', error.stack)
    console.error('Digest:', error.digest)
  }, [error])

  return (
    <html>
      <body>
        <div style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(to bottom right, #0f172a, #1e293b)',
          fontFamily: 'system-ui, -apple-system, sans-serif'
        }}>
          <div style={{
            background: 'white',
            borderRadius: '8px',
            padding: '2rem',
            maxWidth: '600px',
            margin: '1rem'
          }}>
            <h2 style={{ fontSize: '1.5rem', fontWeight: 'bold', textAlign: 'center', marginBottom: '1rem' }}>
              Global Application Error
            </h2>
            <div style={{
              background: '#f3f4f6',
              padding: '1rem',
              borderRadius: '4px',
              marginBottom: '1rem',
              maxHeight: '300px',
              overflow: 'auto'
            }}>
              <pre style={{ fontSize: '0.875rem', margin: 0 }}>{error.message}</pre>
              {error.stack && (
                <pre style={{ fontSize: '0.75rem', marginTop: '0.5rem', color: '#6b7280' }}>{error.stack}</pre>
              )}
            </div>
            <button
              onClick={() => reset()}
              style={{
                width: '100%',
                background: '#2563eb',
                color: 'white',
                padding: '0.5rem 1rem',
                borderRadius: '4px',
                border: 'none',
                cursor: 'pointer',
                fontSize: '1rem'
              }}
            >
              Try again
            </button>
          </div>
        </div>
      </body>
    </html>
  )
}
