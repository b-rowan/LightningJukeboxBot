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

    bot_token: str
    bot_id: str

    price: int = 21
    donation_fee: int = 21

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
