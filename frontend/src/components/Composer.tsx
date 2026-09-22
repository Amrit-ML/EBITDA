import { useLayoutEffect, useRef, useState } from 'react'
import { ArrowUp, Plus } from 'lucide-react'
import { cn } from '@/lib/utils'

interface Props {
  enabled: boolean
  busy: boolean
  canAttach: boolean
  placeholder: string
  onSend: (text: string) => void
  onAttach: () => void
}

export function Composer(p: Props) {
  const [text, setText] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  // Grow with the text up to a cap, then scroll inside.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 208)}px`
  }, [text])

  const canSend = p.enabled && !p.busy && text.trim().length > 0

  function submit() {
    if (!canSend) return
    p.onSend(text.trim())
    setText('')
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
      className="flex items-end gap-2 rounded-xl border-2 border-n-3 bg-n-1 p-2 transition-colors focus-within:border-n-4/50 dark:border-n-5 dark:bg-n-6 dark:focus-within:border-n-4"
    >
      <button
        type="button"
        onClick={p.onAttach}
        disabled={!p.canAttach}
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg text-n-4 transition-colors hover:text-n-7 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:text-n-4 dark:text-n-4d dark:hover:text-n-1"
        aria-label="Add company documents"
        title="Add company documents"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-n-4 text-n-1 dark:bg-n-4d dark:text-n-7">
          <Plus className="h-4 w-4" strokeWidth={2.5} aria-hidden="true" />
        </span>
      </button>
      <label htmlFor="composer" className="sr-only">
        Message
      </label>
      <textarea
        id="composer"
        ref={ref}
        rows={1}
        value={text}
        disabled={!p.enabled || p.busy}
        placeholder={p.placeholder}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
        className="scroll-quiet min-h-10 flex-1 resize-none bg-transparent py-2 text-base leading-6 outline-none placeholder:text-n-4 disabled:cursor-not-allowed dark:placeholder:text-n-4d"
      />
      <button
        type="submit"
        disabled={!canSend}
        className={cn(
          'flex h-10 w-10 shrink-0 items-center justify-center rounded-lg transition',
          canSend
            ? 'bg-primary-1 text-n-1 hover:bg-primary-1/90 active:scale-90'
            : 'cursor-not-allowed bg-n-2 text-n-4 dark:bg-n-5 dark:text-n-4d'
        )}
        aria-label="Send"
      >
        <ArrowUp className="h-5 w-5" strokeWidth={2.5} aria-hidden="true" />
      </button>
    </form>
  )
}
