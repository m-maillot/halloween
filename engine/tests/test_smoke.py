import asyncio

import halloween


def test_package_importable():
    assert halloween.__version__


async def test_async_tests_run_in_event_loop():
    # Vérifie que pytest-asyncio est actif (mode auto) : sans lui, ce test serait ignoré.
    assert asyncio.get_running_loop().is_running()
    await asyncio.sleep(0)
