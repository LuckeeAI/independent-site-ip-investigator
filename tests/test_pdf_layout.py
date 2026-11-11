"""Verify the HTML sent to the PDF renderer using real Markdown conversion."""

import re
import sys
import types

from bs4 import BeautifulSoup, NavigableString
import pytest

import site_ip_investigator as inv


@pytest.fixture(params=["en", "zh"])
def pdf_sections(request, monkeypatch, tmp_path, sample_data):
    captured = []
    sample_data["input_url"] = "https://example.com/products/foo_bar_baz?variant=one_two_three"

    class HTML:
        def __init__(self, *, string):
            captured.append(string)

        def write_pdf(self, path):
            pass

    # Only replace the native renderer; markdown2 must perform the conversion.
    monkeypatch.setitem(sys.modules, "weasyprint", types.SimpleNamespace(HTML=HTML))
    markdown = inv.deterministic_report(sample_data, lang=request.param)
    assert inv.write_pdf(markdown, tmp_path / "report.pdf") == (True, None)
    assert len(captured) == 1
    document = BeautifulSoup(captured[0], "html.parser")
    sections = {}
    for heading in document.find_all("h2"):
        number = int(heading.get_text().split(".", 1)[0])
        content = []
        for sibling in heading.next_siblings:
            if getattr(sibling, "name", None) == "h2":
                break
            content.append(str(sibling))
        sections[number] = BeautifulSoup("".join(content), "html.parser")
    return sections


def test_pdf_basic_information_preserves_literal_field_names_and_url(pdf_sections, sample_data):
    basic = pdf_sections[1].get_text()
    assert sample_data["input_url"] in basic
    if "Hostname:" in basic:
        assert "Shared platform subdomain: false" in basic
    else:
        assert "平台子域名（shared_platform_subdomain）：false" in basic


def paragraph_starting_with(section, prefix):
    return next(
        paragraph for paragraph in section.find_all("p")
        if paragraph.get_text().strip().startswith(prefix)
    )


def visible_lines(paragraph):
    """Collapse ordinary HTML whitespace while preserving actual br elements."""
    lines = [[]]
    for node in paragraph.descendants:
        if getattr(node, "name", None) == "br":
            lines.append([])
        elif isinstance(node, NavigableString):
            lines[-1].append(re.sub(r"\s+", " ", str(node)))
    return ["".join(line).strip() for line in lines if "".join(line).strip()]


@pytest.mark.parametrize("section_number", [8, 9, 10])
def test_pdf_complaint_fields_and_signatures_keep_visible_line_breaks(
    pdf_sections, sample_data, section_number,
):
    section = pdf_sections[section_number]
    if section_number in {8, 9}:
        target = paragraph_starting_with(section, "Infringing Website / Domain:")
        assert visible_lines(target) == [
            "Infringing Website / Domain: example.com",
            f"Infringing Page URL: {sample_data['input_url']}",
        ]
        contact = paragraph_starting_with(section, "Rights Owner Information:")
        assert visible_lines(contact) == [
            "Rights Owner Information:",
            "Brand Name: Example Brand",
            "Company Name: Example Company",
            "Contact Person: [Name]",
            "Email: [Email]",
            "Phone: [Phone]",
            "Address: [Company Address]",
            "Official Website: https://example.org",
        ]
        signature = paragraph_starting_with(section, "Sincerely,")
        assert visible_lines(signature) == ["Sincerely,", "[Name]", "[Title]", "Example Company"]
    else:
        target = paragraph_starting_with(section, "Brand:")
        assert visible_lines(target) == [
            "Brand: Example Brand",
            "Company: Example Company",
            "Amazon Listing URL: https://example.org/listing",
            "External Website: example.com",
            f"Infringing Page URL: {sample_data['input_url']}",
            "Official Website / Original Image Source: https://example.org",
        ]
        signature = paragraph_starting_with(section, "Best regards,")
        assert visible_lines(signature) == ["Best regards,", "[Name]", "Example Company"]


@pytest.mark.parametrize("section_number,introduction,count,first,last", [
    (8, "Attached are supporting documents:", 7,
     "Original product images", "Company information and proof of ownership"),
    (9, "Attached are supporting documents:", 5,
     "Trademark registration certificate", "Company information and proof of ownership"),
    (10, "We respectfully request Amazon to:", 4,
     "Remove the incorrect external price association.",
     "Restore the Buy Box / Featured Offer if it was removed due to this incorrect external match."),
    (10, "Attached are supporting documents:", 7,
     "Brand ownership proof / Amazon Brand Registry proof",
     "Explanation showing that the external website is unauthorized and not a comparable offer"),
])
def test_pdf_template_numbered_requests_and_attachments_are_lists(
    pdf_sections, section_number, introduction, count, first, last,
):
    paragraph = paragraph_starting_with(pdf_sections[section_number], introduction)
    numbered_list = paragraph.find_next_sibling()
    assert numbered_list is not None and numbered_list.name == "ol"
    items = numbered_list.find_all("li", recursive=False)
    assert len(items) == count
    assert items[0].get_text(" ", strip=True) == first
    assert items[-1].get_text(" ", strip=True) == last
