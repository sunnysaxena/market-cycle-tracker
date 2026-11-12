
import { useEffect, useId, useRef } from 'react'
import { X } from 'lucide-react'

export default function InfoPopup({ open, onClose, title, children }) {
  const titleId = useId()
  const closeButtonRef = useRef(null)
  const previousFocusRef = useRef(null)

  useEffect(() => {
    if (!open) return

    previousFocusRef.current = document.activeElement

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    closeButtonRef.current?.focus()

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow

      if (previousFocusRef.current instanceof HTMLElement) {
        previousFocusRef.current.focus()
      }
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-slate-200 bg-white shadow-2xl dark:border-slate-700 dark:bg-[#111827]"
      >
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white p-5 dark:border-slate-800 dark:bg-[#111827]">
          <h3
            id={titleId}
            className="text-lg font-semibold text-slate-900 dark:text-slate-100"
          >
            {title}
          </h3>

          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label="Close information"
            className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus:ring-2 focus:ring-violet-500 dark:hover:bg-slate-800 dark:hover:text-white"
          >
            <X size={20} />
          </button>
        </div>

        <div className="space-y-4 p-5 text-sm text-slate-600 dark:text-slate-300">
          {children}
        </div>
      </section>
    </div>
  )
}
