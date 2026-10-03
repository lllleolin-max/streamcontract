# Public evidence path redactions

Before publication, root preserved the original eight machine-path evidence files outside this repository and redacted local absolute prefixes in their public copies. `{repository}`, `{portfolio-workspace}` and `{user-home}` are explicit path placeholders, not claims that these spellings were the original commands.

This affects command arrays and traceback file locations in `validation-results.json`, `validation-results-0.2.0.json`, `repair-evidence/checkpoint-domain-after.json`, and the signed-zero evidence's `before-tests.json`, `cli-tests-before.log`, `grouping-tests-before.log`, `signed-zero-before.json` and `signed-zero-after.json`. Actual exits, observations, exception messages, checksums, original scores, historical commit identifiers and library sources were preserved. Original full machine-path records remain local and are excluded from public release attachments.

Use README/VALIDATION relative commands or the public independent reproduction scripts to repeat checks; historical command-array placeholders need resolution in your checkout. This documentation-only cleanup is not another implementation iteration or an additional passing test. Earlier historical Git commits may still contain their original machine-path spellings; no review history was rewritten.
