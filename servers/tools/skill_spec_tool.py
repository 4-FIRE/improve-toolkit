#!/usr/bin/env python3
"""
Skill Specification Tool -- Returns skill format requirements and examples

Provides the Agent Skills specification for creating valid SKILL.md files.
Returns format requirements, field constraints, and example templates based on
https://agentskills.io/specification.md

Action: spec -- Return skill specification with examples
"""

import json
from typing import Dict, Any

from .utils import tool_error


# =============================================================================
# Skill Specification Data
# =============================================================================

SKILL_SPEC = {
    "directory_structure": """skill-name/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── ...               # Any additional files or directories""",
    
    "frontmatter_fields": {
        "name": {
            "required": True,
            "constraints": "Max 64 chars. Lowercase a-z, 0-9, hyphens only. Must not start/end with hyphen. No consecutive hyphens (--). Must match parent directory name.",
            "valid_examples": ["pdf-processing", "data-analysis", "code-review"],
            "invalid_examples": ["PDF-Processing (uppercase)", "-pdf (starts with hyphen)", "pdf--processing (consecutive hyphens)"]
        },
        "description": {
            "required": True,
            "constraints": "Max 1024 chars. Non-empty. Describe what the skill does AND when to use it. Include keywords for task matching.",
            "good_example": "Extracts text and tables from PDF files, fills PDF forms, and merges multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.",
            "poor_example": "Helps with PDFs."
        }
    },
    
    "body_guidelines": {
        "recommended_sections": ["Step-by-step instructions", "Examples of inputs and outputs", "Common edge cases"],
        "max_lines": 500,
        "max_tokens": 5000,
        "progressive_disclosure": "Keep SKILL.md concise. Move detailed reference material to references/ or assets/. Load on demand."
    },
    
    "best_practices": [
        "Extract from real hands-on tasks, not LLM-generated speculation",
        "Focus on what the agent wouldn't know: project-specific conventions, non-obvious edge cases",
        "Omit what the agent already knows (don't explain what PDFs are)",
        "Add gotchas: environment-specific facts that defy reasonable assumptions",
        "Provide defaults, not menus (pick one approach, mention alternatives briefly)",
        "Favor procedures over declarations (teach HOW to approach, not WHAT to produce)",
        "Match specificity to fragility (be prescriptive when operations are fragile)",
        "Include validation loops (self-check before proceeding)",
        "Refine with real execution traces, not just final outputs"
    ]
}

SKILL_TEMPLATE_MINIMAL = """---
name: skill-name
description: A description of what this skill does and when to use it.
---

[Instructions for how to perform the task. Include steps, examples, and gotchas.]"""

SKILL_TEMPLATE_FULL = """---
name: pdf-processing
description: Extracts text and tables from PDF files, fills PDF forms, and merges PDFs. Use when working with PDF documents.
---

## Extract PDF text

Use pdfplumber for text extraction. For scanned documents, fall back to
pdf2image with pytesseract.

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```

## Gotchas

- Some PDFs use embedded fonts with non-standard encoding — check `extract_text()` output for garbled characters
- Password-protected PDFs require `pdf.open(password="...")` first
"""


def skill_spec_tool() -> str:
    """
    Return the Agent Skills specification with format requirements and examples.
    
    Returns JSON string with specification data.
    """
    result = {
        "success": True,
        "specification": SKILL_SPEC,
        "templates": {
            "minimal": SKILL_TEMPLATE_MINIMAL,
            "full": SKILL_TEMPLATE_FULL
        },
        "usage": "Use this spec when creating new skills with skill_manage(action='create'). Ensure frontmatter has required fields (name, description) and follows naming constraints."
    }
    return json.dumps(result, ensure_ascii=False)


# =============================================================================
# OpenAI Function-Calling Schema
# =============================================================================

SKILL_SPEC_SCHEMA = {
    "name": "skill_spec",
    "description": (
        "Get the Agent Skills specification: format requirements, field constraints, "
        "and example templates for creating valid SKILL.md files. "
        "Use before skill_manage(action='create') to ensure proper format.\n\n"
        "Returns: directory structure, frontmatter fields (name/description requirements), "
        "body guidelines, best practices, and example templates.\n\n"
        "Key constraints:\n"
        "- name: 1-64 chars, lowercase a-z/0-9/hyphens, no leading/trailing/consecutive hyphens\n"
        "- description: max 1024 chars, describe both WHAT and WHEN\n"
        "- SKILL.md body: recommended <500 lines, <5000 tokens"
    ),
    "parameters": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}
