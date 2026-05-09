export function newChatId(): string {
  return 'c_' + crypto.randomUUID().replace(/-/g, '').slice(0, 12)
}
