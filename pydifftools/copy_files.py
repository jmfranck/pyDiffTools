# from https://tex.stackexchange.com/questions/24542/create-list-of-all-external-files-used-by-master-latex-document
"""Copy figures used by document."""
import os
import shutil
from pathlib import Path, PurePosixPath
import subprocess
import sys


def copy_image_files(ROOT_TEX, project_name, TARGET_DIR, include_suppinfo):
    all_files = []
    with open(ROOT_TEX + ".tex", "r") as fp:
        alltext = fp.read()
    if r"\RequirePackage{snapshot}" not in alltext:
        raise RuntimeError(
            "You haven't called \\RequirePackage{snapshot} in the root tex file.  I can't do my thing without that!"
        )
    with open(ROOT_TEX + ".dep", "r") as f:
        for line in f:
            if "*{file}" in line:
                value = line.split("{")[2].split("}")
                source = value[0]
                _, e = os.path.splitext(source)
                if len(e) == 0 and os.path.exists(source + ".tex"):
                    all_files.append(source + ".tex")
                    print("found", source + ".tex")
                elif os.path.exists(source):
                    all_files.append(source)
            elif "*{package}" in line:
                value = line.split("{")[2].split("}")
                source = value[0]
                _, e = os.path.splitext(source)
                if len(e) == 0 and os.path.exists(source + ".sty"):
                    all_files.append(source + ".sty")
                    print("found", source + ".sty")
                elif os.path.exists(source):
                    all_files.append(source)
            else:
                continue
    os.makedirs(TARGET_DIR, exist_ok=True)
    if include_suppinfo:
        all_files.append("suppinfo.pdf")
        all_files.append("suppinfo.aux")
    for source in all_files:
        d, f = os.path.split(source)
        b, _ = os.path.splitext(source)
        if b == ROOT_TEX:
            f = f.replace(ROOT_TEX, "ms")
        newpath = TARGET_DIR / d / f
        print("copying", source, PurePosixPath(newpath))
        if len(d) > 0:
            print("going to make", newpath.parents[0])
            os.makedirs(newpath.parents[0], exist_ok=True)
        shutil.copy(source, PurePosixPath(newpath))
    shutil.copy(ROOT_TEX + ".tex", os.path.join(TARGET_DIR, "ms.tex"))


if __name__ == "__main__":
    copy_image_files()
    os.chdir(Path.cwd().parent)
    output_filename = f"{project_name}_forarxiv.tgz"
    # create tar process
    tar = subprocess.Popen(
        ["tar", "cf", "-", TARGET_DIR.name], stdout=subprocess.PIPE
    )
    # create gzip process, using tar's stdout as its stdin
    gzip = subprocess.Popen(
        ["gzip", "-9"], stdin=tar.stdout, stdout=subprocess.PIPE
    )
    # close tar's stdout so it doesn't hang around waiting for input
    tar.stdout.close()
    # write gzip's stdout to a file
    with open(output_filename, "wb") as fp:
        shutil.copyfileobj(gzip.stdout, fp)
    gzip.stdout.close()
