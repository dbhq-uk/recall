import pytest

from recall.chunkers.markdown import chunk_markdown

KW = dict(source="brain", rel_path="notes/van.md", file_sha="sha1")


def test_heading_trail_becomes_the_context():
    md = """# Areas

## Travel

### Van conversion

#### Decision

we went with the pop-top
"""
    chunks = chunk_markdown(md, **KW)
    decision = [c for c in chunks if "pop-top" in c.content][0]
    assert decision.context == "Areas > Travel > Van conversion > Decision"


def test_THE_TRAIL_IS_ACTUALLY_EMBEDDED_not_merely_stored():
    """The design's central chunking claim. If this regresses, retrieval quality
    quietly collapses and nothing else will tell us."""
    md = "# Areas\n\n## Travel\n\n### Decision\n\n" + ("we went with the pop-top. " * 12)
    chunk = [c for c in chunk_markdown(md, **KW) if "pop-top" in c.content][0]
    assert chunk.embed_text.startswith("Areas > Travel > Decision\n\n")
    assert "pop-top" in chunk.embed_text


def test_parent_intro_prose_is_not_dropped():
    md = """# Guide

intro prose that belongs to the guide itself and is quite long enough to survive the merge floor because it keeps going and going.

## Child

child prose that is also comfortably long enough to stand on its own two feet without merging anywhere at all.
"""
    chunks = chunk_markdown(md, **KW)
    assert any("intro prose" in c.content for c in chunks)
    assert any("child prose" in c.content for c in chunks)


def test_hash_inside_a_fenced_code_block_is_not_a_heading():
    """Get this wrong and every document containing a shell snippet is shredded."""
    md = """# Real Heading

Some prose that is long enough to not merge forward into anything else at all, honestly it is.

```bash
# this is a comment, not a heading
echo hi
```

More prose after the fence, also long enough to stand alone without any merging.
"""
    chunks = chunk_markdown(md, **KW)
    contexts = {c.context for c in chunks}
    assert contexts == {"Real Heading"}
    assert not any("comment, not a heading" in (c.context or "") for c in chunks)


def test_tilde_fences_are_also_respected():
    md = "# H\n\n~~~\n# not a heading\n~~~\n\n" + ("body text here. " * 20)
    assert {c.context for c in chunk_markdown(md, **KW)} == {"H"}


def test_yaml_front_matter_is_stripped():
    md = """---
title: Van
tags: [travel]
---

# Van

body text that is long enough to be its own chunk without merging into anything.
"""
    chunks = chunk_markdown(md, **KW)
    assert not any("tags:" in c.content for c in chunks)
    assert any("body text" in c.content for c in chunks)


def test_short_sections_merge_forward():
    md = """# A

tiny.

## B

""" + ("this section is comfortably long. " * 20)
    chunks = chunk_markdown(md, **KW)
    # "tiny." is under 200 chars, so it must not survive as its own chunk.
    assert not any(c.content.strip() == "tiny." for c in chunks)
    assert any("tiny." in c.content for c in chunks)


def test_long_sections_split_with_overlap():
    para = "This is a paragraph with a decent amount of prose in it. " * 10  # ~570 chars
    md = "# Big\n\n" + "\n\n".join([para] * 6)  # ~3400 chars, over the 2000 ceiling
    chunks = chunk_markdown(md, **KW)
    assert len(chunks) > 1
    assert all(len(c.content) <= 2400 for c in chunks)  # ceiling + overlap slack
    # Overlap: consecutive chunks share some text.
    assert chunks[0].content[-50:] in chunks[1].content


def test_chunk_indices_are_sequential_from_zero():
    md = "# A\n\n" + ("prose. " * 60) + "\n\n# B\n\n" + ("more prose. " * 60)
    chunks = chunk_markdown(md, **KW)
    assert [c.chunk_idx for c in chunks] == list(range(len(chunks)))


def test_chunks_carry_source_relpath_sha_and_lang():
    md = "# A\n\n" + ("prose. " * 60)
    c = chunk_markdown(md, **KW)[0]
    assert (c.source, c.rel_path, c.file_sha, c.lang) == ("brain", "notes/van.md", "sha1", "markdown")


def test_document_with_no_headings_still_chunks():
    md = "just prose, no headings at all. " * 30
    chunks = chunk_markdown(md, **KW)
    assert len(chunks) >= 1
    assert chunks[0].context is None


def test_empty_document_yields_no_chunks():
    assert chunk_markdown("", **KW) == []
    assert chunk_markdown("\n\n   \n", **KW) == []


def test_deeper_heading_pops_the_trail_correctly():
    md = """# A

## B

""" + ("bee prose. " * 25) + """

## C

""" + ("cee prose. " * 25)
    chunks = chunk_markdown(md, **KW)
    bee = [c for c in chunks if "bee prose" in c.content][0]
    cee = [c for c in chunks if "cee prose" in c.content][0]
    assert bee.context == "A > B"
    assert cee.context == "A > C"  # B must have been popped, not accumulated
