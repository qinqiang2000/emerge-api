export function newChatId(): string {
  return 'c_' + randomHex(12)
}

// crypto.randomUUID() is secure-context only (HTTPS or localhost). On a
// plain-HTTP deployment (e.g. http://<ip>:9090) it's undefined and throws,
// which used to blank the whole app since the chat store seeds an id at load.
// getRandomValues works in insecure contexts; Math.random is the last resort.
function randomHex(len: number): string {
  const c: Crypto | undefined = globalThis.crypto
  if (typeof c?.randomUUID === 'function') {
    return c.randomUUID().replace(/-/g, '').slice(0, len)
  }
  const bytes = new Uint8Array(Math.ceil(len / 2))
  if (typeof c?.getRandomValues === 'function') {
    c.getRandomValues(bytes)
  } else {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256)
  }
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('').slice(0, len)
}
