/**
 * Design-system button: uses `.btn` + `.btn--{variant}` from index.css.
 */
export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  type = 'button',
  className = '',
  disabled = false,
  loading = false,
  href,
  icon: Icon,
  onClick,
  ...rest
}) {
  const v = variant === 'danger' ? 'danger' : variant === 'ghost' ? 'ghost' : variant === 'secondary' ? 'secondary' : 'primary';
  const sz = size === 'sm' ? 'btn--sm' : size === 'lg' ? 'btn--lg' : size === 'xl' ? 'btn--xl' : '';
  const cls = `btn btn--${v} ${sz} ${className}`.trim();

  const inner = (
    <>
      {loading ? <span aria-busy="true">…</span> : null}
      {!loading && Icon ? <Icon size={16} strokeWidth={1.75} aria-hidden /> : null}
      {children}
    </>
  );

  if (href && !disabled) {
    return (
      <a href={href} className={cls} {...rest}>
        {inner}
      </a>
    );
  }

  return (
    <button
      type={type}
      className={cls}
      disabled={disabled || loading}
      onClick={onClick}
      aria-busy={loading || undefined}
      {...rest}
    >
      {inner}
    </button>
  );
}
