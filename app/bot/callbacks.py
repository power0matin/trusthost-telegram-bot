"""Compact, typed callback data (Telegram limit: 64 bytes). Only ids and short codes – never secrets."""
from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class Wal(CallbackData, prefix="w"):
    a: str  # t top-up prompt · go create top-up invoice
    g: str = ""  # gateway: "" = card, "u" = USDT


class Nav(CallbackData, prefix="n"):
    a: str  # home | noop | cancel


class Menu(CallbackData, prefix="m"):
    a: str  # srv | order | inv | wal | usage | support | settings | refresh


class Lang(CallbackData, prefix="lg"):
    code: str
    src: str = "s"  # s = first start, t = settings


class Srv(CallbackData, prefix="s"):
    a: str  # l list · d detail · st status · tr traffic · us usage(30d) · pw power menu
    id: int = 0
    p: int = 0
    m: str = "d"  # list mode: d = manage, u = usage picker


class Pow(CallbackData, prefix="pw"):
    a: str  # ask | do
    id: int
    act: str


class Use(CallbackData, prefix="u"):
    id: int
    d: int = 30


class Top(CallbackData, prefix="tp"):
    a: str  # q quote · s select size · p promo prompt · x remove promo · go create
    id: int
    gb: int = 0


class Ren(CallbackData, prefix="rn"):
    a: str  # s start · p promo prompt · c confirm screen · go execute
    id: int


class Cat(CallbackData, prefix="c"):
    a: str  # g groups · l products of group · p product · c choose cycle
    g: int = 0
    p: int = 0
    pid: int = 0
    cy: str = ""


class Cfg(CallbackData, prefix="cf"):
    a: str  # s select sub-option · k skip step · b previous step
    o: int = 0
    v: int = 0


class Ord(CallbackData, prefix="o"):
    a: str  # extras · host · dom · pw · gw · promo · nopromo · review · confirm · cancel · steps


class Inv(CallbackData, prefix="i"):
    a: str  # l list · d detail · pc pay-credit preview · pd pay-credit do · po online · pu usdt
    id: int = 0
    f: str = "a"
    p: int = 0


class Tkt(CallbackData, prefix="t"):
    a: str  # l list · d detail · r reply prompt · cx close confirm · cc close
    id: int = 0
    p: int = 0


class NewT(CallbackData, prefix="nt"):
    a: str  # s start · d dept · pr priority · sv service · svl service list · go submit · back
    v: int = 0
    s: str = ""
    p: int = 0


class Pref(CallbackData, prefix="st"):
    a: str  # nt toggle notification · api · health · lim · lang
    v: str = ""
