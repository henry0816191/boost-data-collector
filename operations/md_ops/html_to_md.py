"""
HTML to Markdown converter using only Python standard library.
"""

from html import unescape
from html.parser import HTMLParser
import re


class HTMLToMarkdownConverter(HTMLParser):
    """Converts HTML to Markdown using standard library only."""

    def __init__(self):
        super().__init__()
        self.markdown = []
        self.current_tag = None
        self.list_depth = 0
        self.list_item_count = []
        self.list_types = []
        self.in_code = False
        self.in_pre = False
        self.link_text = None
        self.link_url = None
        self.bold_count = 0
        self.italic_count = 0
        self.last_char = ""
        self.in_control = False
        self.control_content = []
        self.skip_embedded_file = False

    def handle_starttag(self, tag, attrs):
        """Handle opening HTML tags."""
        attrs_dict = dict(attrs)

        if tag == "h1":
            self.markdown.append("\n# ")
            self.current_tag = "h1"
        elif tag == "h2":
            self.markdown.append("\n## ")
            self.current_tag = "h2"
        elif tag == "h3":
            self.markdown.append("\n### ")
            self.current_tag = "h3"
        elif tag == "h4":
            self.markdown.append("\n#### ")
            self.current_tag = "h4"
        elif tag == "h5":
            self.markdown.append("\n##### ")
            self.current_tag = "h5"
        elif tag == "h6":
            self.markdown.append("\n###### ")
            self.current_tag = "h6"
        elif tag == "p":
            # Check if this is an embedded-file paragraph
            class_attr = attrs_dict.get("class", "")
            if class_attr == "embedded-file":
                self.skip_embedded_file = True
                self.current_tag = "p"
            else:
                if self.markdown and self.markdown[-1] not in [
                    "\n",
                    "\n# ",
                    "\n## ",
                    "\n### ",
                    "\n#### ",
                    "\n##### ",
                    "\n###### ",
                ]:
                    self.markdown.append("\n\n")
                self.current_tag = "p"
        elif tag == "b" or tag == "strong":
            if (
                self.markdown
                and self.markdown[-1]
                and not self.markdown[-1].endswith(" ")
                and self.markdown[-1]
                not in [
                    "\n",
                    "\n# ",
                    "\n## ",
                    "\n### ",
                    "\n#### ",
                    "\n##### ",
                    "\n###### ",
                    "\n\n",
                ]
            ):
                self.markdown.append(" ")
            self.markdown.append("**")
            self.bold_count += 1
        elif tag == "i" or tag == "em":
            self.markdown.append("*")
            self.italic_count += 1
        elif tag == "a":
            href = attrs_dict.get("href", "")
            self.link_url = href
            self.link_text = []
            if self.in_control:
                self.current_tag = "a_in_control"
            else:
                if (
                    self.markdown
                    and self.markdown[-1]
                    and not self.markdown[-1].endswith(" ")
                    and self.markdown[-1]
                    not in [
                        "\n",
                        "\n# ",
                        "\n## ",
                        "\n### ",
                        "\n#### ",
                        "\n##### ",
                        "\n###### ",
                        "\n\n",
                    ]
                ):
                    self.markdown.append(" ")
                self.current_tag = "a"
        elif tag == "ul":
            self.list_depth += 1
            self.list_item_count.append(0)
            self.list_types.append("ul")
        elif tag == "ol":
            self.list_depth += 1
            self.list_item_count.append(0)
            self.list_types.append("ol")
        elif tag == "li":
            if self.list_item_count:
                self.list_item_count[-1] += 1
            indent = "  " * (self.list_depth - 1)
            if self.list_types and self.list_types[-1] == "ol" and self.list_item_count:
                prefix = f"{self.list_item_count[-1]}. "
            else:
                prefix = "- "
            self.markdown.append(f"\n{indent}{prefix}")
            self.current_tag = "li"
        elif tag == "br":
            self.markdown.append("\n")
        elif tag == "hr":
            self.markdown.append("\n\n---\n\n")
        elif tag == "code":
            if not self.in_pre:
                self.markdown.append("`")
            self.in_code = True
        elif tag == "pre":
            self.markdown.append("\n```\n")
            self.in_pre = True
        elif tag == "img":
            alt = attrs_dict.get("alt", "")
            src = attrs_dict.get("src", "")
            if self.in_control:
                pass
            else:
                if alt and src:
                    self.markdown.append(f"![{alt}]({src})")
                elif src:
                    self.markdown.append(f"![]({src})")
        elif tag == "control":
            self.in_control = True
            self.control_content = []
        elif tag == "span":
            pass
        elif tag == "div":
            pass

    def handle_endtag(self, tag):
        """Handle closing HTML tags."""
        if (
            tag == "h1"
            or tag == "h2"
            or tag == "h3"
            or tag == "h4"
            or tag == "h5"
            or tag == "h6"
        ):
            self.markdown.append("\n")
            self.current_tag = None
        elif tag == "p":
            if self.skip_embedded_file:
                self.skip_embedded_file = False
            else:
                self.markdown.append("\n")
            self.current_tag = None
        elif tag == "b" or tag == "strong":
            self.markdown.append("**")
            self.bold_count = max(0, self.bold_count - 1)
        elif tag == "i" or tag == "em":
            self.markdown.append("*")
            self.italic_count = max(0, self.italic_count - 1)
        elif tag == "a":
            if self.current_tag == "a_in_control":
                if self.link_text:
                    text = "".join(self.link_text).strip()
                    if text:
                        self.control_content.append(text)
                elif self.link_url:
                    self.control_content.append(self.link_url)
                self.link_text = None
                self.link_url = None
                self.current_tag = None
            else:
                if self.link_text and self.link_url:
                    text = "".join(self.link_text).strip()
                    if text:
                        self.markdown.append(f"[{text}]({self.link_url})")
                    else:
                        self.markdown.append(f"({self.link_url})")
                elif self.link_url:
                    self.markdown.append(f"({self.link_url})")
                self.link_text = None
                self.link_url = None
                self.current_tag = None
        elif tag == "ul" or tag == "ol":
            if self.list_item_count:
                self.list_item_count.pop()
            if self.list_types:
                self.list_types.pop()
            self.list_depth = max(0, self.list_depth - 1)
            self.markdown.append("\n")
        elif tag == "li":
            self.current_tag = None
        elif tag == "code":
            if not self.in_pre:
                self.markdown.append("`")
            self.in_code = False
        elif tag == "pre":
            self.markdown.append("\n```\n")
            self.in_pre = False
        elif tag == "control":
            if self.control_content:
                content_parts = []
                for part in self.control_content:
                    if not (part.startswith(":") and part.endswith(":")):
                        content_parts.append(part)
                content = "".join(content_parts).strip()
                if content:
                    if self.markdown and self.markdown[-1] not in [
                        "\n",
                        "\n# ",
                        "\n## ",
                        "\n### ",
                        "\n#### ",
                        "\n##### ",
                        "\n###### ",
                        "\n\n",
                        "**",
                        "*",
                        "`",
                        "- ",
                        "1. ",
                        "2. ",
                        "3. ",
                        "4. ",
                        "5. ",
                        "6. ",
                        "7. ",
                        "8. ",
                        "9. ",
                    ]:
                        if (
                            self.markdown[-1]
                            and not self.markdown[-1].endswith(" ")
                            and not content.startswith(" ")
                        ):
                            self.markdown.append(" ")
                    self.markdown.append(content)
            self.in_control = False
            self.control_content = []
        elif tag == "span":
            pass
        elif tag == "div":
            pass

    def handle_data(self, data):
        """Handle text content."""
        if self.skip_embedded_file:
            return
        if self.in_pre or self.in_code:
            self.markdown.append(data)
            return
        data = data.strip()
        if not data:
            return
        if self.in_control:
            if self.current_tag == "a_in_control":
                if self.link_text is None:
                    self.link_text = []
                self.link_text.append(data)
            else:
                self.control_content.append(data)
            return
        if self.current_tag == "a":
            if self.link_text is None:
                self.link_text = []
            self.link_text.append(data)
        else:
            if data.startswith(":") and data.endswith(":"):
                return
            if self.markdown and self.markdown[-1] not in [
                "\n",
                "\n# ",
                "\n## ",
                "\n### ",
                "\n#### ",
                "\n##### ",
                "\n###### ",
                "\n\n",
                "**",
                "*",
                "`",
                "- ",
                "1. ",
                "2. ",
                "3. ",
                "4. ",
                "5. ",
                "6. ",
                "7. ",
                "8. ",
                "9. ",
            ]:
                if (
                    self.markdown[-1]
                    and not self.markdown[-1].endswith(" ")
                    and not data.startswith(" ")
                ):
                    self.markdown.append(" ")
            self.markdown.append(data)

    def handle_charref(self, name):
        char = unescape(f"&#{name};")
        self.handle_data(char)

    def handle_entityref(self, name):
        char = unescape(f"&{name};")
        self.handle_data(char)

    def get_markdown(self):
        """Get the final markdown string."""
        result = "".join(self.markdown)
        result = re.sub(r"\n{3,}", "\n\n", result)
        result = re.sub(r" +\n", "\n", result)
        return result.strip()


def html_to_markdown(html_content):
    """
    Convert HTML content to Markdown format.

    Args:
        html_content (str): HTML content as string

    Returns:
        str: Markdown formatted string
    """
    parser = HTMLToMarkdownConverter()
    parser.feed(html_content)
    return parser.get_markdown()


def convert_html_file_to_markdown(input_file, output_file=None):
    """
    Convert an HTML file to Markdown format.

    Args:
        input_file (str): Path to input HTML file
        output_file (str, optional): Path to output Markdown file.

    Returns:
        str: Path to the output markdown file
    """
    with open(input_file, "r", encoding="utf-8") as f:
        html_content = f.read()
    markdown_content = html_to_markdown(html_content)
    if output_file is None:
        if input_file.endswith(".html"):
            output_file = input_file[:-5] + ".md"
        else:
            output_file = input_file + ".md"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    return output_file
