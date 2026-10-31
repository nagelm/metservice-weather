"""Tests for the warning notifications blueprint against the Warnings sensor's attributes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.core import State
from homeassistant.helpers.template import Template
from homeassistant.util.yaml import load_yaml

from custom_components.metservice_weather.coordinator_types import MetServicePublicData
from custom_components.metservice_weather.weather_current_conditions_sensors import (
    current_condition_sensor_descriptions_public,
)

_ROOT = Path(__file__).parent.parent
_BLUEPRINT = (
    _ROOT / "blueprints/automation/metservice_weather/warning_notifications.yaml"
)


def _warning_state(*names: str) -> State:
    """Build the Warnings sensor state the integration publishes for these warnings."""
    description = next(
        d
        for d in current_condition_sensor_descriptions_public
        if d.key == "warning_level"
    )
    data = MetServicePublicData(
        warnings_list=[
            {"name": name, "text": "t", "threat_period": "Today"} for name in names
        ]
    )
    return State(
        "sensor.napier_warnings", description.value_fn(data), description.attr_fn(data)
    )


async def test_blueprint_inputs_are_unchanged(hass):
    """Automations built from the blueprint depend on these input names."""
    blueprint = await hass.async_add_executor_job(load_yaml, str(_BLUEPRINT))
    assert set(blueprint["blueprint"]["input"]) == {
        "warning_sensor",
        "details_sensor",
        "min_severity",
        "notify_actions",
    }


@pytest.mark.parametrize(
    ("before", "after", "min_severity", "fires"),
    [
        pytest.param((), ("Road Snowfall Warning",), 1, True, id="new-warning"),
        pytest.param(
            ("Road Snowfall Warning",),
            ("Heavy Rain Warning - Orange",),
            1,
            True,
            id="severity-rose",
        ),
        pytest.param(
            ("Heavy Rain Warning - Orange",),
            ("Road Snowfall Warning",),
            1,
            False,
            id="severity-fell",
        ),
        pytest.param((), ("Strong Wind Watch",), 2, False, id="below-minimum-severity"),
        pytest.param(
            ("Road Snowfall Warning",),
            ("Road Snowfall Warning", "Strong Wind Warning"),
            1,
            True,
            id="count-rose",
        ),
    ],
)
async def test_blueprint_condition_reads_the_published_attributes(
    hass, before, after, min_severity, fires
):
    """The blueprint's condition fires from the sensor's real severity_level and count."""
    blueprint = await hass.async_add_executor_job(load_yaml, str(_BLUEPRINT))
    template = Template(blueprint["condition"][0]["value_template"], hass)

    result = template.async_render(
        {
            "trigger": {
                "from_state": _warning_state(*before),
                "to_state": _warning_state(*after),
            },
            "min_severity": min_severity,
        }
    )

    assert result is fires


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json"])
def test_severity_level_attribute_has_a_translated_name(name):
    """The attribute shows a readable name; its key stays severity_level."""
    path = _ROOT / "custom_components/metservice_weather" / name
    strings = json.loads(path.read_text(encoding="utf-8"))
    attributes = strings["entity"]["sensor"]["warning_level"]["state_attributes"]
    assert attributes["severity_level"]["name"] == "Severity level"
