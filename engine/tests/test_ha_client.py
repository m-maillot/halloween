import pytest

from fake_ha import TOKEN, FakeHA
from halloween.config.models import HomeAssistant
from halloween.drivers.base import HAClient, HAError
from halloween.drivers.homeassistant import HttpHAClient

STATES = [
    {
        "entity_id": "light.bandeau_hue",
        "state": "on",
        "attributes": {"friendly_name": "Bandeau Hue"},
    },
    {"entity_id": "switch.prise_salon", "state": "off", "attributes": {}},
    {"entity_id": "sensor.temperature", "state": "21", "attributes": {"friendly_name": "Temp"}},
    {
        "entity_id": "light.twinkly_halloween",
        "state": "off",
        "attributes": {"friendly_name": "Twinkly"},
    },
]


@pytest.fixture
def ha():
    server = FakeHA(states=STATES).start()
    yield server
    server.stop()


@pytest.fixture
async def client(ha):
    c = HttpHAClient(ha.url, TOKEN, timeout_s=2)
    yield c
    await c.close()


async def test_is_a_ha_client(client):
    assert isinstance(client, HAClient)


async def test_light_on_posts_the_exact_body_with_the_bearer_token(client, ha):
    await client.light_on("light.bandeau_hue", rgb_color=(255, 0, 0), brightness=40, transition=2)
    (request,) = ha.posts()
    assert request.path == "/api/services/light/turn_on"
    assert request.token == TOKEN
    assert request.body == {
        "entity_id": "light.bandeau_hue",
        "rgb_color": [255, 0, 0],
        "brightness": 40,
        "transition": 2,
    }


async def test_other_service_calls(client, ha):
    await client.light_off("light.bandeau_hue")
    await client.switch_on("switch.prise_salon")
    await client.switch_off("switch.prise_salon")
    assert [(r.path, r.body) for r in ha.posts()] == [
        ("/api/services/light/turn_off", {"entity_id": "light.bandeau_hue"}),
        ("/api/services/switch/turn_on", {"entity_id": "switch.prise_salon"}),
        ("/api/services/switch/turn_off", {"entity_id": "switch.prise_salon"}),
    ]


async def test_check_connection(client, ha):
    assert await client.check_connection() == "API running."
    assert [(r.method, r.path) for r in ha.requests] == [("GET", "/api/")]


async def test_list_entities_filters_by_domain_and_sorts(client):
    lights = await client.list_entities("light")
    assert [e.entity_id for e in lights] == ["light.bandeau_hue", "light.twinkly_halloween"]
    assert (
        lights[0].name == "Bandeau Hue" and lights[0].state == "on" and lights[0].domain == "light"
    )
    assert len(await client.list_entities()) == 4


async def test_entity_without_friendly_name_uses_its_id(client):
    switches = await client.list_entities("switch")
    assert switches[0].name == "switch.prise_salon"


async def test_get_entity(client):
    assert (await client.get_entity("light.bandeau_hue")).state == "on"
    assert await client.get_entity("light.inexistante") is None


async def test_url_with_a_path_prefix_and_trailing_slash(ha):
    # derrière un proxy inverse, l'API peut vivre sous un préfixe
    ha.overrides[("GET", "/ha/api/")] = (200, {"message": "API running."})
    client = HttpHAClient(ha.url + "/ha/", TOKEN)
    try:
        assert await client.check_connection() == "API running."
    finally:
        await client.close()


async def test_service_error_status_raises_ha_error(client, ha):
    ha.overrides[("POST", "/api/services/light/turn_on")] = (500, {"message": "boum"})
    with pytest.raises(HAError, match="HTTP 500"):
        await client.light_on("light.x")


def test_from_config_uses_the_configured_token_unless_the_env_overrides_it():
    config = HomeAssistant(url="http://ha:8123", token="du-fichier", timeout_s=3)
    from_file = HttpHAClient.from_config(config, env={})
    from_env = HttpHAClient.from_config(config, env={"HALLOWEEN_HA_TOKEN": "de-l-env"})
    assert from_file._client.headers["Authorization"] == "Bearer du-fichier"
    assert from_env._client.headers["Authorization"] == "Bearer de-l-env"
    assert from_file._client.timeout.read == 3


def test_token_never_appears_in_repr():
    client = HttpHAClient("http://ha:8123", "tres-secret")
    assert "tres-secret" not in repr(client) and "tres-secret" not in str(client)
