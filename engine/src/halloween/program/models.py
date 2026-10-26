"""Modèle d'un programme : un ou plusieurs scripts, chacun commençant par un bloc début.

Format décrit dans la spec 1 (§5). Chaque nœud a un `id` unique pour relier erreurs et
progression aux blocs de l'interface. Les contrôles qui dépendent de la configuration
(composants existants, mode des relais, capacités des lumières) sont dans
`halloween.program.validation`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterator
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from halloween.config.models import Slug

NodeId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
Channel = Annotated[int, Field(ge=0, le=255)]
Seconds = Annotated[float, Field(ge=0)]

MAX_EDITOR_BYTES = 256 * 1024
SCHEMA_VERSION = 1


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- conditions


class ButtonCondition(Model):
    type: Literal["button"]
    id: Slug
    event: Literal["short", "long", "double"]


class RelayIsCondition(Model):
    type: Literal["relay_is"]
    id: Slug
    state: Literal["on", "off"]


class RandomCondition(Model):
    type: Literal["random"]
    probability: Annotated[float, Field(ge=0, le=1)]


Condition = Annotated[
    ButtonCondition | RelayIsCondition | RandomCondition, Field(discriminator="type")
]


# --------------------------------------------------------------------------- blocs de contrôle


class BaseNode(Model):
    id: NodeId


class SequenceNode(BaseNode):
    type: Literal["sequence"]
    children: list[Node]


class ParallelNode(BaseNode):
    type: Literal["parallel"]
    children: list[Node]
    # `all` : termine quand toutes les branches ont fini ; `first` : dès la première.
    until: Literal["all", "first"] = "all"


class RepeatNode(BaseNode):
    type: Literal["repeat"]
    times: Annotated[int, Field(ge=1)] | None = None
    forever: bool = False
    child: Node

    @model_validator(mode="after")
    def _times_xor_forever(self) -> Self:
        if self.forever == (self.times is not None):
            raise ValueError("indiquer soit `times`, soit `forever: true`")
        return self


class WaitNode(BaseNode):
    type: Literal["wait"]
    seconds: Seconds | None = None
    min: Seconds | None = None
    max: Seconds | None = None

    @model_validator(mode="after")
    def _fixed_or_random(self) -> Self:
        random_range = self.min is not None or self.max is not None
        if (self.seconds is not None) == random_range:
            raise ValueError("indiquer soit `seconds`, soit `min` et `max`")
        if random_range:
            if self.min is None or self.max is None:
                raise ValueError("`min` et `max` vont ensemble")
            if self.min > self.max:
                raise ValueError("`min` doit être inférieur ou égal à `max`")
        return self


class IfNode(BaseNode):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    type: Literal["if"]
    condition: Condition
    then: Node
    else_: Node | None = Field(default=None, alias="else")


class WaitUntilNode(BaseNode):
    type: Literal["wait_until"]
    condition: Condition
    timeout_s: Annotated[float, Field(gt=0)] | None = None


class Choice(Model):
    weight: Annotated[float, Field(gt=0)] = 1
    child: Node


class RandomChoiceNode(BaseNode):
    type: Literal["random_choice"]
    choices: Annotated[list[Choice], Field(min_length=1)]


class CallNode(BaseNode):
    type: Literal["call"]
    program_id: Slug


class LogNode(BaseNode):
    type: Literal["log"]
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]


# --------------------------------------------------------------------------- blocs d'action


class ActionNode(BaseNode):
    # Ne pas attendre la réponse de l'appareil avant de passer au bloc suivant.
    fire_and_forget: bool = False
    # Que faire si l'action échoue : continuer le run (défaut) ou l'arrêter.
    on_error: Literal["continue", "abort"] = "continue"


class RelayNode(ActionNode):
    type: Literal["relay"]
    target: Slug
    state: Literal["on", "off"] | None = None  # relais latched
    action: Literal["trigger"] | None = None  # relais push
    wait_for_end: bool = False

    @model_validator(mode="after")
    def _state_xor_action(self) -> Self:
        if (self.state is None) == (self.action is None):
            raise ValueError("indiquer soit `state` (latched), soit `action: trigger` (push)")
        if self.wait_for_end and self.action is None:
            raise ValueError("`wait_for_end` ne vaut que pour `action: trigger`")
        return self


class LightNode(ActionNode):
    type: Literal["light"]
    target: Slug
    state: Literal["on", "off"]
    rgb_color: tuple[Channel, Channel, Channel] | None = None
    brightness: Channel | None = None
    transition: Seconds | None = None


class SwitchNode(ActionNode):
    type: Literal["switch"]
    target: Slug
    state: Literal["on", "off"]


Node = Annotated[
    SequenceNode
    | ParallelNode
    | RepeatNode
    | WaitNode
    | IfNode
    | WaitUntilNode
    | RandomChoiceNode
    | CallNode
    | LogNode
    | RelayNode
    | LightNode
    | SwitchNode,
    Field(discriminator="type"),
]

for _model in (SequenceNode, ParallelNode, RepeatNode, IfNode, Choice, RandomChoiceNode):
    _model.model_rebuild()


# --------------------------------------------------------------------------- scripts et programme


class Hat(Model):
    # Seul type de début en v1 : au lancement du programme.
    type: Literal["start"] = "start"


class Script(Model):
    id: NodeId
    hat: Hat = Field(default_factory=Hat)
    root: Node


class Program(Model):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # `schema` masquerait une méthode de pydantic : on l'expose sous cet alias.
    schema_version: Literal[1] = Field(default=SCHEMA_VERSION, alias="schema")
    id: Slug
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    # Absent = aucune limite (nécessaire pour une ambiance en boucle infinie).
    max_duration_s: Annotated[float, Field(gt=0)] | None = None
    on_end: Literal["reset", "keep"] = "reset"
    show: bool = False
    show_order: int | None = None
    revision: Annotated[int, Field(ge=0)] = 0
    # Mise en page de l'éditeur : ignorée par le moteur, taille limitée.
    editor: dict | None = None
    scripts: Annotated[list[Script], Field(min_length=1)]

    @model_validator(mode="after")
    def _structure(self) -> Self:
        if self.editor is not None and len(json.dumps(self.editor, default=str)) > MAX_EDITOR_BYTES:
            raise ValueError(f"`editor` dépasse {MAX_EDITOR_BYTES // 1024} Ko")
        script_ids = [s.id for s in self.scripts]
        if len(script_ids) != len(set(script_ids)):
            raise ValueError("ids de scripts en double")
        counts = Counter(n.id for n in self.nodes())
        duplicates = sorted(i for i, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"ids de nœuds en double : {', '.join(duplicates)}")
        return self

    def nodes(self) -> Iterator[Node]:
        """Tous les nœuds de tous les scripts, en profondeur d'abord."""
        for script in self.scripts:
            yield from walk(script.root)

    def to_json(self) -> dict:
        """Représentation JSON du format de la spec (clés `schema` et `else`)."""
        return self.model_dump(mode="json", by_alias=True)


def child_nodes(node: Node) -> list[Node]:
    match node:
        case SequenceNode() | ParallelNode():
            return list(node.children)
        case RepeatNode():
            return [node.child]
        case IfNode():
            return [node.then] + ([node.else_] if node.else_ is not None else [])
        case RandomChoiceNode():
            return [choice.child for choice in node.choices]
        case _:
            return []


def walk(node: Node) -> Iterator[Node]:
    yield node
    for child in child_nodes(node):
        yield from walk(child)
