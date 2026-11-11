"""Terminal-only changed-file review, using curses and foreground Vim."""

import curses
import os
from pathlib import Path
import subprocess
import sys

from .git_gd import (
    diff_entry_sort_key,
    is_raster_image_entry,
    numstat_for_paths,
)


def launch_review(name, diff_args, entries):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("gd --terminal requires an interactive terminal.",
              file=sys.stderr)
        return 1
    # {{{ collect text statistics without invoking image helpers
    text_entries = []
    for entry in entries:
        if is_raster_image_entry(entry) or any(
            Path(path).suffix.lower() in {".svg", ".ico", ".avif", ".heic"}
            for path in entry.diff_paths
        ):
            continue
        try:
            entry.added, entry.deleted = numstat_for_paths(
                diff_args, entry.diff_paths
            )
        except subprocess.CalledProcessError as exc:
            print(f"gd: {exc}", file=sys.stderr)
            return exc.returncode
        if entry.added is not None and entry.deleted is not None:
            text_entries.append(entry)
    skipped = len(entries) - len(text_entries)
    text_entries.sort(key=diff_entry_sort_key)
    # }}}
    if not text_entries:
        print(f"No text changes to review. "
              f"Skipped {skipped} image/binary files.")
        return 0

    def review(screen):
        # {{{ configure a warm accent palette with terminal-default background
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        accent = positive = negative = muted = curses.A_NORMAL
        selection = curses.A_NORMAL
        selected_accent = curses.A_NORMAL
        selected_positive = selected_negative = selected_muted = curses.A_BOLD
        if curses.has_colors() and "NO_COLOR" not in os.environ:
            curses.start_color()
            background = curses.COLOR_BLACK
            try:
                curses.use_default_colors()
                background = -1
            except curses.error:
                pass
            selection_background = 234 if curses.COLORS >= 256 else background
            for pair, color in enumerate((
                173 if curses.COLORS >= 256 else curses.COLOR_YELLOW,
                curses.COLOR_GREEN, curses.COLOR_RED,
                245 if curses.COLORS >= 256 else curses.COLOR_CYAN,
            ), 1):
                curses.init_pair(pair, color, background)
                curses.init_pair(pair + 4, color, selection_background)
            curses.init_pair(9, -1 if background == -1 else curses.COLOR_WHITE,
                             selection_background)
            accent, positive, negative, muted = (
                curses.color_pair(pair) for pair in range(1, 5)
            )
            selection = curses.color_pair(9)
            selected_accent = curses.color_pair(5)
            selected_positive, selected_negative, selected_muted = (
                curses.color_pair(pair) | curses.A_BOLD
                for pair in range(6, 9)
            )
        # }}}
        selected = top = 0
        message = ""
        while True:
            # {{{ redraw a scrollable list, clipping safely on small terminals
            screen.erase()
            height, width = screen.getmaxyx()
            page = max(1, height - 7)
            top = max(0, min(top, selected))
            if selected >= top + page:
                top = selected - page + 1
            rows = [
                (0, 2, f"gd / {name}", accent | curses.A_BOLD),
                (1, 2, f"{sum(e.seen for e in text_entries)}/"
                 f"{len(text_entries)} reviewed · "
                 f"{skipped} images/binary skipped",
                 muted),
                (height - 3, 2, message, negative),
                (height - 2, 2,
                 "↑/↓ j/k move · Enter open Vim · Space mark · q quit", muted),
            ]
            for index in range(top, min(top + page, len(text_entries))):
                entry = text_entries[index]
                y = index - top + 3
                active = selection if index == selected else 0
                marker = "✓" if entry.seen else "☐"
                path = " ".join(entry.display_path.splitlines())
                # Render repository-controlled names as text, never controls.
                path = "".join(c if c.isprintable() else "?" for c in path)
                rows.extend((
                    (y, 1, " " * max(0, width - 2), active),
                    (y, 1, "›" if index == selected else " ",
                     selected_accent if index == selected else accent),
                    (y, 3, marker,
                     selected_muted if index == selected else muted),
                    (y, 5, f"+{entry.added:<5}",
                     selected_positive if index == selected else positive),
                    (y, 12, f"-{entry.deleted:<5}",
                     selected_negative if index == selected else negative),
                    (y, 19, f"{entry.status or 'M':4} {path}", active),
                ))
            for y, x, text, style in rows:
                if 0 <= y < height and x < width - 1:
                    try:
                        screen.addnstr(y, x, text, width - x - 1, style)
                    except curses.error:
                        pass
            screen.refresh()
            # }}}
            key = screen.getch()
            if key in (ord("q"), 27):
                return 0
            if key in (curses.KEY_DOWN, ord("j")):
                selected = min(len(text_entries) - 1, selected + 1)
            elif key in (curses.KEY_UP, ord("k")):
                selected = max(0, selected - 1)
            elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE):
                selected = max(0, min(
                    len(text_entries) - 1,
                    selected + (page if key == curses.KEY_NPAGE else -page),
                ))
            elif key == ord(" "):
                entry = text_entries[selected]
                entry.seen = not entry.seen
            elif key in (10, 13, curses.KEY_ENTER):
                # {{{ release the terminal to Vim, restoring curses afterward
                entry = text_entries[selected]
                curses.def_prog_mode()
                curses.endwin()
                try:
                    result = subprocess.run([
                        "git", "-c",
                        "difftool.pydifft-terminal.cmd=vim -f -d -- "
                        '"$LOCAL" "$REMOTE"',
                        "difftool", "--tool=pydifft-terminal", "--no-prompt",
                        "--trust-exit-code", "--find-renames", *diff_args,
                        "--", *entry.diff_paths,
                    ])
                    entry.seen = result.returncode == 0
                    message = (
                        "" if entry.seen else
                        f"Vim diff exited with status {result.returncode}"
                    )
                except OSError as exc:
                    message = str(exc)
                finally:
                    curses.reset_prog_mode()
                    screen.keypad(True)
                    screen.clearok(True)
                # }}}

    try:
        return curses.wrapper(review)
    except KeyboardInterrupt:
        return 130
    except curses.error as exc:
        print(f"gd: cannot initialize terminal interface: {exc}",
              file=sys.stderr)
        return 1
