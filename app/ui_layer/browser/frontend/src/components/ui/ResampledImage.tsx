import { useEffect, useRef, useState, type ImgHTMLAttributes } from 'react'

// An <img> for a picture far larger than the box it fills (marketplace
// previews are ~2800px screenshots shown at card size). Scaled at draw time,
// the GPU samples only a few of its pixels at that ratio and thin text breaks
// into jagged dots. This resamples it once, with a high-quality filter, to
// the box's device pixels (object-fit: cover), so the browser draws it 1:1.
// A source it cannot read (no CORS, no createImageBitmap) shows as is.

// Resampled copies by source and box size, kept for the page's lifetime so a
// reopened view shows them at once. null: show the source as is.
const resampled = new Map<string, Promise<string | null>>()

async function resample(src: string, width: number, height: number): Promise<string | null> {
  const response = await fetch(src, { referrerPolicy: 'no-referrer' })
  if (!response.ok) return null
  const full = await createImageBitmap(await response.blob())
  try {
    const scale = Math.max(width / full.width, height / full.height)
    if (scale >= 1) return null
    const w = Math.round(full.width * scale)
    const h = Math.round(full.height * scale)
    const small = await createImageBitmap(full, { resizeWidth: w, resizeHeight: h, resizeQuality: 'high' })
    const canvas = new OffscreenCanvas(w, h)
    canvas.getContext('2d')!.drawImage(small, 0, 0)
    small.close()
    return URL.createObjectURL(await canvas.convertToBlob({ type: 'image/png' }))
  } finally {
    full.close()
  }
}

export function ResampledImage({ src, alt, ...props }: ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const ref = useRef<HTMLImageElement>(null)
  const [shown, setShown] = useState<string | null>(null)

  useEffect(() => {
    const el = ref.current
    const ratio = window.devicePixelRatio || 1
    const width = el ? Math.ceil(el.clientWidth * ratio) : 0
    const height = el ? Math.ceil(el.clientHeight * ratio) : 0
    if (!width || !height) {
      setShown(src)
      return
    }
    const key = `${src}@${width}x${height}`
    let job = resampled.get(key)
    if (!job) {
      job = resample(src, width, height).catch(() => null)
      resampled.set(key, job)
    }
    let live = true
    void job.then(url => { if (live) setShown(url ?? src) })
    return () => { live = false }
  }, [src])

  // Empty until ready: the box shows its background, never the raw source.
  return <img ref={ref} src={shown ?? undefined} alt={shown ? alt : ''} {...props} />
}
