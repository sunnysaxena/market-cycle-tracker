import { useEffect, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

function toISODate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')

  return `${year}-${month}-${day}`
}

function formatDisplayDate(isoDate) {
  if (!isoDate) return ''

  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDate)
  if (!match) return ''

  return `${match[3]}-${match[2]}-${match[1]}`
}

function parseDisplayDate(displayDate) {
  const match = /^(\d{2})-(\d{2})-(\d{4})$/.exec(displayDate)

  if (!match) return null

  const day = Number(match[1])
  const month = Number(match[2])
  const year = Number(match[3])

  const date = new Date(year, month - 1, day)

  // Reject invalid dates such as 31-02-2026.
  if (
    date.getFullYear() !== year ||
    date.getMonth() !== month - 1 ||
    date.getDate() !== day
  ) {
    return null
  }

  return toISODate(date)
}

export default function CustomDatePicker({
  id,
  label,
  value,
  onChange,
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [inputValue, setInputValue] = useState(formatDisplayDate(value))
  const [visibleMonth, setVisibleMonth] = useState(() => {
    if (value) {
      const [year, month, day] = value.split('-').map(Number)
      return new Date(year, month - 1, day)
    }

    return new Date()
  })

  useEffect(() => {
    setInputValue(formatDisplayDate(value))

    if (value) {
      const [year, month, day] = value.split('-').map(Number)
      setVisibleMonth(new Date(year, month - 1, day))
    }
  }, [value])

  const year = visibleMonth.getFullYear()
  const month = visibleMonth.getMonth()

  const firstDayOfMonth = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()

  const selectedISO = value || ''
  const todayISO = toISODate(new Date())

  const monthLabel = visibleMonth.toLocaleDateString('en-IN', {
    month: 'long',
    year: 'numeric',
  })

  const changeMonth = (amount) => {
    setVisibleMonth(new Date(year, month + amount, 1))
  }

  const selectDate = (day) => {
    const selectedDate = new Date(year, month, day)
    const isoDate = toISODate(selectedDate)

    onChange(isoDate)
    setInputValue(formatDisplayDate(isoDate))
    setIsOpen(false)
  }

  const commitManualDate = () => {
    if (!inputValue.trim()) {
      onChange('')
      return
    }

    const parsedDate = parseDisplayDate(inputValue.trim())

    if (parsedDate) {
      onChange(parsedDate)
      setInputValue(formatDisplayDate(parsedDate))
    } else {
      setInputValue(formatDisplayDate(value))
    }
  }

  return (
    <div className="relative">
      {label && (
        <label
          htmlFor={id}
          className="mb-1 block text-xs font-medium text-slate-500 dark:text-slate-400"
        >
          {label}
        </label>
      )}

      {/* Date Input */}
      <div className="relative">
        <input
          id={id}
          type="text"
          inputMode="numeric"
          placeholder="DD-MM-YYYY"
          value={inputValue}
          maxLength={10}
          onChange={(event) => setInputValue(event.target.value)}
          onBlur={commitManualDate}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              commitManualDate()
              setIsOpen(false)
            }

            if (event.key === 'Escape') {
              setInputValue(formatDisplayDate(value))
              setIsOpen(false)
            }
          }}
          className="h-9 w-40 rounded-md border border-slate-300 bg-white py-2 pl-3 pr-10 text-xs font-medium text-slate-700 outline-none transition-colors placeholder:text-slate-400 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
        />

        <button
          type="button"
          onClick={() => setIsOpen((current) => !current)}
          aria-label={`Open ${label || 'date'} calendar`}
          aria-expanded={isOpen}
          className="absolute inset-y-0 right-0 flex w-9 items-center justify-center text-slate-500 transition-colors hover:text-blue-600 dark:text-slate-400 dark:hover:text-blue-400"
        >
          <CalendarDays size={16} />
        </button>
      </div>

      {/* Calendar Popup */}
      {isOpen && (
        <div className="absolute left-0 top-full z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-3 shadow-xl dark:border-slate-700 dark:bg-slate-900">

          {/* Calendar Header */}
          <div className="mb-3 flex items-center justify-between">
            <button
              type="button"
              onClick={() => changeMonth(-1)}
              aria-label="Previous month"
              className="rounded-md p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <ChevronLeft size={18} />
            </button>

            <span className="text-sm font-semibold text-slate-800 dark:text-slate-100">
              {monthLabel}
            </span>

            <button
              type="button"
              onClick={() => changeMonth(1)}
              aria-label="Next month"
              className="rounded-md p-2 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <ChevronRight size={18} />
            </button>
          </div>

          {/* Weekday Names */}
          <div className="mb-2 grid grid-cols-7 text-center">
            {['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].map((day) => (
              <span
                key={day}
                className="py-1 text-xs font-medium text-slate-400"
              >
                {day}
              </span>
            ))}
          </div>

          {/* Calendar Days */}
          <div className="grid grid-cols-7 gap-y-1">
            {Array.from({ length: firstDayOfMonth }).map((_, index) => (
              <div key={`empty-${index}`} />
            ))}

            {Array.from({ length: daysInMonth }, (_, index) => index + 1).map(
              (day) => {
                const dayISO = toISODate(new Date(year, month, day))
                const isSelected = dayISO === selectedISO
                const isToday = dayISO === todayISO

                return (
                  <button
                    key={day}
                    type="button"
                    onClick={() => selectDate(day)}
                    aria-label={`${day} ${monthLabel}`}
                    aria-pressed={isSelected}
                    className={`mx-auto flex h-8 w-8 items-center justify-center rounded-md text-xs transition-colors ${
                      isSelected
                        ? 'bg-blue-600 font-semibold text-white'
                        : isToday
                          ? 'border border-blue-500 font-semibold text-blue-600 dark:text-blue-400'
                          : 'text-slate-700 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
                    }`}
                  >
                    {day}
                  </button>
                )
              },
            )}
          </div>

          {/* Calendar Footer */}
          <div className="mt-3 flex justify-between border-t border-slate-200 pt-2 dark:border-slate-700">
            <button
              type="button"
              onClick={() => {
                onChange('')
                setInputValue('')
                setIsOpen(false)
              }}
              className="text-xs font-medium text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
            >
              Clear
            </button>

            <button
              type="button"
              onClick={() => {
                const today = new Date()
                const isoDate = toISODate(today)

                onChange(isoDate)
                setInputValue(formatDisplayDate(isoDate))
                setVisibleMonth(today)
                setIsOpen(false)
              }}
              className="text-xs font-medium text-blue-600 hover:text-blue-700 dark:text-blue-400"
            >
              Today
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
