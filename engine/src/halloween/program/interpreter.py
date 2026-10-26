"""Interpréteur asyncio : exécute les scripts d'un programme.

Cette étape couvre les blocs de contrôle. Les blocs d'action sont délégués à un `ActionRunner`
(relais, lumières, interrupteurs : voir `halloween.program.actions`).
"""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from halloween.log import get_logger, log_context
from halloween.program.conditions import Conditions
from halloween.program.models import (
    CallNode,
    IfNode,
    LightNode,
    LogNode,
    Node,
    ParallelNode,
    Program,
    RandomChoiceNode,
    RelayNode,
    RepeatNode,
    Script,
    SequenceNode,
    SwitchNode,
    WaitNode,
    WaitUntilNode,
)
from halloween.program.validation import MAX_CALL_DEPTH

log = get_logger("interpreter")


class ExecutionError(Exception):
    """Incohérence détectée à l'exécution (normalement évitée par la validation)."""


@dataclass(frozen=True)
class NodeEvent:
    kind: Literal["started", "finished"]
    script_id: str
    node_id: str


class ActionRunner(ABC):
    @abstractmethod
    async def execute(self, node: RelayNode | LightNode | SwitchNode) -> None:
        """Exécute un bloc d'action."""


@dataclass
class RunContext:
    run_id: str
    actions: ActionRunner
    conditions: Conditions
    programs: Mapping[str, Program] = field(default_factory=dict)
    rng: random.Random = field(default_factory=random.Random)
    # Appelé à chaque début / fin de bloc (surlignage dans l'interface).
    emit: Callable[[NodeEvent], None] | None = None


@dataclass(frozen=True)
class _Scope:
    script_id: str
    call_depth: int = 0


class Interpreter:
    def __init__(self, context: RunContext) -> None:
        self._ctx = context

    async def run_program(self, program: Program, call_depth: int = 0) -> None:
        """Lance tous les scripts en parallèle ; termine quand tous ont fini."""
        await self._gather_all(
            [self._run_script(program, script, call_depth) for script in program.scripts]
        )

    async def _run_script(self, program: Program, script: Script, call_depth: int) -> None:
        with log_context(script_id=script.id):
            await self._run(script.root, _Scope(script.id, call_depth))

    # ------------------------------------------------------------------ exécution d'un nœud

    async def _run(self, node: Node, scope: _Scope) -> None:
        with log_context(node_id=node.id):
            self._emit("started", scope, node)
            try:
                await self._dispatch(node, scope)
            finally:
                self._emit("finished", scope, node)

    def _emit(self, kind: Literal["started", "finished"], scope: _Scope, node: Node) -> None:
        if self._ctx.emit is not None:
            self._ctx.emit(NodeEvent(kind, scope.script_id, node.id))

    async def _dispatch(self, node: Node, scope: _Scope) -> None:
        match node:
            case SequenceNode():
                for child in node.children:
                    await self._run(child, scope)
            case ParallelNode():
                coros = [self._run(child, scope) for child in node.children]
                if node.until == "first":
                    await self._gather_first(coros)
                else:
                    await self._gather_all(coros)
            case RepeatNode():
                await self._repeat(node, scope)
            case WaitNode():
                await asyncio.sleep(self._duration(node))
            case IfNode():
                if self._ctx.conditions.evaluate(node.condition):
                    await self._run(node.then, scope)
                elif node.else_ is not None:
                    await self._run(node.else_, scope)
            case WaitUntilNode():
                satisfied = await self._ctx.conditions.wait_for(node.condition, node.timeout_s)
                if not satisfied:
                    log.warning(
                        "délai écoulé avant la condition", extra={"timeout_s": node.timeout_s}
                    )
            case RandomChoiceNode():
                weights = [choice.weight for choice in node.choices]
                (picked,) = self._ctx.rng.choices(node.choices, weights=weights)
                await self._run(picked.child, scope)
            case CallNode():
                await self._call(node, scope)
            case LogNode():
                log.info(node.message)
            case RelayNode() | LightNode() | SwitchNode():
                await self._ctx.actions.execute(node)

    async def _repeat(self, node: RepeatNode, scope: _Scope) -> None:
        count = 0
        while node.forever or count < (node.times or 0):
            await self._run(node.child, scope)
            count += 1
            # Garantit que la boucle rend la main même si le corps ne contient aucune attente.
            await asyncio.sleep(0)

    def _duration(self, node: WaitNode) -> float:
        if node.seconds is not None:
            return node.seconds
        assert node.min is not None and node.max is not None
        return self._ctx.rng.uniform(node.min, node.max)

    async def _call(self, node: CallNode, scope: _Scope) -> None:
        program = self._ctx.programs.get(node.program_id)
        if program is None:
            raise ExecutionError(f"programme appelé inconnu : {node.program_id}")
        depth = scope.call_depth + 1
        if depth > MAX_CALL_DEPTH:
            raise ExecutionError(f"appels imbriqués trop profonds (max {MAX_CALL_DEPTH})")
        await self.run_program(program, depth)

    # ------------------------------------------------------------------ parallélisme

    @staticmethod
    async def _gather_all(coros: list[Coroutine[Any, Any, None]]) -> None:
        """Attend toutes les branches ; à la première erreur, annule les autres et la relance."""
        await _wait_branches(coros, asyncio.FIRST_EXCEPTION)

    @staticmethod
    async def _gather_first(coros: list[Coroutine[Any, Any, None]]) -> None:
        """Termine dès qu'une branche a fini ; annule les autres."""
        await _wait_branches(coros, asyncio.FIRST_COMPLETED)


async def _wait_branches(coros: list[Coroutine[Any, Any, None]], when: str) -> None:
    if not coros:
        return
    tasks = [asyncio.ensure_future(c) for c in coros]
    try:
        done, _ = await asyncio.wait(tasks, return_when=when)
        for task in done:
            task.result()  # relance l'exception éventuelle
    finally:
        pending = [t for t in tasks if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
