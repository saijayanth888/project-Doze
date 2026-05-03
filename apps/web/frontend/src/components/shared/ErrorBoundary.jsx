import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('ErrorBoundary', error, info);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            minHeight: '60vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 24,
            fontFamily: 'var(--font-ui, Outfit, sans-serif)',
            color: 'var(--text-secondary, #94a3b8)',
            textAlign: 'center',
          }}
        >
          <h1 style={{ color: 'var(--danger, #ef4444)', fontSize: '1.25rem', marginBottom: 8 }}>Something went wrong</h1>
          <p style={{ maxWidth: 480, marginBottom: 20 }}>{String(this.state.error?.message || this.state.error)}</p>
          <button
            type="button"
            className="btn btn--primary"
            onClick={() => {
              this.setState({ error: null });
              window.location.reload();
            }}
          >
            Reload page
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
