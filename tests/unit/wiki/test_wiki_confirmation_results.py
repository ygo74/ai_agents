"""Human write acknowledgements stay separate from fenced model tool results."""

import pytest

from ai_agent_lab.wiki.adapters.capabilities.results import (
    WIKI_UNTRUSTED_CONTRACT,
    WikiCommentPostedResult,
    WikiPageDeletedResult,
    WikiPageDraftedResult,
    WikiPageWrittenResult,
    WikiToolResultRenderer,
)
from ai_agent_lab.wiki.adapters.http.confirmation_results import WikiConfirmationResultRenderer


def written(**changes):
    return WikiPageWrittenResult(
        page_id="98490", space_key="MFS", title="My first space", version=4,
        url="https://wiki.example/spaces/MFS/pages/98490",
    ).model_copy(update=changes)


def test_saved_page_is_readable_and_model_fences_remain_intact():
    result = written()
    human = WikiConfirmationResultRenderer().render(result)
    assert human == (
        "Page saved successfully.\n\n"
        "- Title: My first space\n- Page: 98490\n- Space: MFS\n- Version: 4\n\n"
        "[Open page](<https://wiki.example/spaces/MFS/pages/98490>)"
    )
    assert "UNTRUSTED_" not in human
    assert WIKI_UNTRUSTED_CONTRACT not in human
    assert '"page_id"' not in human
    model = WikiToolResultRenderer().render(result)
    assert WIKI_UNTRUSTED_CONTRACT in model
    assert '<UNTRUSTED_' in model
    assert 'label="title of 98490"' in model
    assert "My first space" in model


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (WikiPageDeletedResult(page_id="p1"), "Page deleted successfully.\n\n- Page: p1"),
        (WikiCommentPostedResult(page_id="p1", comment_id="c1"),
         "Comment posted successfully.\n\n- Page: p1\n- Comment: c1"),
    ],
)
def test_other_confirmed_writes_have_readable_acknowledgements(result, expected):
    assert WikiConfirmationResultRenderer().render(result) == expected


@pytest.mark.security
def test_third_party_title_and_identifiers_cannot_insert_html_or_markdown():
    human = WikiConfirmationResultRenderer().render(written(
        title='<img src=x onerror=alert(1)>\n# ![link](javascript:alert(1))',
        space_key="[space](https://other.example)",
    ))
    assert '<img' not in human
    assert '&lt;img src=x onerror=alert\\(1\\)&gt;' in human
    assert r'\# \!\[link\]\(javascript:alert\(1\)\)' in human
    assert r'- Space: \[space\]\(https://other\.example\)' in human
    assert '\n#' not in human


@pytest.mark.security
@pytest.mark.parametrize("url", [
    "", "javascript:alert(1)", "data:text/html,test", "//wiki.example/page",
    "https://", "https://[invalid", "https://wiki.example/\npage",
    "https://user:secret@wiki.example/page",
])
def test_unsafe_or_malformed_optional_links_are_not_displayed(url):
    human = WikiConfirmationResultRenderer().render(written(url=url))
    assert "Page saved successfully." in human
    assert "Open page" not in human
    assert "secret" not in human


def test_url_markup_characters_are_encoded():
    human = WikiConfirmationResultRenderer().render(written(url='https://wiki.example/a(b)><img>'))
    assert '[Open page](<https://wiki.example/a%28b%29%3E%3Cimg%3E>)' in human


def test_result_sequences_render_each_acknowledgement():
    renderer = WikiConfirmationResultRenderer()
    results = [WikiPageDeletedResult(page_id="p1"), WikiCommentPostedResult(page_id="p2", comment_id="c1")]
    assert renderer.render(results) == "\n\n".join(renderer.render(result) for result in results)


def test_non_write_results_do_not_fall_back_to_unfenced_tool_output():
    with pytest.raises(TypeError, match="Unsupported Wiki confirmation result"):
        WikiConfirmationResultRenderer().render(WikiPageDraftedResult(draft_reference="draft1", body="Internal draft"))
