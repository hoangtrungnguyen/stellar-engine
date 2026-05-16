"""IR round-trip tests — dataclass → JSON → dataclass must preserve fields."""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from generator.ir import (
    Block,
    DesignLink,
    Epic,
    Heading,
    Outline,
    Section,
    Story,
    Task,
    outline_from_dict,
    section_from_dict,
)


def test_section_roundtrip_empty():
    s = Section(heading=Heading(level=1, text="Root", anchor="1"))
    d = asdict(s)
    s2 = section_from_dict(json.loads(json.dumps(d)))
    assert s2 == s


def test_section_roundtrip_nested():
    s = Section(
        heading=Heading(level=1, text="Root", anchor="1"),
        blocks=[Block(kind="paragraph", text="hi", anchor="2")],
        children=[
            Section(
                heading=Heading(level=2, text="Sub", anchor="3"),
                blocks=[Block(kind="code", text="print(1)", anchor="4")],
            )
        ],
    )
    d = asdict(s)
    s2 = section_from_dict(json.loads(json.dumps(d)))
    assert s2 == s
    assert s2.children[0].blocks[0].text == "print(1)"


def test_outline_roundtrip_minimal():
    o = Outline()
    d = asdict(o)
    o2 = outline_from_dict(json.loads(json.dumps(d)))
    assert o2 == o
    assert o2.epics == []
    assert o2.confidence == 0.0


def test_outline_roundtrip_full():
    o = Outline(
        epics=[
            Epic(
                title="Court Booking",
                summary="Pick + reserve",
                source_anchors=["L12"],
                design_links=[
                    DesignLink(url="https://figma.com/x", label="Figma flow"),
                    DesignLink(url="design/mock.png"),
                ],
                stories=[
                    Story(
                        title="Pick a court",
                        depends_on=["auth"],
                        source_anchors=["L20"],
                        acceptance_criteria=["Map shows pins", "Pin tap opens sheet"],
                        tasks=[Task(title="Render map", ac=["use Goong tiles"])],
                    )
                ],
            )
        ],
        confidence=0.78,
    )
    d = asdict(o)
    o2 = outline_from_dict(json.loads(json.dumps(d)))
    assert o2 == o


def test_design_link_label_none_serialises():
    dl = DesignLink(url="design/mock.png")
    d = asdict(dl)
    assert d == {"url": "design/mock.png", "label": None}


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_outline_confidence_preserved(confidence):
    o = Outline(confidence=confidence)
    o2 = outline_from_dict(json.loads(json.dumps(asdict(o))))
    assert o2.confidence == confidence
