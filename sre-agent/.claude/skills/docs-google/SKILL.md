---
name: google-docs-integration
description: Google Docs and Drive integration. Use for reading documents, searching Drive, creating docs, writing content with markdown formatting, and sharing documents.
allowed-tools: Bash(python *)
---

# Google Docs & Drive Integration

## Authentication

**IMPORTANT**: Credentials are injected automatically by a proxy layer. Just run the scripts directly.

**Note**: In direct mode, requires `google-api-python-client` and `google-auth` packages.

## Available Scripts

All scripts are in `.claude/skills/docs-google/scripts/`

### read_document.py
```bash
python .claude/skills/docs-google/scripts/read_document.py --document-id DOC_ID
```

### search_drive.py
```bash
python .claude/skills/docs-google/scripts/search_drive.py --query "incident report" [--mime-type "application/vnd.google-apps.document"] [--max-results 10]
```

### list_folder.py
```bash
python .claude/skills/docs-google/scripts/list_folder.py --folder-id FOLDER_ID
```

### create_document.py
```bash
python .claude/skills/docs-google/scripts/create_document.py --title "Postmortem Report" [--folder-id FOLDER_ID]
```

### write_content.py
```bash
python .claude/skills/docs-google/scripts/write_content.py --document-id DOC_ID --content "# Heading\n\nParagraph..." [--replace]
```

### share_document.py
```bash
python .claude/skills/docs-google/scripts/share_document.py --document-id DOC_ID --email user@example.com [--role writer]
python .claude/skills/docs-google/scripts/share_document.py --document-id DOC_ID --anyone [--role reader]
```
