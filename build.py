#!/usr/bin/env python3
"""Render the iximiuz Labs unikernels tutorial as a single local HTML page.

Usage: ./build.py   (writes site/index.html, then serve with ./serve.sh)

The source markdown is left untouched. Local adaptations (setup section and
"on this machine" notes) are injected from LOCAL_NOTES below.
"""
import html
import re
import shutil
from pathlib import Path

import markdown
import yaml
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.util import ClassNotFound

HERE = Path(__file__).resolve().parent
SRC = HERE / "unikernels-intro-93976514"
OUT = HERE / "site"
LAB = HERE / "lab"

SETUP = f"""
## Local Setup

::local-box
This section and the green "On this machine" boxes are not part of the original tutorial.
They replace the iximiuz playground box with your own machine (Debian 13, bare metal, KVM available).

The tutorial's commands are written for bash. Your login shell is fish, which handles most of them,
but if one misbehaves just run `bash` first and stay in it.
::

### 1. Install Packages

QEMU, the kernel build dependencies, and a few tools the tutorial calls (`kvm-ok`, `bsdcat`, `dpkg -L nginx-common`).
`make`, `gcc`, `unzip` and `git` are already installed.

```sh
sudo apt update
sudo apt install -y qemu-system-x86 cpu-checker \\
  libncurses-dev bison flex \\
  libarchive-tools nginx-common
```

### 2. Install urunc

The container runtime used in the Docker part of the tutorial (v0.8.1, same as the playground).
Two static binaries go to `/usr/local/bin`; nothing else on the system is touched.

```sh
cd "$(mktemp -d)"
curl -fsSLO https://github.com/urunc-dev/urunc/releases/download/v0.8.1/urunc_static_amd64
curl -fsSLO https://github.com/urunc-dev/urunc/releases/download/v0.8.1/containerd-shim-urunc-v2_static_amd64
echo "ab9fc0306b396f358b771e263eba625cadab4b03827dc869da56399a0b0df152  urunc_static_amd64" | sha256sum --check
echo "619e14ae0cfac3e66afbc42119c4cb58856627a7febc1231d260d4399b04fc37  containerd-shim-urunc-v2_static_amd64" | sha256sum --check
sudo install -D -m0755 urunc_static_amd64 /usr/local/bin/urunc
sudo install -D -m0755 containerd-shim-urunc-v2_static_amd64 /usr/local/bin/containerd-shim-urunc-v2
cd -
```

### 3. Docker 28 or Newer

The Docker part of the tutorial needs Docker Engine 28 or newer. Check yours:

```sh
docker version --format '{{{{.Server.Version}}}}'
```

::remark-box
---
kind: warning
---
With older versions (Debian 13 ships 26.1.5 as `docker.io`) the unikernel container starts but has no network:
`curl` cannot connect, and the container logs show `No network interface attached!`.
Docker up to v27 attaches the container's network from a `prestart` OCI hook, which urunc v0.8.1 does not run.
::

To replace Debian's packages with Docker's own (existing images and containers in `/var/lib/docker` are kept; run this in `bash`):

```sh
sudo apt remove -y docker.io docker-cli docker-buildx containerd runc
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian trixie stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 4. Workspace

The playground pre-creates `nginx/` and `sources/` in the home directory.
Here they are already created under `lab/` by `setup-workspace.sh` (pinned to the same commits as the playground).
To start over from scratch at any time:

```sh
rm -rf {LAB}
{HERE}/setup-workspace.sh
```

### 5. Open a Terminal in the Lab

Everything below assumes this directory plays the role of the playground's HOME:

```sh
cd {LAB}
```
"""

CLEANUP = """
## Local Cleanup

::local-box
Not part of the original tutorial: how to undo everything once you are done.
::

```sh
docker container stop unikernel
docker image rm lab/nginx-unikernel:latest
sudo rm /usr/local/bin/urunc /usr/local/bin/containerd-shim-urunc-v2
```

The `docker run busybox ps` step leaves a stopped busybox container behind; remove it with `docker container rm` if you care.
The apt packages from the setup can go with `sudo apt remove`, and the workspace is just the `lab/` directory.
"""

# (prefix of the source line to insert before, markdown to insert)
LOCAL_NOTES = [
    ("## Requirements", SETUP),
    ("## Summary", CLEANUP),
    (
        "The playground box is pre-initialized with",
        f"""::local-box
Your "HOME" for this tutorial is `{LAB}`. Make sure your terminal is there before continuing.
::
""",
    ),
    (
        "After about 2 minutes, you should see the build succeed",
        """::local-box
On this 24-core machine the full build takes about 15 seconds. `git status` lists one extra
`nginx_qemu-x86_64.dbg.uk_pcpuvar.bin.cmd` file compared to the listing below.
::
""",
    ),
    (
        "The format of this kernel is an ELF executable",
        """::local-box
Debian has no uncompressed `/boot/vmlinux`. For the Linux side of the comparisons below use the compressed image instead:

```sh
file /boot/vmlinuz-$(uname -r)
du -hL /boot/vmlinuz-$(uname -r) /lib/x86_64-linux-gnu/libc.so.6
```

`file` reports a bzImage rather than an ELF, and `/usr/sbin/nginx` is not installed (only `nginx-common` is, to avoid starting a web server on port 80).
::
""",
    ),
    (
        "Both of those requirements can conveniently be checked",
        """::local-box
On Debian `kvm-ok` lives in `/usr/sbin`, so run it as `sudo kvm-ok`.
The nested virtualization warning below does not apply: you are on bare metal, so boot times should be close to the ones shown.
::
""",
    ),
    (
        "The OCI images produced by Bunny have the peculiarity",
        """::local-box
With the current `bunny:latest` frontend the `com.urunc.unikernel.cmdline` label is no longer set;
the command line is stored as the image's regular `Cmd` instead. The other labels match.
::
""",
    ),
    (
        "Then send a HTTP request to that IP address",
        """::local-box
If other containers are running on the default bridge, the address will not be `172.17.0.2`.
Use whatever the previous command printed.
::
""",
    ),
]

FENCE_OPEN = re.compile(r"^```\s*(\w+)?\s*(?:\[([^\]]+)\])?\s*(?:\{([\d,\-\s]+)\})?\s*$")
DIRECTIVE = re.compile(r"^::([a-z-]+)\s*$")
LEXER_ALIASES = {"sh": "bash", "conf": "ini", "html": "http"}

placeholders = {}


def stash(markup):
    key = f"PLACEHOLDER{len(placeholders):04d}X"
    placeholders[key] = markup
    return f"\n\n{key}\n\n"


def parse_hl(spec):
    lines = []
    for part in (spec or "").split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            lines.extend(range(int(a), int(b) + 1))
        elif part:
            lines.append(int(part))
    return lines


def render_code(info, body):
    lang, title, hl = FENCE_OPEN.match(info).groups()
    try:
        lexer = get_lexer_by_name(LEXER_ALIASES.get(lang, lang)) if lang else TextLexer()
    except ClassNotFound:
        lexer = TextLexer()
    code = "\n".join(body) + "\n"
    rendered = highlight(code, lexer, HtmlFormatter(cssclass="hl", hl_lines=parse_hl(hl)))
    kind = "cmd" if lang == "sh" else "out"
    head = f'<div class="code-title">{html.escape(title)}</div>' if title else ""
    copy = '<button class="copy" type="button">copy</button>' if kind == "cmd" else ""
    return f'<div class="code {kind}">{head}{copy}{rendered}</div>'


def read_meta(lines, i):
    """Parses an optional `---` delimited header following a directive line."""
    if i >= len(lines) or lines[i].strip() != "---":
        return {}, "", i
    j = i + 1
    while lines[j].strip() != "---":
        j += 1
    raw = "\n".join(lines[i + 1 : j])
    meta = {}
    for line in lines[i + 1 : j]:
        m = re.match(r"^:?([\w-]+):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2)
    return meta, raw, j + 1


def read_body(lines, i):
    """Collects raw lines up to the `::` closing the current directive."""
    body, depth, in_fence = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence:
            if DIRECTIVE.match(line):
                depth += 1
            elif line.strip() == "::":
                if depth == 0:
                    return body, i + 1
                depth -= 1
        body.append(line)
        i += 1
    raise ValueError("unterminated directive")


def inline(text):
    rendered = markdown.markdown(text.strip())
    return re.sub(r"^<p>|</p>$", "", rendered)


def split_tabs(body, names):
    parts, current, in_fence = {}, None, False
    for line in body:
        if line.startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("#") and line[1:].strip() in names:
            current = line[1:].strip()
            parts[current] = []
        elif current:
            parts[current].append(line)
    return parts


def convert(lines):
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while not lines[j].startswith("```"):
                j += 1
            out.append(stash(render_code(line, lines[i + 1 : j])))
            i = j + 1
            continue
        m = DIRECTIVE.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        name = m.group(1)
        meta, raw_meta, i = read_meta(lines, i + 1)
        body, i = read_body(lines, i)
        if name == "simple-task":
            continue
        if name == "image-box":
            style = f' style="max-width:{meta["max-width"]}"' if "max-width" in meta else ""
            caption = inline("\n".join(body))
            caption = f"<figcaption>{caption}</figcaption>" if caption else ""
            out.append(stash(
                f'<figure><img src="{meta["src"]}" alt="{html.escape(meta.get("alt", ""))}"{style}>'
                f"{caption}</figure>"
            ))
        elif name == "tabbed":
            tabs = yaml.safe_load(raw_meta)["tabs"]
            parts = split_tabs(body, {t["name"] for t in tabs})
            buttons = "".join(
                f'<button type="button" class="tab{" active" if n == 0 else ""}">{html.escape(t["title"])}</button>'
                for n, t in enumerate(tabs)
            )
            out.append(stash(f'<div class="tabs"><div class="tab-bar">{buttons}</div>'))
            for n, t in enumerate(tabs):
                out.append(stash(f'<div class="tab-panel{" active" if n == 0 else ""}">'))
                out.append(convert(parts[t["name"]]))
                out.append(stash("</div>"))
            out.append(stash("</div>"))
        elif name in ("details-box", "hint-box"):
            label = "Hint: " if name == "hint-box" else ""
            out.append(stash(
                f'<details class="box {name}"><summary>{label}{inline(meta.get("summary", "Details"))}</summary>'
                '<div class="box-body">'
            ))
            out.append(convert(body))
            out.append(stash("</div></details>"))
        else:
            kind = "local" if name == "local-box" else meta.get("kind", "note")
            label = {"local": "On this machine", "warning": "Warning", "info": "Info"}.get(kind, "Note")
            out.append(stash(f'<div class="box remark {kind}"><div class="box-label">{label}</div>'))
            out.append(convert(body))
            out.append(stash("</div>"))
    return "\n".join(out)


def toc_html(tokens):
    items = []
    for h2 in tokens:
        items.append(f'<a class="l2" href="#{h2["id"]}">{h2["name"]}</a>')
        for h3 in h2["children"]:
            items.append(f'<a class="l3" href="#{h3["id"]}">{h3["name"]}</a>')
    return "\n".join(items)


def main():
    text = (SRC / "index.md").read_text()
    _, front, body = text.split("\n---\n", 2) if text.startswith("---\n") else ("", "", text)
    front = yaml.safe_load(text.split("\n---\n", 1)[0].removeprefix("---\n"))
    body = text.split("\n---\n", 1)[1]

    lines = body.split("\n")
    for prefix, note in LOCAL_NOTES:
        at = next(n for n, line in enumerate(lines) if line.startswith(prefix))
        lines[at:at] = note.strip("\n").split("\n") + [""]

    md = markdown.Markdown(extensions=["footnotes", "tables", "sane_lists", "toc"],
                           extension_configs={"toc": {"toc_depth": "2-3", "permalink": "#"}})
    content = md.convert(convert(lines))
    for key, markup in placeholders.items():
        content, n = re.subn(rf"<p>{key}</p>", lambda _: markup, content)
        assert n == 1, f"{key} substituted {n} times"
    assert "PLACEHOLDER" not in content

    page = (HERE / "template.html").read_text()
    page = page.replace("{{title}}", html.escape(front["title"]))
    page = page.replace("{{pygments}}", HtmlFormatter(style="monokai").get_style_defs(".hl"))
    page = page.replace("{{toc}}", toc_html(md.toc_tokens))
    page = page.replace("{{content}}", content)

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(page)
    shutil.copytree(SRC / "__static__", OUT / "__static__", dirs_exist_ok=True)
    print(f"wrote {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
