"""Le contrat OpenAPI versionné (`docs/openapi.json`) correspond aux routes réelles."""

import json
import re
from pathlib import Path

import pytest
from openapi_spec_validator import validate

from api_helpers import Pi
from halloween.api.openapi import PUBLIC_OPERATIONS, main, openapi_document, render
from halloween.events import EVENT_MODELS

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "openapi.json"
HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return openapi_document()


def operations(spec):
    for path, methods in spec["paths"].items():
        for method, operation in methods.items():
            if method in HTTP_METHODS:
                yield path, method, operation


def test_committed_contract_is_up_to_date(spec):
    committed = CONTRACT.read_text(encoding="utf-8")
    assert committed == render(spec), "docs/openapi.json est périmé : lancer `make openapi`"


def test_check_mode_detects_a_stale_file(tmp_path):
    stale = tmp_path / "openapi.json"
    stale.write_text("{}")
    assert main(["--check", "--output", str(stale)]) == 1
    assert main(["--output", str(stale)]) == 0
    assert main(["--check", "--output", str(stale)]) == 0


def test_contract_is_a_valid_openapi_document(spec):
    validate(spec)  # lève une exception si le document n'est pas du OpenAPI 3.1 valide


def test_every_documented_operation_exists_on_the_real_application(tmp_path, spec):
    """Chaque opération du contrat répond réellement : 401 sans jeton (route protégée existante)."""
    from fastapi.testclient import TestClient

    with TestClient(Pi(tmp_path).app()) as client:
        checked = 0
        for path, method, operation in operations(spec):
            url = re.sub(r"\{[^}]+\}", "x", path)
            response = client.request(method.upper(), url)
            if operation["operationId"] in PUBLIC_OPERATIONS:
                assert response.status_code in (200, 404), (method, path)
                assert response.status_code != 404 or "inconnue" in response.text
            else:
                assert response.status_code == 401, (
                    f"{method.upper()} {path} -> {response.status_code}"
                )
            checked += 1
    assert checked >= 25


def test_the_served_contract_is_the_same_enriched_document(tmp_path, spec):
    from fastapi.testclient import TestClient

    with TestClient(Pi(tmp_path).app()) as client:
        served = client.get("/openapi.json").json()
    assert served == json.loads(render(spec)) or served == spec
    assert "x-websocket" in served and "Event" in served["components"]["schemas"]


def test_operation_ids_are_unique_stable_and_readable(spec):
    ids = [operation["operationId"] for _, _, operation in operations(spec)]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z][a-z0-9_]*", i) for i in ids), ids
    assert not any("_api_" in i for i in ids)  # pas d'identifiant auto-généré à partir du chemin


def test_every_operation_is_tagged_documented_and_has_a_success_response(spec):
    tag_names = {t["name"] for t in spec["tags"]}
    for path, method, operation in operations(spec):
        label = f"{method.upper()} {path}"
        assert operation.get("tags") and set(operation["tags"]) <= tag_names, label
        assert any(code.startswith("2") for code in operation["responses"]), label


def test_authentication_is_declared_except_on_public_routes(spec):
    assert spec["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    for path, method, operation in operations(spec):
        public = operation["operationId"] in PUBLIC_OPERATIONS
        assert (operation.get("security") == []) == public, f"{method.upper()} {path}"
    assert PUBLIC_OPERATIONS == {"health", "get_image"}


def test_websocket_events_are_described(spec):
    schemas = spec["components"]["schemas"]
    assert spec["x-websocket"]["path"] == "/api/events"
    event = schemas["Event"]
    assert event["discriminator"]["propertyName"] == "type"
    mapped = set(event["discriminator"]["mapping"])
    assert mapped == {model.model_fields["type"].default for model in EVENT_MODELS}
    for model in EVENT_MODELS:
        assert model.__name__ in schemas


def test_program_format_is_exposed_with_its_documented_keys(spec):
    program = spec["components"]["schemas"]["Program"]
    assert {"schema", "id", "name", "scripts", "revision", "max_duration_s", "show"} <= set(
        program["properties"]
    )
    body = spec["paths"]["/api/programs/{program_id}"]["put"]["requestBody"]
    assert body["content"]["application/json"]["schema"] == {"$ref": "#/components/schemas/Program"}
    parameters = spec["paths"]["/api/programs/{program_id}"]["put"]["parameters"]
    assert "if-match" in {p["name"].lower() for p in parameters}


def test_component_results_have_readable_schema_names(spec):
    names = set(spec["components"]["schemas"])
    assert {"RelayResult", "ButtonResult", "LightResult", "SwitchResult"} <= names
    assert not any(re.search(r"Result_\w+_", n) for n in names)


def test_images_are_documented_as_binary_uploads(spec):
    upload = spec["paths"]["/api/images"]["post"]["requestBody"]["content"]
    assert set(upload) == {"image/png", "image/jpeg", "image/webp"}
    assert all(v["schema"]["format"] == "binary" for v in upload.values())
