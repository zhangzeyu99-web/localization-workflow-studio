"""Do not treat a review handoff or declared unresolved issue as acceptance."""
import re


def unresolved_review_detail(row: dict) -> str:
    findings = row.get('unresolved_issues', [])
    if not isinstance(findings, list):
        return 'unresolved_issues must be an array'
    if findings:
        return 'Review declares unresolved issues: ' + str(findings)
    reason = str(row.get('review_reason') or row.get('reason') or '')
    # Legacy records used prose instead of a structured FLAG. Only explicit
    # handoff phrases are recognized; this is not a free-text semantic checker.
    if re.search(r'提交主控\s*QA|待主控(?:确认|复核|处理)|pending\s+(?:QA|main\s+review)', reason, re.I):
        return 'Review contains an unresolved QA handoff: ' + reason
    return ''
