from app_identity import (
    APP_DISPLAY_NAME,
    APP_STORAGE_NAME,
    GITHUB_REPOSITORY,
    MAIN_EXECUTABLE_NAME,
    SETUP_RELEASE_ASSET_TEMPLATE,
    SINGLE_INSTANCE_MUTEX,
    UPDATER_EXECUTABLE_NAME,
)


def test_public_brand_uses_tokenmeter_names():
    assert APP_DISPLAY_NAME == "TokenMeter"
    assert MAIN_EXECUTABLE_NAME == "TokenMeter.exe"
    assert UPDATER_EXECUTABLE_NAME == "TokenMeterUpdater.exe"
    assert SETUP_RELEASE_ASSET_TEMPLATE == "TokenMeter-Setup-v{version}-x64.exe"
    assert GITHUB_REPOSITORY == "zensoku142/TokenMeter"


def test_legacy_storage_and_single_instance_identities_remain_stable():
    # These identifiers are persistent Windows integration keys, not display branding.
    assert APP_STORAGE_NAME == "TokenSpider"
    assert SINGLE_INSTANCE_MUTEX == r"Local\TokenSpider.SingleInstance"
