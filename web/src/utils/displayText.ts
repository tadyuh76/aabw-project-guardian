const LEADING_ARTIFACT = /^(?:(?:demo|test|testing|synthetic|fixture|mock|sample)(?:\s+data)?\s*[:\-]?\s*)+/i;
const EMBEDDED_ARTIFACT = /\s+\b(?:demo|synthetic|fixture|mock)\b\s*:/gi;
const GENERATED_SUFFIX = /\s*(?:Mẫu tổng hợp|Mẫu đối sánh|Trường hợp)\s+[a-z0-9_-]+\.?\s*$/giu;

export function cleanDisplayText(value: string): string {
  const hadLeadingArtifact = LEADING_ARTIFACT.test(value.trim());
  const cleaned = value
    .trim()
    .replace(LEADING_ARTIFACT, "")
    .replace(EMBEDDED_ARTIFACT, ":")
    .replace(GENERATED_SUFFIX, "")
    .replace(/\s{2,}/g, " ")
    .trim();

  if (!cleaned || !hadLeadingArtifact) return cleaned;
  return `${cleaned.charAt(0).toUpperCase()}${cleaned.slice(1)}`;
}
