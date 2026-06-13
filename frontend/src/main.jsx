import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }
  static getDerivedStateFromError(error) {
    return { error }
  }
  componentDidCatch(error, info) {
    console.error('App crashed:', error, info)
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{
          minHeight: '100vh', background: '#0f172a', color: '#f1f5f9',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column', padding: '2rem', fontFamily: 'monospace'
        }}>
          <div style={{ fontSize: '2rem', marginBottom: '1rem' }}>⚠️</div>
          <h2 style={{ color: '#f87171', marginBottom: '1rem' }}>App Error</h2>
          <pre style={{
            background: '#1e293b', padding: '1rem', borderRadius: '0.5rem',
            maxWidth: '600px', width: '100%', overflow: 'auto',
            color: '#fca5a5', fontSize: '0.75rem', whiteSpace: 'pre-wrap'
          }}>
            {this.state.error?.message}
            {'\n\n'}
            {this.state.error?.stack?.split('\n').slice(0,8).join('\n')}
          </pre>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: '1rem', padding: '0.5rem 1rem',
              background: '#10b981', color: 'white',
              border: 'none', borderRadius: '0.5rem', cursor: 'pointer'
            }}
          >
            Try Again
          </button>
          <p style={{ color: '#64748b', marginTop: '1rem', fontSize: '0.75rem' }}>
            Screenshot this error and share it for debugging
          </p>
        </div>
      )
    }
    return this.props.children
  }
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <ErrorBoundary>
    <App />
  </ErrorBoundary>
)
