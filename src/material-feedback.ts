// Translate material failures into useful actions without exposing provider internals.
export function materialErrorMessage(detail: unknown, fallback = 'We could not get this material ready. Try again. If it keeps happening, contact the app owner.'): string {
  const text = typeof detail === 'string' ? detail.toLowerCase() : ''
  if (/session.*expired|sign in|unauthorized/.test(text)) return 'Your session has expired. Please sign in again.'
  if (/too many requests|too many attempts/.test(text)) return 'Please wait a moment before trying again.'
  if (/monthly.*limit|quota|usage limit/.test(text)) return 'The app has reached its usage limit. Please contact the app owner.'
  if (/not configured|credentials|api key|access token|location is invalid/.test(text)) return 'The app needs attention before it can prepare this material. Please contact the app owner.'
  if (/empty or password protected/.test(text)) return 'This PDF is empty or password-protected. Choose a PDF with pages that opens without a password.'
  if (/password.protected|encrypted/.test(text)) return 'This file is locked. Upload a copy that opens without a password.'
  if (/file is empty|uploaded file is empty/.test(text)) return 'This file is empty. Choose a file with content and upload it again.'
  if (/corrupt|damaged|invalid pdf signature|invalid pptx|do not match.*extension/.test(text)) return 'We could not read this file. Open it on your device, save a new copy, and upload that copy.'
  if (/too large|safe size limit/.test(text)) return 'This file or one of its pages is too large. Try a smaller copy.'
  if (/unsupported.*type|type is not supported/.test(text)) return 'Choose a PDF, PPTX, PNG, or JPEG file.'
  if (/no readable text/.test(text)) return 'We could not find readable text. Try a clearer scan or a file with selectable text.'
  if (/caption|transcript/.test(text)) return 'We could not read this video’s captions. Check that the video is public and has captions, or try another video.'
  if (/valid youtube|https youtube|youtube.*supported/.test(text)) return 'Paste a valid HTTPS YouTube video link.'
  if (/file is missing|file is not found|uploaded material.*not found/.test(text)) return 'We could not find the uploaded file. Please upload it again.'
  if (/failed to fetch|networkerror|network error|server could not be reached/.test(text)) return 'We could not connect. Check your internet connection and try again.'
  return fallback
}

export function materialStatusLabel(status: string): string {
  switch (status) {
    case 'uploaded': return 'Waiting to get ready'
    case 'processing': return 'Getting ready'
    case 'ready': return 'Ready to use'
    case 'failed': return 'Needs attention'
    default: return 'Checking status'
  }
}
