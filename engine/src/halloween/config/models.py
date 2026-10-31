"""Modèles de la configuration : composants et connexion Home Assistant.

Composants : relais, boutons, lumières, interrupteurs, lecteurs de vidéos.

La validation ici est locale à chaque composant. Les contrôles qui croisent plusieurs composants
(ids et broches uniques, références) sont dans `halloween.config.validation`.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# Identifiant technique : stable, utilisé dans les programmes (jamais une broche ni un entity_id).
SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
Slug = Annotated[str, StringConstraints(pattern=SLUG_PATTERN)]

_BUILTIN_IMAGE = re.compile(r"^builtin:[a-z0-9][a-z0-9-]{0,63}$")
_UPLOADED_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.(png|jpe?g|webp)$")

# Broches utilisateur du connecteur 40 broches du Raspberry Pi (numérotation BCM).
# GPIO 0 et 1 sont réservés à l'EEPROM des cartes HAT.
GpioPin = Annotated[int, Field(ge=2, le=27)]


class Model(BaseModel):
    """Base : les champs inconnus sont refusés (détecte les fautes de frappe)."""

    model_config = ConfigDict(extra="forbid")


class Component(Model):
    """Champs communs à tous les composants."""

    id: Slug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    # Icône de la bibliothèque (`builtin:<nom>`) ou fichier téléversé sous /images/.
    image: str | None = None

    @field_validator("image")
    @classmethod
    def _check_image(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if _BUILTIN_IMAGE.match(value) or _UPLOADED_IMAGE.match(value):
            return value
        raise ValueError("image invalide : attendu `builtin:<nom>` ou un fichier png/jpg/webp")


class RelayMode(StrEnum):
    LATCHED = "latched"  # maintenu : fermé jusqu'à l'extinction
    PUSH = "push"  # impulsion : l'objet joue sa propre animation


class Relay(Component):
    pin: GpioPin
    mode: RelayMode
    # Le module s'active à l'état bas ; ici `high()` active le relais, donc faux par défaut.
    active_low: bool = False
    # Mode push uniquement.
    pulse_ms: Annotated[int, Field(gt=0, le=10_000)] | None = None
    animation_s: Annotated[float, Field(gt=0)] | None = None
    # Mode latched uniquement. Absent = aucune limite d'allumage.
    max_on_seconds: Annotated[float, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def _check_mode_fields(self) -> Self:
        if self.mode is RelayMode.PUSH:
            if self.max_on_seconds is not None:
                raise ValueError("`max_on_seconds` n'est valable qu'en mode latched")
            if self.pulse_ms is None:
                self.pulse_ms = 500
        else:
            if self.pulse_ms is not None or self.animation_s is not None:
                raise ValueError("`pulse_ms` et `animation_s` ne sont valables qu'en mode push")
        return self


class Button(Component):
    """Entrée numérique : un bouton (appui court, long, double) ou un détecteur de mouvement PIR."""

    # `motion` : détecteur PIR, dont la sortie passe au niveau haut sur un mouvement.
    kind: Literal["button", "motion"] = "button"
    pin: GpioPin
    pull: Literal["up", "down"] = "up"
    debounce_ms: Annotated[int, Field(ge=0, le=1_000)] = 50
    long_press_ms: Annotated[int, Field(ge=100, le=10_000)] = 800
    double_press_ms: Annotated[int, Field(ge=100, le=2_000)] = 400
    # Détecteur seulement : détections ignorées après le démarrage du moteur (le PIR se stabilise).
    warmup_s: Annotated[int, Field(ge=0, le=600)] = 60

    @model_validator(mode="before")
    @classmethod
    def _motion_pulls_down(cls, data: Any) -> Any:
        # Sortie de PIR active à l'état haut : sauf indication contraire, résistance vers le bas.
        if isinstance(data, dict) and data.get("kind") == "motion" and "pull" not in data:
            return {**data, "pull": "down"}
        return data


def event_mismatch(button: Button, event: str) -> str | None:
    """Message si `event` ne peut jamais venir de cette entrée (détecteur : `motion` seul)."""
    if button.kind == "motion" and event != "motion":
        return (
            f"`{button.name}` est un détecteur de mouvement : seul l'événement « mouvement » existe"
        )
    if button.kind == "button" and event == "motion":
        return f"`{button.name}` est un bouton : il ne détecte pas de mouvement"
    return None


class Light(Component):
    entity_id: Annotated[str, StringConstraints(pattern=r"^light\.[a-z0-9_]+$")]
    supports_color: bool = False
    supports_brightness: bool = False
    supports_transition: bool = False


class Switch(Component):
    entity_id: Annotated[str, StringConstraints(pattern=r"^switch\.[a-z0-9_]+$")]


# Dossier média local de Home Assistant : un simple nom de fichier y est cherché.
LOCAL_MEDIA = "media-source://media_source/local/"


class Video(Model):
    id: Slug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    # Nom d'un fichier du dossier média local de Home Assistant (`halloween_video.mp4`), ou
    # n'importe quelle source que le script accepte (`media-source://...`, URL).
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
    # Durée, pour « attendre la fin » dans un scénario.
    duration_s: Annotated[float, Field(gt=0, le=86_400)] | None = None

    @property
    def media(self) -> str:
        """Valeur envoyée au script : un nom de fichier seul désigne le dossier média local."""
        if "://" in self.source or "/" in self.source:
            return self.source
        return LOCAL_MEDIA + self.source


class Player(Component):
    """Lecteur de vidéos (Shield + Kodi) piloté par un script Home Assistant.

    Le script reçoit `video` (la source) et `boucle` (vrai/faux) et lance la lecture."""

    script: Annotated[str, StringConstraints(pattern=r"^script\.[a-z0-9_]+$")]
    videos: Annotated[list[Video], Field(min_length=1)]
    # Vidéo jouée en boucle au repos (écran noir) : démarrage, arrêt global, fin de scénario.
    rest_video: Slug | None = None

    @model_validator(mode="after")
    def _check_videos(self) -> Self:
        ids = [video.id for video in self.videos]
        if len(ids) != len(set(ids)):
            raise ValueError("ids de vidéos en double")
        if self.rest_video is not None and self.rest_video not in ids:
            raise ValueError(f"vidéo de repos inconnue : `{self.rest_video}`")
        return self

    def video(self, video_id: str) -> Video | None:
        return next((v for v in self.videos if v.id == video_id), None)


class HomeAssistant(Model):
    url: str
    # Le jeton n'apparaît jamais dans repr() (donc ni dans les logs ni dans les traces).
    token: str = Field(default="", repr=False)
    # Délai maximal d'un appel à Home Assistant.
    timeout_s: Annotated[float, Field(gt=0, le=60)] = 5.0

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not re.match(r"^https?://[^\s/:]+(:\d{1,5})?(/\S*)?$", value):
            raise ValueError("URL invalide : attendu http(s)://hôte[:port]")
        return value


Channel = Annotated[int, Field(ge=0, le=255)]


class RestState(Model):
    """État nominal d'une lumière ou d'un interrupteur, appliqué au repos (fin de run, arrêt)."""

    state: Literal["on", "off"]
    rgb_color: tuple[Channel, Channel, Channel] | None = None
    brightness: Channel | None = None
    transition: Annotated[float, Field(ge=0)] | None = None


class AppConfig(Model):
    home_assistant: HomeAssistant | None = None
    relays: list[Relay] = Field(default_factory=list)
    buttons: list[Button] = Field(default_factory=list)
    lights: list[Light] = Field(default_factory=list)
    switches: list[Switch] = Field(default_factory=list)
    players: list[Player] = Field(default_factory=list)
    # Par id de lumière ou d'interrupteur. Les relais maintenus reposent toujours éteints ; les
    # composants absents d'ici ne sont pas touchés au repos.
    rest_state: dict[Slug, RestState] = Field(default_factory=dict)
