import html, re
import httpx
from .security import decrypt
from .services import setting


class ExternalError(Exception):
    def __init__(self, message, status=None, retry_after=None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def telegram_config(db):
    c = setting(db, "telegram")
    if not c.get("token"):
        raise ExternalError("Telegram 尚未配置")
    return {**c, "bot_token": decrypt(c["token"]), "secret": decrypt(c["secret"])}


def tg(db, method, payload=None, files=None):
    c = telegram_config(db)
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            url = f"https://api.telegram.org/bot{c['bot_token']}/{method}"
            r = (
                client.post(url, data=payload, files=files)
                if files
                else client.post(url, json=payload or {})
            )
        body = r.json()
    except (httpx.HTTPError, ValueError):
        raise ExternalError("Telegram 网络异常，结果可能未知")
    if not body.get("ok"):
        description = str(body.get("description", "请求失败"))[:300].replace(
            c["bot_token"], "[REDACTED]"
        )
        raise ExternalError(
            "Telegram: " + description,
            r.status_code,
            (body.get("parameters") or {}).get("retry_after"),
        )
    return body["result"]


def telegram_text(text, entities):
    """将 UTF-16 偏移实体转换为安全 HTML；未知实体只保留文字。"""
    raw = text.encode("utf-16-le")
    starts = {}
    ends = {}
    tags = {
        "bold": ("b", ""),
        "italic": ("i", ""),
        "underline": ("u", ""),
        "strikethrough": ("s", ""),
        "code": ("code", ""),
        "pre": ("pre", ""),
        "blockquote": ("blockquote", ""),
    }
    for e in entities:
        start = e.get("offset", 0) * 2
        end = start + e.get("length", 0) * 2
        tag, attrs = tags.get(e.get("type"), ("", ""))
        if e.get("type") == "text_link" and re.match(r"^https?://", e.get("url", "")):
            tag = "a"
            attrs = ' href="' + html.escape(e["url"], quote=True) + '"'
        if tag:
            starts.setdefault(start, []).append((end, f"<{tag}{attrs}>"))
            ends.setdefault(end, []).append((start, f"</{tag}>"))
    out = []
    # Decode each Unicode code point while preserving Telegram's UTF-16 offsets.
    offset = 0
    for ch in text:
        for _, v in sorted(ends.get(offset, []), reverse=True):
            out.append(v)
        for _, v in sorted(starts.get(offset, []), reverse=True):
            out.append(v)
        out.append(html.escape(ch))
        offset += len(ch.encode("utf-16-le"))
    for _, v in sorted(ends.get(offset, []), reverse=True):
        out.append(v)
    return "".join(out)


def entities_markdown(text, entities):
    # HTML is parsed as data and converted to Markdown; client HTML remains disabled.
    from html.parser import HTMLParser

    class Convert(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out = []
            self.links = []

        def handle_starttag(self, t, attrs):
            if t == "a":
                self.out.append("[")
                self.links.append(dict(attrs).get("href", ""))
            else:
                self.out.append(
                    {
                        "b": "**",
                        "i": "*",
                        "s": "~~",
                        "code": "`",
                        "pre": "\n```\n",
                        "blockquote": "\n> ",
                    }.get(t, "")
                )

        def handle_endtag(self, t):
            if t == "a":
                self.out.append("](" + self.links.pop().replace(")", "%29") + ")")
            else:
                self.out.append(
                    {"b": "**", "i": "*", "s": "~~", "code": "`", "pre": "\n```\n"}.get(
                        t, ""
                    )
                )

        def handle_data(self, d):
            self.out.append(d)

    parser = Convert()
    parser.feed(telegram_text(text, entities))
    return "".join(parser.out)


def telegram_chunks(body):
    # Parse Markdown and emit readable plain text, retaining links and picture URLs.
    from markdown_it import MarkdownIt

    tokens = MarkdownIt("commonmark", {"html": False}).parse(body)
    out = []
    for t in tokens:
        if t.type == "inline":
            for c in t.children or []:
                if c.type in ("text", "code_inline"):
                    out.append(c.content)
                elif c.type == "image":
                    out.append("\n🖼 " + str(c.attrGet("src")) + "\n")
                elif c.type == "link_close":
                    out.append(" ")
                elif c.type == "link_open":
                    out.append(str(c.attrGet("href")) + " ")
                elif c.type in ("softbreak", "hardbreak"):
                    out.append("\n")
            out.append("\n")
        elif t.type in ("fence", "code_block"):
            out.append(t.content + "\n")
        elif t.type == "list_item_open":
            out.append("• ")
    text = "".join(out).strip() or body
    # Conservative chunks stay below Telegram's UTF-16 text limit even with emoji.
    return [text[i : i + 1800] for i in range(0, len(text), 1800)] or [""]


def telegram_html(body):
    """Only Telegram-supported HTML; Markdown image links remain clickable."""
    from html.parser import HTMLParser
    from .security import render

    class Convert(HTMLParser):
        def __init__(self):
            super().__init__()
            self.out = []

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag in ("strong", "em", "code", "pre", "blockquote"):
                self.out.append("<" + {"strong": "b", "em": "i"}.get(tag, tag) + ">")
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.out.append("<b>")
            elif tag == "a":
                self.out.append(
                    '<a href="' + html.escape(attrs.get("href", ""), quote=True) + '">'
                )
            elif tag == "img":
                self.out.append(
                    '<a href="'
                    + html.escape(attrs.get("src", ""), quote=True)
                    + '">🖼 '
                    + html.escape(attrs.get("alt") or "图片")
                    + "</a>"
                )
            elif tag == "li":
                self.out.append("• ")
            elif tag == "br":
                self.out.append("\n")

        def handle_endtag(self, tag):
            if tag in ("strong", "em", "code", "pre", "blockquote", "a"):
                self.out.append("</" + {"strong": "b", "em": "i"}.get(tag, tag) + ">")
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.out.append("</b>\n")
            elif tag in ("p", "li", "ul", "ol"):
                self.out.append("\n")

        def handle_data(self, data):
            self.out.append(html.escape(data))

    p = Convert()
    p.feed(render(body))
    return "".join(p.out).strip()
