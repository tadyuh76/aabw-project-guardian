const SUPPRESSED_DASHBOARD_MESSAGE_PATTERNS = [
  /^No resolved Guardian feedback occurs\b/i,
];

export function sanitizeDashboardMessages(messages: string[]): string[] {
  return messages.filter((message) => !SUPPRESSED_DASHBOARD_MESSAGE_PATTERNS.some((pattern) => pattern.test(message)));
}
