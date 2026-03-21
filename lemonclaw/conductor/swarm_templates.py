"""Single-instance swarm templates for Conductor.

These templates keep LemonClaw on the current SSOT path:
- one runtime / one ledger / one operator surface
- multiple specialist roles coordinated inside the same instance
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class SwarmRoleTemplate:
    id: str
    label: str
    skills: tuple[str, ...] = ()
    prompt: str = ""


@dataclass(frozen=True)
class SwarmTeamTemplate:
    id: str
    label: str
    keywords: tuple[str, ...] = ()
    roles: tuple[SwarmRoleTemplate, ...] = ()

    def role_by_id(self, role_id: str) -> SwarmRoleTemplate | None:
        return next((role for role in self.roles if role.id == role_id), None)


_SEO_TEMPLATE = SwarmTeamTemplate(
    id="seo_content_studio",
    label="SEO Content Studio",
    keywords=("seo", "serp", "keyword", "outline", "article", "internal link"),
    roles=(
        SwarmRoleTemplate(
            id="lead",
            label="Lead Planner",
            skills=("planning", "coordination"),
            prompt="You are the lead planner for an SEO content swarm. Keep the work scoped, evidence-based, and sequenced clearly.",
        ),
        SwarmRoleTemplate(
            id="researcher",
            label="Researcher",
            skills=("research", "analysis", "seo"),
            prompt="You are the researcher. Focus on search intent, competitive observations, facts, and citations. Do not drift into final polish.",
        ),
        SwarmRoleTemplate(
            id="writer",
            label="Writer",
            skills=("writing", "seo", "content"),
            prompt="You are the writer. Turn approved research into structured, publication-ready copy with crisp hierarchy and no unnecessary filler.",
        ),
        SwarmRoleTemplate(
            id="reviewer",
            label="Reviewer",
            skills=("review", "qa", "editing"),
            prompt="You are the reviewer. Check for gaps, factual drift, clarity issues, and handoff readiness. Be concise and concrete.",
        ),
    ),
)

_ECOM_TEMPLATE = SwarmTeamTemplate(
    id="ecommerce_ops_team",
    label="Ecommerce Ops Team",
    keywords=("sku", "listing", "ecommerce", "shop", "product page", "review", "ad creative"),
    roles=(
        SwarmRoleTemplate(
            id="lead",
            label="Ops Lead",
            skills=("planning", "coordination"),
            prompt="You are the ecommerce ops lead. Keep deliverables aligned to one store or campaign and maintain crisp task boundaries.",
        ),
        SwarmRoleTemplate(
            id="analyst",
            label="SKU Analyst",
            skills=("analysis", "research", "ecommerce"),
            prompt="You are the SKU analyst. Focus on product facts, gaps, customer signals, and merchandising angles.",
        ),
        SwarmRoleTemplate(
            id="copywriter",
            label="Listing Copywriter",
            skills=("writing", "marketing", "ecommerce"),
            prompt="You are the listing copywriter. Produce clear, conversion-oriented product copy grounded in approved facts.",
        ),
        SwarmRoleTemplate(
            id="reviewer",
            label="QA Reviewer",
            skills=("review", "qa", "editing"),
            prompt="You are the QA reviewer. Catch unsupported claims, factual drift, policy issues, and missing assets before delivery.",
        ),
    ),
)

_MARKETING_TEMPLATE = SwarmTeamTemplate(
    id="marketing_campaign_room",
    label="Marketing Campaign Room",
    keywords=("campaign", "marketing", "landing page", "ads", "creative", "funnel", "launch"),
    roles=(
        SwarmRoleTemplate(
            id="lead",
            label="Campaign Lead",
            skills=("planning", "coordination"),
            prompt="You are the campaign lead. Keep the work tied to one campaign goal, one audience, and one measurable output set.",
        ),
        SwarmRoleTemplate(
            id="strategist",
            label="Strategist",
            skills=("research", "strategy", "marketing"),
            prompt="You are the strategist. Clarify audience, offer, positioning, and channel logic before copy or creative is finalized.",
        ),
        SwarmRoleTemplate(
            id="copywriter",
            label="Copywriter",
            skills=("writing", "marketing", "content"),
            prompt="You are the copywriter. Turn approved strategy into strong campaign copy with sharp hooks and clear CTAs.",
        ),
        SwarmRoleTemplate(
            id="reviewer",
            label="Launch Reviewer",
            skills=("review", "qa", "editing"),
            prompt="You are the launch reviewer. Check message consistency, execution gaps, and readiness for handoff.",
        ),
    ),
)

_CONTENT_TEMPLATE = SwarmTeamTemplate(
    id="content_studio",
    label="Content Studio",
    keywords=("script", "video", "content", "topic", "title", "hook", "repurpose"),
    roles=(
        SwarmRoleTemplate(
            id="lead",
            label="Studio Lead",
            skills=("planning", "coordination"),
            prompt="You are the studio lead. Keep the content package aligned to one deliverable set and maintain role handoffs clearly.",
        ),
        SwarmRoleTemplate(
            id="scout",
            label="Topic Scout",
            skills=("research", "content", "analysis"),
            prompt="You are the topic scout. Focus on audience interest, source material, angles, and supporting evidence.",
        ),
        SwarmRoleTemplate(
            id="writer",
            label="Script Writer",
            skills=("writing", "content", "storytelling"),
            prompt="You are the script writer. Convert approved angles into usable scripts, outlines, titles, or hooks.",
        ),
        SwarmRoleTemplate(
            id="reviewer",
            label="Content Reviewer",
            skills=("review", "qa", "editing"),
            prompt="You are the content reviewer. Check flow, clarity, consistency, and handoff completeness.",
        ),
    ),
)

_GENERAL_TEMPLATE = SwarmTeamTemplate(
    id="general_swarm",
    label="General Swarm",
    keywords=(),
    roles=(
        SwarmRoleTemplate(
            id="lead",
            label="Lead",
            skills=("planning", "coordination"),
            prompt="You are the lead. Break work into clear lanes and keep the final output coherent.",
        ),
        SwarmRoleTemplate(
            id="researcher",
            label="Researcher",
            skills=("research", "analysis"),
            prompt="You are the researcher. Gather facts, inspect context, and identify risks or missing information.",
        ),
        SwarmRoleTemplate(
            id="maker",
            label="Maker",
            skills=("writing", "coding", "execution"),
            prompt="You are the maker. Produce the concrete deliverable based on approved inputs.",
        ),
        SwarmRoleTemplate(
            id="reviewer",
            label="Reviewer",
            skills=("review", "qa"),
            prompt="You are the reviewer. Verify quality, catch issues, and tighten the final handoff.",
        ),
    ),
)

_TEMPLATES: tuple[SwarmTeamTemplate, ...] = (
    _SEO_TEMPLATE,
    _ECOM_TEMPLATE,
    _MARKETING_TEMPLATE,
    _CONTENT_TEMPLATE,
    _GENERAL_TEMPLATE,
)


def list_swarm_templates() -> list[SwarmTeamTemplate]:
    return list(_TEMPLATES)


def get_swarm_template(template_id: str | None) -> SwarmTeamTemplate | None:
    if not template_id:
        return None
    return next((template for template in _TEMPLATES if template.id == template_id), None)


def infer_swarm_template(message: str, required_skills: Iterable[str] | None = None) -> SwarmTeamTemplate:
    haystack = " ".join([message.lower(), *[str(skill).lower() for skill in (required_skills or [])]])
    for template in _TEMPLATES:
        if template is _GENERAL_TEMPLATE:
            continue
        if any(keyword in haystack for keyword in template.keywords):
            return template
    return _GENERAL_TEMPLATE


def infer_role_hint(template: SwarmTeamTemplate, description: str, required_skills: Iterable[str] | None = None) -> str:
    haystack = " ".join([description.lower(), *[str(skill).lower() for skill in (required_skills or [])]])
    if any(token in haystack for token in ("review", "qa", "verify", "audit", "check", "proofread")):
        return "reviewer" if template.role_by_id("reviewer") else template.roles[-1].id
    if any(token in haystack for token in ("research", "analyze", "inspect", "compare", "investigate")):
        for candidate in ("researcher", "analyst", "strategist", "scout"):
            if template.role_by_id(candidate):
                return candidate
    if any(token in haystack for token in ("write", "draft", "script", "build", "implement", "compose")):
        for candidate in ("writer", "copywriter", "maker"):
            if template.role_by_id(candidate):
                return candidate
    return template.roles[0].id
