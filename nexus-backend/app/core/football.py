from enum import StrEnum


class PlayerPosition(StrEnum):
    GK = "GK"
    CB = "CB"
    LB = "LB"
    RB = "RB"
    LWB = "LWB"
    RWB = "RWB"
    DM = "DM"
    CM = "CM"
    AM = "AM"
    LW = "LW"
    RW = "RW"
    ST = "ST"
    CF = "CF"


class DominantFoot(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BOTH = "BOTH"


class PlayerStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class SquadStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    LOANED = "LOANED"
    RELEASED = "RELEASED"
