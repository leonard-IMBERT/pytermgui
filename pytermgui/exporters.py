"""This module provides various methods and utilities to turn TIM into HTML & SVG."""

# TODO: The HTML and SVG implementations are completely independent at the moment,
#       which is pretty annoying to maintain. It would be great to consolidate them
#       at some point.

from __future__ import annotations

from copy import deepcopy
from html import escape
from typing import Iterator

from .colors import Color
from .markup import StyledText, Token, tim
from .terminal import get_terminal
from .widgets import Widget

MARGIN = 15
BODY_MARGIN = 70
CHAR_WIDTH = 0.62
CHAR_HEIGHT = 1.15
FONT_SIZE = 15

FONT_WIDTH = FONT_SIZE * CHAR_WIDTH
FONT_HEIGHT = FONT_SIZE * CHAR_HEIGHT * 1.1

HTML_FORMAT = """\
<html>
    <head>
        <style>
            body {{
                --ptg-background: {background};
                --ptg-foreground: {foreground};
                color: var(--ptg-foreground);
                background-color: var(--ptg-background);
            }}
            a {{
                text-decoration: none;
                color: inherit;
            }}
            code {{
                font-size: {font_size}px;
                font-family: Menlo, 'DejaVu Sans Mono', consolas, 'Courier New', monospace;
                line-height: 1.2em;
            }}
            .ptg-position {{
                position: absolute;
            }}
{styles}
        </style>
    </head>
    <body>
        <pre class="ptg">
            <code>
{content}
            </code>
        </pre>
    </body>
</html>"""

SVG_MARGIN_LEFT = 0
TEXT_MARGIN_LEFT = 20

TEXT_MARGIN_TOP = 35
SVG_MARGIN_TOP = 20

SVG_FORMAT = f"""\
<svg width="{{total_width}}" height="{{total_height}}"
    viewBox="0 0 {{total_width}} {{total_height}}" xmlns="http://www.w3.org/2000/svg">
    <!-- Generated by PyTermGUI -->
    <style type="text/css">
        text.{{prefix}} {{{{
            font-size: {FONT_SIZE}px;
            font-family: Menlo, 'DejaVu Sans Mono', consolas, 'Courier New', monospace;
        }}}}

        .{{prefix}}-title {{{{
            font-family: 'arial';
            fill: #94999A;
            font-size: 13px;
            font-weight: bold;
        }}}}
{{stylesheet}}
    </style>
    {{chrome}}
{{code}}
</svg>"""

_STYLE_TO_CSS = {
    "bold": "font-weight: bold",
    "italic": "font-style: italic",
    "dim": "opacity: 0.7",
    "underline": "text-decoration: underline",
    "strikethrough": "text-decoration: line-through",
    "overline": "text-decoration: overline",
}


__all__ = ["token_to_css", "to_html"]


def _get_cls(prefix: str | None, index: int) -> str:
    """Constructs a class identifier with the given prefix and index."""

    return "ptg" + ("-" + prefix if prefix is not None else "") + str(index)


def _generate_stylesheet(document_styles: list[list[str]], prefix: str | None) -> str:
    """Generates a '\\n' joined CSS stylesheet from the given styles."""

    stylesheet = ""
    for i, styles in enumerate(document_styles):
        stylesheet += "\n." + _get_cls(prefix, i) + " {" + "; ".join(styles) + "}"

    return stylesheet


def _generate_index_in(lst: list[list[str]], item: list[str]) -> int:
    """Returns the given item's index in the list, len(lst) if not found."""

    index = len(lst)

    if item in lst:
        return lst.index(item)

    return index


# Note: This whole routine will be massively refactored in an upcoming update,
#       once StyledText has a bit of a better way of managing style attributes.
#       Until then we must ignore some linting issues :(.
def _get_spans(  # pylint: disable=too-many-locals
    line: str,
    vertical_offset: float,
    horizontal_offset: float,
    include_background: bool,
) -> Iterator[tuple[str, list[str]]]:
    """Creates `span` elements from the given line, yields them with their styles.

    Args:
        line: The ANSI line of text to use.

    Yields:
        Tuples of the span text (more on that later), and a list of CSS styles applied
        to it.  The span text is in the format `<span{}>content</span>`, and it doesn't
        yet have the styles formatted into it.
    """

    def _adjust_pos(
        position: int | None, scale: float, offset: float, digits: int = 2
    ) -> float:
        """Adjusts a given position for the HTML canvas' scale."""

        if position is None:
            return 0

        return round(position * scale + offset / FONT_SIZE, digits)

    position = None

    for span in StyledText.group_styles(line):
        styles = []
        if include_background:
            styles.append("background-color: var(--ptg-background)")

        has_link = False
        has_inverse = False

        for token in sorted(span.tokens, key=lambda token: token.is_color()):
            if token.is_plain():
                continue

            if Token.is_cursor(token):
                if token.value != position:
                    # Yield closer if there is already an active positioner
                    if position is not None:
                        yield "</div>", []

                    adjusted = (
                        _adjust_pos(token.x, CHAR_WIDTH, horizontal_offset),
                        _adjust_pos(token.y, CHAR_HEIGHT, vertical_offset),
                    )

                    yield (
                        "<div class='ptg-position'"
                        + f" style='left: {adjusted[0]}em; top: {adjusted[1]}em'>"
                    ), []

                    position = token.value

            elif token.is_hyperlink():
                has_link = True
                yield f"<a href='{token.value}'>", []

            elif token.is_style() and token.value == "inverse":
                has_inverse = True

                # Add default inverted colors, in case the text doesn't have any
                # color applied.
                styles.append("color: var(--ptg-background);")
                styles.append("background-color: var(--ptg-foreground)")

                continue

            css = token_to_css(token, has_inverse)
            if css is not None and css not in styles:
                styles.append(css)

        escaped = (
            escape(span.plain)
            .replace("{", "{{")
            .replace("}", "}}")
            .replace(" ", "&#160;")
        )

        if len(styles) == 0:
            yield f"<span>{escaped}</span>", []
            continue

        tag = "<span{}>" + escaped + "</span>"
        tag += "</a>" if has_link else ""

        yield tag, styles


def token_to_css(token: Token, invert: bool = False) -> str:
    """Finds the CSS representation of a token.

    Args:
        token: The token to represent.
        invert: If set, the role of background & foreground colors
            are flipped.
    """

    if Token.is_color(token):
        color = token.color

        style = "color:" + color.hex

        if invert:
            color.background = not color.background

        if color.background:
            style = "background-" + style

        return style

    if token.is_style() and token.value in _STYLE_TO_CSS:
        return _STYLE_TO_CSS[token.value]

    return ""


# We take this many arguments for future proofing and customization, not much we can
# do about it.
def to_html(  # pylint: disable=too-many-arguments, too-many-locals
    obj: Widget | StyledText | str,
    prefix: str | None = None,
    inline_styles: bool = False,
    include_background: bool = True,
    vertical_offset: float = 0.0,
    horizontal_offset: float = 0.0,
    formatter: str = HTML_FORMAT,
    joiner: str = "\n",
) -> str:
    """Creates a static HTML representation of the given object.

    Note that the output HTML will not be very attractive or easy to read. This is
    because these files probably aren't meant to be read by a human anyways, so file
    sizes are more important.

    If you do care about the visual style of the output, you can run it through some
    prettifiers to get the result you are looking for.

    Args:
        obj: The object to represent. Takes either a Widget or some markup text.
        prefix: The prefix included in the generated classes, e.g. instead of `ptg-0`,
            you would get `ptg-my-prefix-0`.
        inline_styles: If set, styles will be set for each span using the inline `style`
            argument, otherwise a full style section is constructed.
        include_background: Whether to include the terminal's background color in the
            output.
    """

    document_styles: list[list[str]] = []

    if isinstance(obj, Widget):
        data = obj.get_lines()

    elif isinstance(obj, str):
        data = obj.splitlines()

    else:
        data = str(obj).splitlines()

    lines = []
    for dataline in data:
        line = ""

        for span, styles in _get_spans(
            dataline, vertical_offset, horizontal_offset, include_background
        ):
            index = _generate_index_in(document_styles, styles)
            if index == len(document_styles):
                document_styles.append(styles)

            if inline_styles:
                stylesheet = ";".join(styles)
                line += span.format(f" styles='{stylesheet}'")

            else:
                line += span.format(" class='" + _get_cls(prefix, index) + "'")

        # Close any previously not closed divs
        line += "</div>" * (line.count("<div") - line.count("</div"))
        lines.append(line)

    stylesheet = ""
    if not inline_styles:
        stylesheet = _generate_stylesheet(document_styles, prefix)

    document = formatter.format(
        foreground=Color.get_default_foreground().hex,
        background=Color.get_default_background().hex if include_background else "",
        content=joiner.join(lines),
        styles=stylesheet,
        font_size=FONT_SIZE,
    )

    return document


def _escape_text(text: str) -> str:
    """Escapes HTML and replaces ' ' with &nbsp;."""

    return escape(text).replace(" ", "&#160;")


def _handle_tokens_svg(
    text: StyledText, default_fore: str, default_back: str
) -> tuple[tuple[int, int] | None, str | None, list[str]]:
    """Builds CSS styles that apply to the text."""

    styles: list[tuple[Token, str]] = []
    pos = None

    fore, back = default_fore, default_back

    has_inverse = any(
        token.is_style() and token.value == "inverse" for token in text.tokens
    )

    fore, back = (
        (default_back, default_fore) if has_inverse else (default_fore, default_back)
    )

    for token in text.tokens:
        if Token.is_cursor(token):
            pos = token.x, token.y
            continue

        if Token.is_color(token):
            color = token.color

            if has_inverse:
                color = deepcopy(color)
                color.background = not color.background

            if color.background:
                back = color.hex

            else:
                fore = color.hex

            continue

        if Token.is_clear(token):
            for i, (target, _) in enumerate(styles):
                if token.targets(target):
                    styles.pop(i)

        css = token_to_css(token)

        if css != "":
            styles.append((token, css))

    css_styles = [value for _, value in styles]
    css_styles.append(f"fill:{fore}")

    return (None if pos is None else (pos[0] or 0, pos[1] or 0)), back, css_styles


def _slugify(text: str) -> str:
    """Turns the given text into a slugified form."""

    return text.replace(" ", "-").replace("_", "-")


def _make_tag(tagname: str, content: str = "", **attrs) -> str:
    """Creates a tag."""

    tag = f"<{tagname} "

    for key, value in attrs.items():
        if key == "raw":
            tag += " " + value
            continue

        if key == "cls":
            key = "class"

        if isinstance(value, float):
            value = round(value, 2)

        tag += f"{_slugify(key)}='{value}' "

    tag += f">{content}</{tagname}>"

    return tag


# This is a bit of a beast of a function, but it does the job and IMO reducing it
# into parts would just make our lives more complicated.
def to_svg(  # pylint: disable=too-many-locals, too-many-arguments, too-many-statements
    obj: Widget | StyledText | str,
    prefix: str | None = None,
    chrome: bool = True,
    inline_styles: bool = False,
    title: str = "PyTermGUI",
    formatter: str = SVG_FORMAT,
) -> str:
    """Creates an SVG screenshot of the given object.

    This screenshot tries to mimick what the Kitty terminal looks like on MacOS,
    complete with the menu buttons and drop shadow. The `title` argument will be
    displayed in the window's top bar.

    Args:
        obj: The object to represent. Takes either a Widget or some markup text.
        prefix: The prefix included in the generated classes, e.g. instead of `ptg-0`,
            you would get `ptg-my-prefix-0`.
        chrome: Sets the visibility of the window "chrome", e.g. the part of the SVG
            that mimicks the outside border of a terminal.
        inline_styles: If set, styles will be set for each span using the inline `style`
            argument, otherwise a full style section is constructed.
        title: A string to display in the top bar of the fake terminal.
        formatter: The formatting string to use. Inspect `pytermgui.exporters.SVG_FORMAT`
            to see all of its arguments.
    """

    def _is_block(text: str) -> bool:
        """Determines whether the given text only contains block characters.

        These characters reside in the unicode range of 9600-9631, which is what we test
        against.
        """

        return all(9600 <= ord(char) <= 9631 for char in text)

    prefix = prefix if prefix is not None else "ptg"

    terminal = get_terminal()
    default_fore = Color.get_default_foreground().hex
    default_back = Color.get_default_background().hex

    text = ""

    lines = 1
    cursor_x = cursor_y = 0.0
    document_styles: list[list[str]] = []

    # We manually set all text to have an alignment-baseline of
    # text-after-edge to avoid block characters rendering in the
    # wrong place (not at the top of their "box"), but with that
    # our background rects will be rendered in the wrong place too,
    # so this is used to offset that.
    baseline_offset = 0.17 * FONT_HEIGHT

    if isinstance(obj, Widget):
        obj = "\n".join(obj.get_lines())

    elif isinstance(obj, StyledText):
        obj = str(obj)

    for plain in tim.group_styles(obj):
        should_newline = False

        pos, back, styles = _handle_tokens_svg(plain, default_fore, default_back)

        index = _generate_index_in(document_styles, styles)

        if index == len(document_styles):
            document_styles.append(styles)

        style_attr = (
            f"class='{prefix}' style='{';'.join(styles)}'"
            if inline_styles
            else f"class='{prefix} {_get_cls(prefix, index)}'"
        )

        # Manual positioning
        if pos is not None:
            cursor_x = pos[0] * FONT_WIDTH - 10
            cursor_y = pos[1] * FONT_HEIGHT - 15

        for line in plain.plain.splitlines():
            text_len = len(line) * FONT_WIDTH

            if should_newline:
                cursor_y += FONT_HEIGHT
                cursor_x = 0

                lines += 1
                if lines > terminal.height:
                    break

            text += _make_tag(
                "rect",
                x=cursor_x,
                y=cursor_y - (baseline_offset if not _is_block(line) else 0),
                fill=back or default_back,
                width=text_len * 1.02,
                height=FONT_HEIGHT,
            )

            text += _make_tag(
                "text",
                _escape_text(line),
                dy="-0.25em",
                x=cursor_x,
                y=cursor_y + FONT_SIZE,
                textLength=text_len,
                raw=style_attr,
            )

            cursor_x += text_len
            should_newline = True

        if lines > terminal.height:
            break

        if plain.plain.endswith("\n"):
            cursor_y += FONT_HEIGHT
            cursor_x = 0

            lines += 1

    stylesheet = "" if inline_styles else _generate_stylesheet(document_styles, prefix)

    terminal_width = terminal.width * FONT_WIDTH + 2 * TEXT_MARGIN_LEFT
    terminal_height = terminal.height * FONT_HEIGHT + 2 * TEXT_MARGIN_TOP

    total_width = terminal_width + (2 * SVG_MARGIN_LEFT if chrome else 0)
    total_height = terminal_height + (2 * SVG_MARGIN_TOP if chrome else 0)

    if chrome:
        transform = (
            f"translate({TEXT_MARGIN_LEFT + SVG_MARGIN_LEFT}, "
            + f"{TEXT_MARGIN_TOP + SVG_MARGIN_TOP})"
        )

        chrome_part = f"""<g>
            <rect x="{SVG_MARGIN_LEFT}" y="{SVG_MARGIN_TOP}"
                rx="9px" ry="9px" stroke-width="1px" stroke-linejoin="round"
                width="{terminal_width}" height="{terminal_height}" fill="{default_back}" />
            <circle cx="{SVG_MARGIN_LEFT+15}" cy="{SVG_MARGIN_TOP + 15}" r="6" fill="#ff6159"/>
            <circle cx="{SVG_MARGIN_LEFT+35}" cy="{SVG_MARGIN_TOP + 15}" r="6" fill="#ffbd2e"/>
            <circle cx="{SVG_MARGIN_LEFT+55}" cy="{SVG_MARGIN_TOP + 15}" r="6" fill="#28c941"/>
            <text x="{terminal_width // 2}" y="{SVG_MARGIN_TOP + FONT_HEIGHT}" text-anchor="middle"
                class="{prefix}-title">{title}</text>
        </g>
        """

    else:
        transform = "translate(16, 16)"

        chrome_part = f"""<rect width="{total_width}" height="{total_height}"
            fill="{default_back}" />"""

    output = _make_tag("g", text, transform=transform) + "\n"

    return formatter.format(
        # Dimensions
        total_width=terminal_width + (2 * SVG_MARGIN_LEFT if chrome else 0),
        total_height=terminal_height + (2 * SVG_MARGIN_TOP if chrome else 0),
        terminal_width=terminal_width * 1.02,
        terminal_height=terminal_height - 15,
        # Styles
        background=default_back,
        stylesheet=stylesheet,
        # Code
        code=output,
        prefix=prefix,
        chrome=chrome_part,
    )
