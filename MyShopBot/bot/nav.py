"""Навигация: стек «Назад», конечная точка — «Меню» при пустом стеке."""

from typing import Any, Dict, List, Optional


def _stack(ud: Dict[str, Any]) -> List[str]:
    return ud.setdefault("nav_stack", [])


def current_screen(ud: Dict[str, Any]) -> Optional[str]:
    return ud.get("screen")


def set_screen(ud: Dict[str, Any], name: str) -> None:
    ud["screen"] = name


def push_nav(ud: Dict[str, Any], new_screen: str) -> None:
    old = ud.get("screen")
    if old == new_screen:
        return
    if old:
        _stack(ud).append(old)
    set_screen(ud, new_screen)


def reset_nav(ud: Dict[str, Any], screen: str = "start") -> None:
    ud["nav_stack"] = []
    set_screen(ud, screen)


def nav_back(ud: Dict[str, Any]) -> str:
    stack = _stack(ud)
    if stack:
        target = stack.pop()
        set_screen(ud, target)
        return target
    set_screen(ud, "menu")
    return "menu"
