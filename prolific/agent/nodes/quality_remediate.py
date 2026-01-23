"""Quality Remediation node for auto-fixing content issues.

The Quality Remediation Agent analyzes quality issues from integration
and applies fixes where possible before delivering to the user.
"""

import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from prolific.agent.state import ContentGenerationState
from prolific.schemas.artifacts import DraftChunk, QualityIssue
from prolific.services.llm import get_llm_service

logger = logging.getLogger(__name__)


class ContentPatch(BaseModel):
    """A proposed fix for a quality issue."""

    issue_id: str
    chunk_id: str
    original_text: str
    fixed_text: str
    explanation: str
    confidence: float = Field(ge=0.0, le=1.0)


class RemediationPlan(BaseModel):
    """Plan for fixing quality issues."""

    patches: list[ContentPatch] = Field(default_factory=list)
    skipped_issues: list[str] = Field(default_factory=list)


REMEDIATION_PROMPT = """You are a content editor fixing quality issues in written content.

Quality Issue to Fix:
- Type: {issue_type}
- Severity: {severity}
- Description: {description}
- Location Text: {location_text}

Surrounding Context:
{context}

Your task:
1. Identify the problematic text
2. Propose a minimal fix that addresses the issue
3. Preserve the original meaning and style
4. Only change what's necessary

Generate a patch with:
- original_text: The exact text that needs to be changed (must match exactly)
- fixed_text: The corrected version
- explanation: Brief explanation of the fix
- confidence: Your confidence this fix is correct (0.0-1.0)

If the issue cannot be fixed automatically (e.g., requires research, major rewrite), set confidence to 0.0.
"""

ISSUE_TYPES_AUTO_FIXABLE = {
    "style_mismatch": True,
    "poor_transition": True,
    "unclear_writing": True,
    "missing_context": False,
    "repetition": True,
    "missing_citation": False,
    "contradiction": False,
    "factual_error": False,
}


async def analyze_and_create_issues(
    state: ContentGenerationState,
    llm_service,
) -> list[QualityIssue]:
    """Analyze content and create structured quality issues.

    This converts the string warnings from integration into
    structured QualityIssue objects for remediation.
    """
    warnings = state.get("warnings", [])
    draft_chunks = {str(c.id): c for c in state.get("draft_chunks", [])}
    chapter_briefs = {str(b.chapter_id): b for b in state.get("chapter_briefs", [])}

    quality_issues = []

    for warning in warnings:
        warning_lower = warning.lower()

        if "repetition" in warning_lower or "similarity" in warning_lower:
            issue_type = "repetition"
            severity = "major"
        elif "style" in warning_lower:
            issue_type = "style_mismatch"
            severity = "minor"
        elif "transition" in warning_lower:
            issue_type = "poor_transition"
            severity = "minor"
        elif "consistency" in warning_lower or "contradiction" in warning_lower:
            issue_type = "contradiction"
            severity = "major"
        elif "citation" in warning_lower:
            issue_type = "missing_citation"
            severity = "major"
        else:
            issue_type = "unclear_writing"
            severity = "minor"

        issue = QualityIssue(
            id=uuid4(),
            issue_type=issue_type,
            severity=severity,
            description=warning,
            auto_fixable=ISSUE_TYPES_AUTO_FIXABLE.get(issue_type, False),
        )
        quality_issues.append(issue)

    return quality_issues


async def generate_patch(
    llm_service,
    issue: QualityIssue,
    chunk: DraftChunk,
) -> ContentPatch | None:
    """Generate a fix patch for a quality issue.

    Args:
        llm_service: LLM service for generation
        issue: The quality issue to fix
        chunk: The draft chunk containing the issue

    Returns:
        ContentPatch if a fix was generated, None otherwise
    """
    location_text = issue.location_text or ""
    if not location_text and chunk:
        location_text = chunk.content[:500]

    context = chunk.content[:2000] if chunk else ""

    system_message = SystemMessage(
        content=REMEDIATION_PROMPT.format(
            issue_type=issue.issue_type,
            severity=issue.severity,
            description=issue.description,
            location_text=location_text,
            context=context,
        )
    )

    user_message = HumanMessage(content="Generate the fix patch.")

    try:
        result = await llm_service.invoke_with_structured_output(
            messages=[system_message, user_message],
            output_schema=ContentPatch,
            tier="research",
            temperature=0.2,
        )

        if result.confidence < 0.5:
            logger.info(f"Low confidence patch for issue {issue.id}, skipping")
            return None

        result.issue_id = str(issue.id)
        result.chunk_id = str(chunk.id) if chunk else ""

        return result

    except Exception as e:
        logger.warning(f"Failed to generate patch for issue {issue.id}: {e}")
        return None


def apply_patch(chunk: DraftChunk, patch: ContentPatch) -> DraftChunk:
    """Apply a patch to a draft chunk.

    Args:
        chunk: The draft chunk to modify
        patch: The patch to apply

    Returns:
        Modified draft chunk
    """
    if patch.original_text not in chunk.content:
        logger.warning(f"Original text not found in chunk, cannot apply patch")
        return chunk

    new_content = chunk.content.replace(patch.original_text, patch.fixed_text, 1)

    updated_chunk = chunk.model_copy()
    updated_chunk.content = new_content
    updated_chunk.word_count = len(new_content.split())
    updated_chunk.revision_number += 1

    return updated_chunk


async def quality_remediate_node(state: ContentGenerationState) -> dict:
    """Auto-fix quality issues where possible.

    This node:
    1. Converts warnings to structured QualityIssue objects
    2. Filters for auto-fixable issues
    3. Generates and applies patches
    4. Updates draft chunks with fixes

    Args:
        state: Current workflow state

    Returns:
        Dict with updated draft_chunks and quality_issues
    """
    logger.info("=== QUALITY REMEDIATION PHASE ===")

    warnings = state.get("warnings", [])
    draft_chunks = state.get("draft_chunks", [])
    chapter_briefs = {str(b.chapter_id): b for b in state.get("chapter_briefs", [])}

    if not warnings:
        logger.info("No quality issues to remediate")
        return {
            "messages": [AIMessage(content="No quality issues to fix.")],
        }

    llm_service = get_llm_service()

    quality_issues = await analyze_and_create_issues(state, llm_service)
    logger.info(f"Identified {len(quality_issues)} quality issues")

    auto_fixable = [i for i in quality_issues if i.auto_fixable]
    logger.info(f"Auto-fixable issues: {len(auto_fixable)}")

    if not auto_fixable:
        return {
            "quality_issues": quality_issues,
            "messages": [
                AIMessage(
                    content=f"Found {len(quality_issues)} quality issues, none are auto-fixable."
                )
            ],
        }

    chunks_by_id = {str(c.id): c for c in draft_chunks}
    updated_chunks = []
    fixes_applied = 0

    for issue in auto_fixable[:10]:
        if not issue.location_chapter_id:
            continue

        target_chunks = [
            c for c in draft_chunks
            if str(c.chapter_id) == str(issue.location_chapter_id)
        ]

        if not target_chunks:
            continue

        chunk = target_chunks[0]

        patch = await generate_patch(llm_service, issue, chunk)
        if patch:
            updated_chunk = apply_patch(chunk, patch)
            if updated_chunk.content != chunk.content:
                chunks_by_id[str(chunk.id)] = updated_chunk
                issue.fix_applied = True
                fixes_applied += 1
                logger.info(f"Applied fix for issue {issue.id}")

    updated_chunks = list(chunks_by_id.values())

    logger.info(f"Quality remediation complete: {fixes_applied} fixes applied")

    return {
        "draft_chunks": updated_chunks,
        "quality_issues": quality_issues,
        "messages": [
            AIMessage(
                content=f"Quality remediation: {fixes_applied} fixes applied out of {len(auto_fixable)} auto-fixable issues."
            )
        ],
    }
