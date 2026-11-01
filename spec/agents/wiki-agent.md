# Wiki agent

## Purpose and role

The Wiki agent helps a project-team member find and understand documentation,
answer questions with page sources, assess whether a page is stale, and prepare
content for review. Publishing, replacing, commenting on, or deleting a page is
a separate operation with its own permission and confirmation behavior.

The application owns the Wiki graph, skills, permission policy, confirmation
tickets, MCP dialect, and capability filtering. LangChain/LangGraph supplies
the agent framework. The runtime supplies the shared native graph binding,
managed HTTP worker, conversation engine, approval limits, and generic MCP
client mechanics.

## Capabilities

| Group | Capabilities | Effect |
|---|---|---|
| Answer and analyse | `answer_from_wiki`, `summarise_page`, `assess_page_freshness` | Answers are grounded in retrieved pages and cite sources. Freshness is computed from page dates, not guessed by a model. No write. |
| Find and read | `search_wiki`, `get_page`, `get_page_children`, `list_spaces`, `get_comments`, `get_page_history` | Search returns references and short excerpts; reading a page is a separate call. History returns revision metadata, not old page bodies. |
| Prepare content | `draft_page_content` | Stores a proposed page body and returns a reference. It does not publish or change a wiki page. |
| Publish or change | `create_page`, `update_page`, `add_comment`, `delete_page` | Changes shared wiki state and is checked by permission and confirmation policy. |

Search and answer behavior is intentionally bounded. Search does not return full
page bodies; the agent reads selected pages explicitly. An answer that cannot be
grounded in accessible pages must say that the evidence is missing rather than
present an inference as a fact. Freshness classification uses deterministic
date thresholds.

## Write policy and confirmation

`create_page` and `update_page` use the `wiki:author` permission. `delete_page`
uses the stronger `wiki:manage` permission; authoring does not imply management.
`add_comment` uses `wiki:comment`. A draft has no remote side effect and does
not require the authoring permission.

The code-owned security floor fixes `update_page` and `delete_page` at high risk
with confirmation always required. `create_page` requires confirmation by
default but its posture is configurable. `add_comment` is not confirmed by
default; a deployment may choose to require confirmation. The model cannot
change these rules.

Drafting and publishing are separate capabilities. A draft is stored and the
model receives an opaque reference. Publishing resolves the exact stored body,
so it cannot be rewritten after the person reviews or confirms it. Updating a
page also carries the version the draft was based on. If a colleague changed
the page in between, the update fails rather than overwriting that edit.

When a LangGraph tool is interrupted, the Wiki resolver creates a person-facing
ticket and records the authorized request in the ledger. A later confirmation
command is handled before graph execution. The ticket is scoped to caller and
conversation, is consumed once, and runs the stored arguments. Abandoned
approval state and grants are cleared before a later turn.

## Identity, content, and MCP limits

Wiki HTTP requests require an authenticated caller. The service derives the
LangGraph checkpoint key from the verified subject and conversation. The Wiki
MCP client supplies the caller's selected credentials or HTTP headers so the
source system can apply that person's page restrictions. Authentication
identifies the caller; application permissions and source ACLs still govern
what they may do.

Titles, page bodies, comments, and search results are untrusted data. The agent
fences them before reasoning. They do not become trusted instructions, policy,
or permission grants.

The `WIKI_MCP_READ_ONLY` setting removes write capabilities before the model
sees them. This matches the remote server's read-only mode. A missing remote
tool is likewise filtered out instead of being advertised and failing only
after selection. The current Wiki HTTP service exposes OpenAI Chat Completions;
the runtime's stream binding does not mean this service exposes HTTP streaming.

## Acceptance

- Answers and summaries use only content the caller can retrieve and identify
  the supporting pages.
- Page search does not silently retrieve every full page or bypass source ACLs.
- Freshness is calculated from dates using deterministic thresholds.
- Drafting changes no remote wiki state; publishing uses the exact reviewed
  draft and detects concurrent page edits.
- High-risk update and delete operations cannot bypass the security floor.
- Read-only configuration never advertises Wiki write capabilities.

See the [Wiki HTTP and conversation guide](../../doc/users/wiki-agent-http.md), the
[Wiki user guide](../../doc/users/wiki-agent-reference.md), [LangGraph integration](../integrations/langchain-langgraph.md),
and [MCP server boundaries](../integrations/mcp-server-hosting.md). The
delivered inventory is in [`agent.yaml`](../../config/agents/wiki/agent.yaml);
tool posture is defined by [`operations.py`](../../agents/wiki/src/ai_agent_lab/wiki/application/operations.py)
and [`security_floor.py`](../../agents/wiki/src/ai_agent_lab/wiki/domain/policies/security_floor.py).
