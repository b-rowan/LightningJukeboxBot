from pydantic import computed_field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from .const import BASE_DIR


class JukeboxSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JUKEBOX_")

    port: int = 7000

    domain: str

    delete_message_timeout_short: int = 10
    delete_message_timeout_medium: int = 60
    delete_message_timeout_long: int = 300

    max_connections: int = 5

    bot_token: str
    bot_id: int
    bot_ipaddr: str

    price: int = 21
    donation_fee: int = 21
    fund_max: int = 42000

    lnbits_protocol: str
    lnbits_host: str
    lnbits_adminkey: str
    lnbits_hostkey: str
    lnbits_userkey: str

    superadmin: list[int]

    @computed_field
    @property
    def fund_min(self) -> int:
        return self.price

    @computed_field
    @property
    def spotify_redirect_uri(self) -> str:
        return f"https://{self.domain}/spotify"

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            YamlConfigSettingsSource(settings_cls, BASE_DIR.parent.joinpath("settings.yaml")),
            env_settings,
            file_secret_settings,
        )
