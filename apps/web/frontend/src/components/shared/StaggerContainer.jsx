import { Children } from 'react';

export default function StaggerContainer({ children, className = '' }) {
  return (
    <div className={className}>
      {Children.map(children, (child, i) =>
        child ? (
          <div className="stagger-child" style={{ '--i': i }}>
            {child}
          </div>
        ) : null
      )}
    </div>
  );
}
