const HREF =
  'https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap'

if (typeof document !== 'undefined' && !document.querySelector(`link[href="${HREF}"]`)) {
  const pre1 = document.createElement('link'); pre1.rel = 'preconnect'; pre1.href = 'https://fonts.googleapis.com'; document.head.appendChild(pre1)
  const pre2 = document.createElement('link'); pre2.rel = 'preconnect'; pre2.href = 'https://fonts.gstatic.com'; pre2.crossOrigin = ''; document.head.appendChild(pre2)
  const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = HREF; document.head.appendChild(link)
}

export {}
