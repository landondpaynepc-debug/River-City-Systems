STAFF_ROLE_ID = 1572082374760468682


def has_staff_role(member):
    return getattr(member, "guild", None) is not None and member.get_role(STAFF_ROLE_ID) is not None
