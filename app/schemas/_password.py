MIN_PASSWORD_LENGTH = 10

# A small blocklist of extremely common passwords - FR-AUTH-03. Not exhaustive; the length
# requirement plus argon2 hashing is the primary defense, this just catches the obvious cases.
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password123",
        "123456789",
        "12345678",
        "1234567890",
        "qwertyuiop",
        "letmein123",
        "welcome123",
        "administrator",
        "iloveyou123",
        "trustno1123",
        "abc123456789",
    }
)


def validate_password_policy(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long")
    if password.lower() in _COMMON_PASSWORDS:
        raise ValueError("Password is too common; please choose a less predictable password")
    return password
