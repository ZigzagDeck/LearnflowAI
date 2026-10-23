/** Build citation previews only for a recognized YouTube video URL. */
export function youtubeEmbedUrl(sourceUrl: string | null, startSeconds = 0): string | null {
  if (!sourceUrl) return null
  try {
    const url = new URL(sourceUrl)
    if (!['https:', 'http:'].includes(url.protocol)) return null
    const host = url.hostname.toLowerCase().replace(/^www\./, '')
    const videoId = host === 'youtu.be' ? url.pathname.split('/')[1]
      : ['youtube.com', 'm.youtube.com', 'youtube-nocookie.com'].includes(host)
        ? url.pathname === '/watch' ? url.searchParams.get('v')
          : /^\/(?:embed|shorts|live)\//.test(url.pathname) ? url.pathname.split('/')[2] : null
        : null
    if (!videoId || !/^[\w-]{11}$/.test(videoId)) return null
    const start = Number.isFinite(startSeconds) ? Math.max(0, Math.floor(startSeconds)) : 0
    return `https://www.youtube-nocookie.com/embed/${videoId}?start=${start}&autoplay=1`
  } catch {
    return null
  }
}
