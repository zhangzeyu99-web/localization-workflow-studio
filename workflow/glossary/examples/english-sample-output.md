# English Sample Glossary Output

This example shows the intended delivery shape after extracting terms from a game language table.

| ID | CN | EN | EN2 | Why it matters |
| --- | --- | --- | --- | --- |
| 2001 | 报名 | Registration | Sign Up | The same concept appears as a standard term and a UI action. |
| 2003 | 传说 | Legend | Legendary | The noun and adjective forms should be separated. |
| 2005 | 升级 | Level Up | Upgrade | UI and system contexts often use different English wording. |

## Minimal command

```bash
python scripts/extract_glossary.py /path/to/language_table.xlsx
```

The sample CSV is documentation-only. Use an Excel file matching `templates/language_table_minimum_headers.tsv` for the runnable command.
