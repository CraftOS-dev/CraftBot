// Pure geometry for the live view. The frame <img> fills the stage with
// `object-fit: contain`, so whenever the frame's aspect differs from the
// stage (mid-resize, a clamped viewport, another window's size) the picture
// is letterboxed. Input must be mapped against the DRAWN picture, never the
// element box, or clicks land tens of pixels off — and clicks on the bars
// must be ignored rather than snapped onto the page edge.

export interface Rect {
  left: number
  top: number
  width: number
  height: number
}

export interface FramePoint {
  /** 0..1 across the frame the user saw. */
  x: number
  y: number
}

/** Where an image of natural size `naturalWidth`×`naturalHeight` is drawn
 *  inside `box` under `object-fit: contain`. Null when nothing is drawn. */
export function containRect(box: Rect, naturalWidth: number, naturalHeight: number): Rect | null {
  if (!(naturalWidth > 0 && naturalHeight > 0 && box.width > 0 && box.height > 0)) return null
  const scale = Math.min(box.width / naturalWidth, box.height / naturalHeight)
  const width = naturalWidth * scale
  const height = naturalHeight * scale
  return {
    left: box.left + (box.width - width) / 2,
    top: box.top + (box.height - height) / 2,
    width,
    height,
  }
}

const clamp01 = (value: number): number => Math.min(1, Math.max(0, value))

/** A client point as 0..1 frame coordinates. Points on the letterbox bars
 *  give null, unless `clamp` (a drag that left the picture keeps going at
 *  its edge). */
export function toFramePoint(
  drawn: Rect,
  clientX: number,
  clientY: number,
  clamp: boolean,
): FramePoint | null {
  const x = (clientX - drawn.left) / drawn.width
  const y = (clientY - drawn.top) / drawn.height
  if (clamp) return { x: clamp01(x), y: clamp01(y) }
  if (!(x >= 0 && x <= 1 && y >= 0 && y <= 1)) return null
  return { x, y }
}

/** The drawn picture of `img` in client coordinates, or null before the
 *  first frame has decoded. */
export function drawnImageRect(img: HTMLImageElement | null): Rect | null {
  if (!img || !img.naturalWidth || !img.naturalHeight) return null
  const box = img.getBoundingClientRect()
  return containRect(
    { left: box.left, top: box.top, width: box.width, height: box.height },
    img.naturalWidth,
    img.naturalHeight,
  )
}
