interface ErrorNoticeProps {
  message: string
}

/** A genuine failure — the API was unreachable or returned a non-2xx. Deliberately distinct
 * (role="alert", red) from `RefusalNotice` (role="status", amber): this is something that went
 * wrong, not the system honestly declining to answer. */
export function ErrorNotice({ message }: ErrorNoticeProps) {
  return (
    <section className="error-notice" role="alert" aria-label="Error">
      <span className="grc-badge grc-badge--refuse" style={{ color: 'var(--error)', background: 'var(--error-soft)', borderColor: 'var(--error-line)' }}>
        Something went wrong
      </span>
      <p className="error-notice__message">{message}</p>
    </section>
  )
}
