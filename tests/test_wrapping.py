import pytest

from pydifftools.match_spaces import run
from pydifftools.wrap_sentences import classify_lines, wrap_prose, wr


@pytest.mark.parametrize(
    "block",
    [
        "# A heading that is much longer than the requested wrapping width\n",
        "A long heading that must remain on one line\n==========================================\n",
        "\x60\x60\x60python\nx = '$$ and some very long text'\n\n  # keep spaces  \n\x60\x60\x60\n",
        "\x60\x60\x60\x60{anything}\n\x60\x60\x60\n\narbitrary $$ <tag> contents\n\x60\x60\x60\x60\n",
        "  ~~~unknown\n  text that is much longer than the width\n\n  ~~~\n",
        "---\ntitle: A long title that should not wrap\n\ncustom: value\n---\n",
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
    "Name     Value\n-------  -------\nalpha    a very long value\nbeta     another value\n",
    "-------  -------\nalpha    a very long value\nbeta     another value\n-------  -------\n",
    "--------------------------------\nName     Value\n-------  -----------------------\nalpha    a long value\n         continued here\n\nbeta     another value\n--------------------------------\n",
    "-------  -----------------------\nalpha    a long value\n         continued here\n\nbeta     another value\n-------  -----------------------\n",
    "| Name | Value |\n| :--- | ---: |\n| alpha | a very long value |\n",
    "Name | Value\n:--- | ---:\nalpha | a very long value\n",
    "+-------+-----------------------+\n| Name  | Value                 |\n+=======+=======================+\n| alpha | a very long value     |\n|       |                       |\n|       | another paragraph     |\n+-------+-----------------------+\n",
]


@pytest.mark.parametrize("table", TABLES)
@pytest.mark.parametrize("caption_before", [False, True])
def test_tables_and_captions_are_preserved(tmp_path, table, caption_before):
    caption = "Table: A long caption whose original wrapping\n    must be retained.\n"
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
        "\\section{A very long heading with {nested} braces\nand another line}\n"
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
    assert classify_lines(text) == [(False, line) for line in text.splitlines(True)]


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
        "added words, with $x$ and several more words about an extended explanation "
        * 3
    )
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
def test_wmatch_local_width_excludes_headers_and_keeps_indentation(tmp_path, indent):
    old = tmp_path / "old.md"
    new = tmp_path / "new.md"
    # Distant wide prose and a long heading must not determine the local width.
    distant = ("A distant paragraph with much longer lines " * 4 + "\n") * 12
    local = "".join(indent + f"Local line {j:02} has several ordinary words\n" for j in range(12))
    source = distant + "\n# " + "heading " * 30 + "\n\n" + local
    changed_line = indent + "Local line 10 has " + "many extra ordinary words " * 12
    changed_line += "several ordinary words\n"
    changed = source.replace(indent + "Local line 10 has several ordinary words\n", changed_line)
    old.write_text(source)
    new.write_text(changed)
    run([str(old), str(new)])
    result = new.read_text()
    assert "# " + "heading " * 30 in result
    changed_lines = [line for line in result.splitlines() if "many extra" in line]
    assert changed_lines and all(line.startswith(indent) for line in changed_lines)


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
    before = "The introduction contains a long explanation with several ordinary words"
    after = "and the ending contains another long explanation with ordinary words."
    context = REFERENCE * 5
    old.write_text(context + before + " REMOVE\n" + after + "\n")
    new.write_text(context + before + " " + after + "\n")
    run([str(old), str(new)])
    assert new.read_text() == context + wrap_prose(before + " " + after + "\n", 40)


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
