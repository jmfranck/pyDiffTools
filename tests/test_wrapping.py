import json
import subprocess

import pytest

from pydifftools.match_spaces import run
from pydifftools.wrap_sentences import (
    classify_lines,
    markdown_blocks,
    wrap_blocks,
    wrap_prose,
    wr,
)


@pytest.mark.parametrize(
    "block",
    [
        "# A heading that is much longer than the requested wrapping width\n",
        (
            "A long heading that must remain on one line\n"
            "==========================================\n"
        ),
        (
            "```python\n"
            "x = '$$ and some very long text'\n"
            "\n"
            "  # keep spaces  \n"
            "```\n"
        ),
        (
            "````{anything}\n"
            "```\n"
            "\n"
            "arbitrary $$ <tag> contents\n"
            "````\n"
        ),
        "  ~~~unknown\n  text that is much longer than the width\n\n  ~~~\n",
        (
            "---\n"
            "title: A long title that should not wrap\n"
            "\n"
            "custom: value\n"
            "---\n"
        ),
        "![a very long figure description](image.png)\n",
        "<div>\nlong content with $$ symbols\n\nmore content\n</div>\n",
    ],
)
def test_wr_preserves_blocks_and_wraps_adjacent_prose(tmp_path, block):
    path = tmp_path / "document.md"
    prose = "Ordinary prose with enough words to need several wrapped lines.\n"
    path.write_text(block + prose)
    wr(str(path), wrapnumber=20)
    assert path.read_text() == block + wrap_prose(prose, 20)
    first = path.read_text()
    wr(str(path), wrapnumber=20)
    assert path.read_text() == first


@pytest.mark.parametrize("suffix", [".md", ".qmd"])
def test_unclosed_fence_preserved_through_eof(tmp_path, suffix):
    path = tmp_path / ("document" + suffix)
    text = "\x60\x60\x60python\n\n  x = 'very long content with $$ and <tags>'"
    path.write_text(text)
    wr(str(path), wrapnumber=10)
    assert path.read_text() == text


TABLES = [
    (
        "Name     Value\n"
        "-------  -------\n"
        "alpha    a very long value\n"
        "beta     another value\n"
    ),
    (
        "-------  -------\n"
        "alpha    a very long value\n"
        "beta     another value\n"
        "-------  -------\n"
    ),
    (
        "--------------------------------\n"
        "Name     Value\n"
        "-------  -----------------------\n"
        "alpha    a long value\n"
        "         continued here\n"
        "\n"
        "beta     another value\n"
        "--------------------------------\n"
    ),
    (
        "-------  -----------------------\n"
        "alpha    a long value\n"
        "         continued here\n"
        "\n"
        "beta     another value\n"
        "-------  -----------------------\n"
    ),
    "| Name | Value |\n| :--- | ---: |\n| alpha | a very long value |\n",
    "Name | Value\n:--- | ---:\nalpha | a very long value\n",
    (
        "+-------+-----------------------+\n"
        "| Name  | Value                 |\n"
        "+=======+=======================+\n"
        "| alpha | a very long value     |\n"
        "|       |                       |\n"
        "|       | another paragraph     |\n"
        "+-------+-----------------------+\n"
    ),
]


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("caption_before", [False, True])
def test_tables_and_captions_are_preserved(tmp_path, table, caption_before):
    caption = (
        "Table: A long caption whose original wrapping\n"
        "    must be retained.\n"
    )
    block = (
        caption + "\n" + table if caption_before else table + "\n" + caption
    )
    prose = "Surrounding prose that should wrap into multiple lines.\n"
    text = prose + "\n" + block + "\n" + prose
    path = tmp_path / "table.md"
    path.write_text(text)
    wr(str(path), wrapnumber=18)
    assert path.read_text() == wrap_prose(
        prose, 18
    ) + "\n" + block + "\n" + wrap_prose(prose, 18)
    assert all(
        not allowed for allowed, line in classify_lines(block) if line.strip()
    )


def test_pipes_and_horizontal_rules_do_not_hide_prose(tmp_path):
    prose = "Ordinary prose | with a pipe | and enough words to wrap.\n"
    path = tmp_path / "plain.md"
    path.write_text(prose + "\n---\n\n" + prose)
    wr(str(path), wrapnumber=18)
    assert path.read_text() == wrap_prose(
        prose, 18
    ) + "\n---\n\n" + wrap_prose(prose, 18)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$$a  + b$$\n", "$$\na  + b\n$$\n"),
        ("$$\na  + b\n\n  + c\n$$\n", "$$\na  + b\n\n  + c\n$$\n"),
        ("before $$a + b$$ after\n", "before\n$$\na + b\n$$\nafter\n"),
        ("$$a$$ $$b$$", "$$\na\n$$\n \n$$\nb\n$$"),
        (
            r"An escaped \$ is ordinary text.",
            r"An escaped \$ is ordinary text.",
        ),
    ],
)
def test_display_math_only_adds_boundary_newlines(tmp_path, text, expected):
    path = tmp_path / "math.md"
    path.write_text(text)
    wr(str(path), wrapnumber=100)
    assert path.read_text() == expected
    wr(str(path), wrapnumber=100)
    assert path.read_text() == expected


def test_latex_headers_and_environments(tmp_path):
    block = (
        "\\section{A very long heading with {nested} braces\n"
        "and another line}\n"
        "\\begin{align}\na &= b\n\nc &= d\n\\end{align}\n"
    )
    prose = "Ordinary prose with enough words to need wrapping.\n"
    path = tmp_path / "document.tex"
    path.write_text(block + prose)
    wr(str(path), wrapnumber=20)
    assert path.read_text() == block + wrap_prose(
        prose, 20, filetype="latex", indent_amount=4
    )


def test_inline_math_prefers_both_boundaries():
    assert (
        wrap_prose("alpha beta $x$ gamma delta epsilon", 18).splitlines()[0]
        == "alpha beta $x$"
    )
    assert (
        wrap_prose("alpha beta $longvariable$ gamma delta", 18).splitlines()[0]
        == "alpha beta"
    )
    assert (
        wrap_prose(r"alpha beta \$x\$ gamma delta epsilon", 20).splitlines()[0]
        == r"alpha beta \$x\$"
    )
    # Preferences do not make a long expression indivisible.
    assert "\n" in wrap_prose("$alpha + beta + gamma + delta + epsilon$", 15)


def test_math_and_table_contents_are_not_parsed_as_html(tmp_path):
    text = (
        "$$\na <symbol> b\n# literal math content\n\nc = d\n$$\n\n"
        "| Name | Value |\n| --- | --- |\n| $$ | <symbol> |\n"
    )
    path = tmp_path / "document.md"
    path.write_text(text)
    wr(str(path), wrapnumber=10)
    assert path.read_text() == text


def test_single_column_pipe_table():
    text = "| Heading |\n| --- |\n| a long cell |\n"
    assert classify_lines(text) == [
        (False, line) for line in text.splitlines(True)
    ]


def test_separate_tables_do_not_exclude_intervening_prose():
    prose = "This prose must remain eligible for wrapping.\n"
    text = TABLES[0] + "\n" + prose + "\n" + TABLES[0]
    assert (True, prose) in classify_lines(text)


REFERENCE = (
    "The first reference line has enough words\n"
    "Another reference line has similar length\n"
    "The final reference line ends this text.\n"
)


@pytest.mark.parametrize("operation", ["insert", "replace"])
def test_wmatch_reuses_wr_rules_and_preserves_other_lines(tmp_path, operation):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    addition = (
        "added words, with $x$ and several more words about"
        " an extended explanation "
    ) * 3
    old.write_text(REFERENCE)
    first, rest = REFERENCE.split("\n", 1)
    changed = first.replace(
        "reference",
        addition + ("reference" if operation == "insert" else "replacement"),
        1,
    )
    new.write_text(changed + "\n" + rest)
    run([str(old), str(new)])
    expected = wrap_prose(changed + "\n", 40) + rest
    assert new.read_text() == expected
    run([str(old), str(new)])
    assert new.read_text() == expected


def test_wmatch_small_edit_and_missing_final_newline(tmp_path):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    old.write_text(REFERENCE.rstrip("\n"))
    changed = REFERENCE.replace("first", "very first").rstrip("\n")
    new.write_text(changed)
    run([str(old), str(new)])
    assert new.read_text() == changed


@pytest.mark.parametrize("indent", ["", "    "])
def test_wmatch_local_width_excludes_headers_and_keeps_indentation(
    tmp_path, indent
):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    # Distant wide prose and a long heading must not determine the local width.
    distant = ("A distant paragraph with much longer lines " * 4 + "\n") * 12
    local = "".join(
        indent + f"Local line {j:02} has several ordinary words\n"
        for j in range(12)
    )
    source = distant + "\n# " + "heading " * 30 + "\n\n" + local
    changed_line = (
        indent + "Local line 10 has " + "many extra ordinary words " * 12
    )
    changed_line += "several ordinary words\n"
    changed = source.replace(
        indent + "Local line 10 has several ordinary words\n", changed_line
    )
    old.write_text(source)
    new.write_text(changed)
    run([str(old), str(new)])
    result = new.read_text()
    assert "# " + "heading " * 30 in result
    changed_lines = [
        line for line in result.splitlines() if "many extra" in line
    ]
    assert changed_lines and all(
        line.startswith(indent) for line in changed_lines
    )


def test_wmatch_fallback_width_and_long_word(tmp_path):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    old.write_text("Start end.\n")
    long_word = "https://example.org/" + "x" * 150
    text = "Start " + "extra words " * 20 + long_word + " end.\n"
    new.write_text(text)
    run([str(old), str(new)])
    assert new.read_text() == wrap_prose(text, 80)
    assert long_word in new.read_text()


def test_wmatch_deletion_that_joins_long_lines(tmp_path):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    before = (
        "The introduction contains a long explanation with "
        "several ordinary words"
    )
    after = (
        "and the ending contains another long explanation with ordinary words."
    )
    context = REFERENCE * 5
    old.write_text(context + before + " REMOVE\n" + after + "\n")
    new.write_text(context + before + " " + after + "\n")
    run([str(old), str(new)])
    assert new.read_text() == context + wrap_prose(
        before + " " + after + "\n", 40
    )


@pytest.mark.parametrize(
    "block",
    [
        TABLES[0],
        "\x60\x60\x60python\nvalue = 'old'\n\x60\x60\x60\n",
        "$$\nold\n$$\n",
    ],
)
def test_wmatch_does_not_overflow_wrap_protected_text(tmp_path, block):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    old.write_text(REFERENCE + "\n" + block)
    changed = block.replace("old", "extended " * 30).replace(
        "alpha", "extended " * 30
    )
    new.write_text(REFERENCE + "\n" + changed)
    run([str(old), str(new)])
    assert " ".join(["extended"] * 29) in new.read_text()


@pytest.mark.parametrize("suffix", [".md", ".qmd"])
@pytest.mark.parametrize(
    "opening, continuation, heading",
    [
        (":   ", "    ", "Definition term\n"),
        (":\t", "    ", "Definition term\n\n"),
        ("- ", "  ", ""),
        ("* ", "  ", ""),
        ("+ ", "  ", ""),
        ("12. ", "    ", ""),
        ("1) ", "   ", ""),
        ("> ", "> ", ""),
        (">    ", ">    ", ""),
        ("> ", "", ""),
        ("> ", "  ", ""),
    ],
)
def test_container_wrapping_and_idempotence(
    tmp_path,
    suffix,
    opening,
    continuation,
    heading,
):
    path = tmp_path / ("container" + suffix)
    body = "alpha beta gamma delta epsilon zeta eta theta iota kappa\n"
    source = heading + opening + "alpha beta gamma delta\n"
    source += continuation + "epsilon zeta eta theta iota kappa\n"
    margin = max(len(opening.expandtabs(4)), len(continuation))
    wrapped = wrap_prose(body, 24 - margin).splitlines(keepends=True)
    expected = heading + opening + wrapped[0]
    expected += "".join(continuation + line for line in wrapped[1:])
    path.write_text(source)
    wr(str(path), wrapnumber=24)
    assert path.read_text() == expected
    wr(str(path), wrapnumber=24)
    assert path.read_text() == expected


@pytest.mark.parametrize(
    "prefix, heading",
    [
        ("> ", ""),
        ("    ", "Term\n:   introduction\n\n"),
        ("  ", "- introduction\n\n"),
    ],
)
@pytest.mark.parametrize(
    "protected",
    [
        "```python\nvalue = 'a long literal with : > - and $$'\n```\n",
        "```html\n<unclosed-literal> with many words\n```\n",
        "| Name | Value |\n| --- | --- |\n| alpha | a very long value |\n",
        "$$\na  + b\n\n  + c\n$$\n",
        "<div>\na very long literal with arbitrary whitespace\n</div>\n",
    ],
)
def test_nested_protected_blocks(prefix, heading, protected):
    source = heading + "".join(
        prefix + line if line.strip() else prefix.rstrip() + line
        for line in protected.splitlines(keepends=True)
    )
    assert wrap_blocks(markdown_blocks(source), 20) == source


def test_nested_containers_keep_terms_items_and_paragraphs_separate():
    source = (
        "Term\n:   first definition paragraph with several ordinary words\n"
        "\n    - a nested item with several ordinary words\n"
        "      > a nested quotation with several ordinary words\n"
        "\n:   a second definition with several ordinary words\n"
        "\nOutside prose with several ordinary words\n"
    )
    result = wrap_blocks(markdown_blocks(source), 25)
    assert result.startswith("Term\n:   first definition\n")
    assert "\n    - a nested item with\n" in result
    assert "\n      > a nested quotation\n" in result
    assert "\n:   a second definition\n" in result
    assert "\n\nOutside prose" in result
    assert wrap_blocks(markdown_blocks(result), 25) == result


@pytest.mark.parametrize("marker", ["- ", "12. ", "> ", ":   "])
def test_wmatch_container_overflow_and_unchanged_neighbors(tmp_path, marker):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    indent = marker if marker == "> " else " " * len(marker)
    heading = "Term\n" if marker.startswith(":") else ""
    reference_lines = REFERENCE.splitlines(keepends=True)
    source = heading + marker + reference_lines[0]
    source += "".join(indent + line for line in reference_lines[1:])
    source += "\nUnchanged paragraph with its original line breaks.\n"
    old.write_text(source)
    changed = source.replace(
        "reference", "extra ordinary words " * 15 + "reference", 1
    )
    new.write_text(changed)
    run([str(old), str(new)])
    result = new.read_text()
    assert result.endswith(
        "\nUnchanged paragraph with its original line breaks.\n"
    )
    body = result[len(heading) :].split("\n\n")[0].splitlines()
    assert body[0].startswith(marker)
    assert all(line.startswith(indent) for line in body[1:])
    assert max(map(len, body)) < 70
    assert result.count(marker.strip()) == (len(body) if marker == "> " else 1)
    run([str(old), str(new)])
    assert new.read_text() == result


def test_colon_captions_and_literal_markers_remain_protected():
    source = (
        TABLES[0] + "\n: A caption with several words that must stay intact\n"
    )
    assert wrap_blocks(markdown_blocks(source), 12) == source
    source = "```\n> not a quote\n- not a list\n: not a definition\n```\n"
    assert wrap_blocks(markdown_blocks(source), 12) == source


@pytest.mark.parametrize(
    "source",
    [
        "> alpha beta gamma delta epsilon\nlazy continuation\n>\n"
        "> ```\n> literal code here\n> ```\n",
        "> alpha beta gamma delta epsilon\n>\n"
        ">     indented code with several words that must not wrap\n",
        ">> nested quotation with several ordinary words to wrap\n",
        "Term\n:   first paragraph with several ordinary words\n\n"
        "    second paragraph with several ordinary words\n",
        "- first list item with several ordinary words\n"
        "  - nested list item with several ordinary words\n"
        "- second list item with several ordinary words",
    ],
)
def test_container_wrapping_preserves_pandoc_structure(source):
    result = wrap_blocks(markdown_blocks(source), 20)
    documents = []
    for text in (source, result):
        rendered = subprocess.run(
            ["pandoc", "-f", "markdown", "-t", "json"],
            input=text,
            text=True,
            capture_output=True,
            check=True,
        )
        documents.append(
            json.loads(rendered.stdout.replace('"SoftBreak"', '"Space"'))
        )
    assert documents[0] == documents[1]
    assert wrap_blocks(markdown_blocks(result), 20) == result
