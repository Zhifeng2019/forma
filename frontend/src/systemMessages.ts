import i18n, { formatDateTime, t } from './i18n'

export function statusLabel(value: string) {
  return t(`status.${value}`, { defaultValue: value })
}

type Rule = [RegExp, (match: RegExpMatchArray) => string]
const architecture = (value: string) => ['static', 'frontend only'].includes(value) ? t('Frontend only') : value === 'fastapi' ? 'FastAPI' : t(value)

// Only known application messages are translated. User text, source code, model
// output, and unknown diagnostic details retain their original contents.
const rules: Rule[] = [
  [/^Wait (\d+) seconds before requesting another code\.$/, m => t('Wait {{count}} seconds before requesting another code.', { count: +m[1] })],
  [/^Project limit reached \((\d+) per user\)\. Delete a project before creating another\.$/, m => t('Project limit reached ({{limit}} per user). Delete a project before creating another.', { limit: +m[1] })],
  [/^Provider returned HTTP (\d+)$/, m => t('Provider returned HTTP {{status}}', { status: m[1] })],
  [/^Connection failed: (.+)$/s, m => t('Connection failed: {{detail}}', { detail: m[1] })],
  [/^Connection successful\. (\d+) models available\.$/, m => t('Connection successful. {{count}} models available.', { count: +m[1] })],
  [/^This project already uses (static|fastapi) architecture$/, m => t('This project already uses {{architecture}} architecture', { architecture: architecture(m[1]) })],
  [/^(.+) and all their data were deleted\. Their contact can be registered again\.$/s, m => t('{{name}} and all their data were deleted. Their contact can be registered again.', { name: m[1] })],
  [/^(.+) is approved and can now sign in\.$/s, m => t('{{name}} is approved and can now sign in.', { name: m[1] })],
  [/^(.+)'s registration was rejected\.$/s, m => t("{{name}}'s registration was rejected.", { name: m[1] })],
  [/^String should have at least (\d+) characters$/, m => t('Please enter at least {{count}} characters.', { count: +m[1] })],
  [/^String should have at most (\d+) characters$/, m => t('Please enter no more than {{count}} characters.', { count: +m[1] })],
  [/^Input should be greater than or equal to (.+)$/, m => t('Please enter a value of at least {{value}}.', { value: m[1] })],
  [/^Input should be less than or equal to (.+)$/, m => t('Please enter a value no greater than {{value}}.', { value: m[1] })],
  [/^value is not a valid email address: .+$/s, () => t('Please enter a valid email address.')],
  [/^String should match pattern .+$/, () => t('Please use the requested format.')],
  [/^Phase (\d+)$/, m => t('Phase {{phase}}', { phase: +m[1] })],
  [/^Phase (\d+) is implemented and the preview has been updated\.$/, m => t('Phase {{phase}} is implemented and the preview has been updated.', { phase: +m[1] })],
  [/^(Product description|Experience design|Implementation plan|Phased implementation|Review & improve|Ready to publish|Discovery|Design|Plan|Implementation|Review|Release) completed$/, m => t('{{stage}} completed', { stage: t(m[1]) })],
  [/^(Product description|Experience design|Implementation plan|Phased implementation|Review & improve|Ready to publish|Discovery|Design|Plan|Implementation|Review|Release|Document revision) started with (.+)$/, m => t('{{stage}} started with {{engine}}', { stage: t(m[1]), engine: m[2] })],
  [/^Architecture: (FastAPI backend|frontend only) — (.+)$/s, m => t('Architecture: {{architecture}} — {{reason}}', { architecture: architecture(m[1]), reason: systemText(m[2]) })],
  [/^Feedback applied to version (\d+)$/, m => t('Feedback applied to version {{version}}', { version: +m[1] })],
  [/^Version (\d+) published; hosting expires at (.+)$/, m => t('Version {{version}} published; hosting expires at {{date}}', { version: +m[1], date: formatDateTime(m[2]) })],
  [/^Version (\d+) is live\. Your public link is ready to share\. Hosting expires at (.+)\.$/, m => t('Version {{version}} is live. Your public link is ready to share. Hosting expires at {{date}}.', { version: +m[1], date: formatDateTime(m[2]) })],
  [/^I hit a problem: (.+)$/s, m => t('I hit a problem: {{detail}}', { detail: systemText(m[1]) })],
  [/^Architecture updated to (static|fastapi)\. The next build will use this foundation\.$/, m => t('Architecture updated to {{architecture}}. The next build will use this foundation.', { architecture: architecture(m[1]) })],
  [/^Architecture migration to (static|fastapi) started$/, m => t('Architecture migration to {{architecture}} started', { architecture: architecture(m[1]) })],
  [/^Architecture changed to (static|fastapi) before the first build$/, m => t('Architecture changed to {{architecture}} before the first build', { architecture: architecture(m[1]) })],
  [/^Architecture migrated to (static|fastapi) as version (\d+)$/, m => t('Architecture migrated to {{architecture}} as version {{version}}', { architecture: architecture(m[1]), version: +m[2] })],
  [/^Version (\d+) now uses (static|fastapi)\. Your phase and published release are unchanged\.$/, m => t('Version {{version}} now uses {{architecture}}. Your phase and published release are unchanged.', { version: +m[1], architecture: architecture(m[2]) })],
  [/^I’ve applied your feedback to `([^`]+)`\. Review it, then approve to continue\.$/, m => t('I’ve applied your feedback to `{{path}}`. Review it, then approve to continue.', { path: m[1] })],
  [/^Noted\. I’ll carry this direction into the next artifact: “([\s\S]*)”$/, m => t('Noted. I’ll carry this direction into the next artifact: “{{feedback}}”', { feedback: m[1] })],
  [/^([^\n]+\.md) revised from feedback$/, m => t('{{path}} revised from feedback', { path: m[1] })],
]

export function systemText(value: string): string {
  if (i18n.resolvedLanguage !== 'zh-CN') return value
  if (i18n.exists(value)) return t(value)
  if (value.startsWith('Value error, ')) return systemText(value.slice(13))
  for (const [pattern, render] of rules) {
    const match = value.match(pattern)
    if (match) return render(match)
  }
  return value.includes('\n') ? value.split('\n').map(systemText).join('\n') : value
}
