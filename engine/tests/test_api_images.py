import io

import pytest
from PIL import Image

from api_helpers import Pi
from halloween.api.images import MAX_SIDE, MAX_UPLOAD_BYTES


@pytest.fixture
def pi(tmp_path) -> Pi:
    return Pi(tmp_path)


@pytest.fixture
def client(pi):
    with pi.client() as c:
        yield c


def encode(image: Image.Image, fmt: str = "PNG", **kwargs) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **kwargs)
    return out.getvalue()


def upload(client, data: bytes, content_type: str = "image/png"):
    return client.post("/api/images", content=data, headers={"Content-Type": content_type})


def test_upload_returns_a_reference_and_the_image_is_served_without_a_token(client):
    response = upload(client, encode(Image.new("RGB", (100, 80), (255, 0, 0))))
    assert response.status_code == 201
    body = response.json()
    assert body["image"].endswith(".webp") and body["url"] == f"/api/images/{body['image']}"
    assert (body["width"], body["height"]) == (100, 80)

    from fastapi.testclient import TestClient

    anonymous = TestClient(client.app)  # les balises <img> ne peuvent pas envoyer de jeton
    served = anonymous.get(body["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/webp"
    assert "immutable" in served.headers["cache-control"]
    assert Image.open(io.BytesIO(served.content)).size == (100, 80)


def test_large_images_are_reduced_keeping_the_aspect_ratio(client):
    response = upload(client, encode(Image.new("RGB", (2000, 1000), "blue")))
    assert (response.json()["width"], response.json()["height"]) == (MAX_SIDE, MAX_SIDE // 2)


def test_jpeg_and_webp_are_accepted_and_transparency_is_kept(client):
    assert (
        upload(client, encode(Image.new("RGB", (10, 10)), "JPEG"), "image/jpeg").status_code == 201
    )
    assert (
        upload(client, encode(Image.new("RGB", (10, 10)), "WEBP"), "image/webp").status_code == 201
    )
    transparent = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    name = upload(client, encode(transparent)).json()["image"]
    stored = Image.open(io.BytesIO(client.get(f"/api/images/{name}").content))
    assert stored.mode == "RGBA" and stored.getpixel((0, 0))[3] == 0


def test_exif_metadata_is_removed_and_orientation_applied(client):
    image = Image.new("RGB", (40, 20), "green")
    exif = Image.Exif()
    exif[0x0112] = 6  # à pivoter de 90°
    exif[0x010F] = "AppareilSecret"
    exif[0x8825] = {1: "N", 2: (48.0, 51.0, 0.0)}  # position GPS
    raw = encode(image, "JPEG", exif=exif)
    assert b"AppareilSecret" in raw
    response = upload(client, raw, "image/jpeg").json()
    assert (response["width"], response["height"]) == (20, 40)  # pivotée
    served = client.get(response["url"]).content
    assert b"AppareilSecret" not in served and not Image.open(io.BytesIO(served)).getexif()


def test_same_content_gets_the_same_name(client):
    data = encode(Image.new("RGB", (32, 32), "orange"))
    assert upload(client, data).json()["image"] == upload(client, data).json()["image"]


def test_unsupported_content_type_is_a_415(client):
    assert upload(client, b"GIF89a", "image/gif").status_code == 415
    assert upload(client, b"x", "text/plain").status_code == 415
    assert client.post("/api/images", content=b"x").status_code == 415


def test_unreadable_or_unsupported_data_is_a_422(client):
    assert upload(client, b"ceci n'est pas une image").status_code == 422
    gif = encode(Image.new("P", (4, 4)), "GIF")
    response = upload(client, gif, "image/png")  # déclaré PNG mais c'est un GIF
    assert response.status_code == 422 and "format" in response.json()["detail"]["message"]
    truncated = encode(Image.new("RGB", (200, 200), "red"))[:100]
    assert upload(client, truncated).status_code == 422


def test_oversized_upload_is_a_413(client):
    response = upload(client, b"\x00" * (MAX_UPLOAD_BYTES + 1))
    assert response.status_code == 413


def test_decompression_bomb_is_refused_before_decoding(client):
    huge = encode(Image.new("1", (10_000, 10_000)))  # 100 mégapixels, quelques ko compressés
    assert len(huge) < 100_000
    response = upload(client, huge)
    assert response.status_code == 413 and "trop grande" in response.json()["detail"]["message"]


@pytest.mark.parametrize(
    "name", ["inconnue.webp", "..%2Fconfig.json", "%2e%2e%2Fconfig.json", "a.gif", ".webp"]
)
def test_unknown_or_dangerous_names_are_404(client, name):
    assert client.get(f"/api/images/{name}").status_code == 404


def test_an_uploaded_image_can_be_used_by_a_component_and_persists(client, pi):
    name = upload(client, encode(Image.new("RGB", (16, 16), "red"))).json()["image"]
    response = client.put(
        "/api/components/relays/fantome",
        json={"name": "Fantôme", "pin": 18, "mode": "latched", "image": name},
    )
    assert (
        response.status_code == 200
        and response.json()["component"]["image_url"] == f"/api/images/{name}"
    )
    assert (pi.store.root / "images" / name).is_file()
