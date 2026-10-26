import halloween


def test_package_importable():
    assert halloween.__version__


async def test_asyncio_tests_are_collected():
    # Vérifie que pytest-asyncio est actif (mode auto).
    assert True
