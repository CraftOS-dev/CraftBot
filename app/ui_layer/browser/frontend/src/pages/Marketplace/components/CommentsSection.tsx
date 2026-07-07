import React, { useEffect, useState } from 'react'
import { Loader2, MessageSquare, Send } from 'lucide-react'
import { fetchComments, postComment } from '../marketplaceApi'
import type { CommentItem } from '../marketplaceApi'
import styles from '../Marketplace.module.css'

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: 'numeric', month: 'short', day: 'numeric',
    })
  } catch {
    return ''
  }
}

/** Community comments: approved comments + a submit form (new comments go
 *  into the moderation queue before appearing). */
export function CommentsSection({ slug }: { slug: string }) {
  const [comments, setComments] = useState<CommentItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [unavailable, setUnavailable] = useState(false)

  const [draft, setDraft] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [sending, setSending] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  useEffect(() => {
    setComments([])
    setPage(1)
    setSubmitted(false)
    setLoading(true)
    fetchComments(slug, 1)
      .then(data => { setComments(data.comments); setTotal(data.total) })
      .catch(() => setUnavailable(true))
      .finally(() => setLoading(false))
  }, [slug])

  if (unavailable) return null

  const loadMore = async () => {
    const next = page + 1
    try {
      const data = await fetchComments(slug, next)
      setComments(prev => [...prev, ...data.comments])
      setPage(next)
    } catch { /* leave the list as-is */ }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!draft.trim() || sending) return
    setSending(true)
    setSubmitError(null)
    try {
      await postComment(slug, draft.trim(), displayName.trim() || undefined)
      setDraft('')
      setSubmitted(true)
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Could not submit comment')
    }
    setSending(false)
  }

  return (
    <div className={styles.aboutSection}>
      <h2 className={styles.aboutHeader}>
        Comments{total > 0 ? ` (${total})` : ''}
      </h2>

      <form className={styles.commentForm} onSubmit={submit}>
        <input
          className={styles.input}
          placeholder="Display name (optional)"
          value={displayName}
          onChange={e => setDisplayName(e.target.value)}
          maxLength={60}
        />
        <textarea
          className={styles.commentTextarea}
          placeholder="Share your experience with this Living UI..."
          value={draft}
          onChange={e => setDraft(e.target.value)}
          maxLength={2000}
          rows={3}
        />
        <div className={styles.commentFormFooter}>
          {submitted ? (
            <span className={styles.commentPendingNote}>
              Submitted — appears after review.
            </span>
          ) : submitError ? (
            <span className={styles.errorText}>{submitError}</span>
          ) : <span />}
          <button className={styles.installBtn} type="submit" disabled={!draft.trim() || sending}>
            {sending ? <Loader2 size={13} className={styles.spinner} /> : <Send size={13} />}
            Post
          </button>
        </div>
      </form>

      {loading ? (
        <div className={styles.stateCenter}><Loader2 size={18} className={styles.spinner} /></div>
      ) : comments.length === 0 ? (
        <p className={styles.commentEmpty}>
          <MessageSquare size={14} /> No comments yet.
        </p>
      ) : (
        <div className={styles.commentList}>
          {comments.map(c => (
            <div key={c.id} className={styles.comment}>
              <div className={styles.commentHead}>
                <span className={styles.commentAuthor}>{c.displayName || 'Anonymous'}</span>
                <span className={styles.commentDate}>{formatDate(c.createdAt)}</span>
              </div>
              <p className={styles.commentBody}>{c.body}</p>
            </div>
          ))}
          {comments.length < total && (
            <button className={styles.configCancel} onClick={loadMore}>
              Show more
            </button>
          )}
        </div>
      )}
    </div>
  )
}
