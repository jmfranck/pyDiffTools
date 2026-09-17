import pytest

from pydifftools.wrap_sentences import check_prose, wr, wrap_prose, wrchk
from test_wrapping import TABLES


def test_wr_output_is_always_clean():
    prose = (
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    wrapped = wrap_prose(prose, 30)
    assert check_prose(wrapped, 30, 20) == []


def test_shorter_user_break_is_clean():
    # The user broke earlier than wr's own choice would -- always fine.
    text = (
        "This is some\n"
        "ordinary prose\n"
        "with quite a few words that\n"
        "need wrapping across several\n"
        "lines for a real test.\n"
    )
    assert check_prose(text, 30, 20) == []


def test_word_moved_to_next_line_is_clean():
    # wr would wrap this as "...prose\nwith quite a few words that\n"
    # "need wrapping.". Moving "that" down to the final line (breaking
    # one word earlier than wr would, with the rest still fitting) is a
    # legitimate user-added break.
    text = (
        "This is some ordinary prose\n"
        "with quite a few words\n"
        "that need wrapping.\n"
    )
    assert check_prose(text, 30, 20) == []


def test_overlong_line_is_flagged_with_line_number_and_word():
    text = (
        "This is some ordinary prose with quite a few words that\n"
        "need wrapping across several\n"
        "lines for a real test.\n"
    )
    issues = check_prose(text, 30, 20)
    assert len(issues) == 1
    line, message = issues[0]
    assert line == 1
    assert "with" in message
    assert "too long" in message


def test_sentence_ends_mid_line_is_flagged():
    text = "First sentence ends here. Second sentence starts right after.\n"
    issues = check_prose(text, 60, 20)
    assert len(issues) == 1
    line, message = issues[0]
    assert line == 1
    assert "mid-line" in message
    assert r"\ " in message


def test_backslash_space_abbreviation_is_not_flagged():
    text = "See etc.\\ more.\n"
    assert check_prose(text, 60, 20) == []


def test_plain_space_after_abbreviation_still_flagged():
    # Without the escape, the crude heuristic can't tell "etc." from a
    # real sentence end -- a known, pre-existing limitation shared with wr.
    text = "See etc. more things here.\n"
    issues = check_prose(text, 60, 20)
    assert len(issues) == 1


@pytest.mark.parametrize("table", TABLES)
def test_protected_tables_are_never_flagged(tmp_path, table):
    path = tmp_path / "doc.md"
    path.write_text(table)
    wrchk(str(path), wrapnumber=5)


def test_protected_code_and_math_are_never_flagged(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "```python\n"
        "x = 'a very long line that would overflow any small width'\n"
        "```\n"
        "$$\n"
        "a + b + c + d + e + f + g + h + i + j + k + l + m + n\n"
        "$$\n"
    )
    wrchk(str(path), wrapnumber=5)


def test_wrchk_raises_systemexit_on_violations(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit) as excinfo:
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    assert excinfo.value.code == 1


def test_wrchk_clean_after_wr(tmp_path):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    wr(str(path), wrapnumber=30)
    wrchk(str(path), wrapnumber=30)


def test_wrchk_reports_line_and_file_name(tmp_path, capsys):
    path = tmp_path / "doc.md"
    path.write_text(
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit):
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    out = capsys.readouterr().out
    assert f"{path}:1:" in out


def test_wrchk_latex_document(tmp_path):
    path = tmp_path / "doc.tex"
    path.write_text(
        "\\section{Title}\n"
        "This is some ordinary prose with quite a few words that need"
        " wrapping across several lines for a real test.\n"
    )
    with pytest.raises(SystemExit):
        wrchk(str(path), wrapnumber=30, punctuation_slop=20)
    wr(str(path), wrapnumber=30)
    wrchk(str(path), wrapnumber=30)
